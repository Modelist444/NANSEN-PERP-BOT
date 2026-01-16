"""
Trading strategy module: Adaptive Smart-Money Momentum (ASMM).
Combines Nansen smart money signals with price action, VWAP, Open Interest, and Funding Rates.
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from config import config
from nansen import nansen_client, NansenSignal, SignalType
from exchange import exchange_client
from logger import log_info, log_debug, log_signal

class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"

@dataclass
class TradeSignal:
    """Represents a complete trade signal with entry/exit levels for ASMM."""
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profit_1: float  # Partial TP at 1.5R
    take_profit_2: float  # Final TP at 3R+
    position_size: float
    atr: float
    nansen_signal: NansenSignal
    oi_trend: str
    funding_rate: float
    is_vwap_confirmed: bool
    timestamp: datetime
    
    @property
    def risk_reward_1(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit_1 - self.entry_price)
        return reward / risk if risk > 0 else 0
        
    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'direction': self.direction.value,
            'entry': self.entry_price,
            'stop_loss': self.stop_loss,
            'tp_partial': self.take_profit_1,
            'tp_final': self.take_profit_2,
            'size': self.position_size,
            'atr': self.atr,
            'oi_trend': self.oi_trend,
            'funding': self.funding_rate,
            'vwap_ok': self.is_vwap_confirmed,
            'timestamp': self.timestamp.isoformat()
        }

class ASMMStrategy:
    """Implement the Adaptive Smart-Money Momentum strategy."""
    
    def __init__(self):
        self.lookback = 20
        self.atr_period = config.atr_period
        
    def calculate_atr(self, df: pd.DataFrame) -> float:
        """Calculate current ATR."""
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        tr = pd.concat([high - low, abs(high - close), abs(low - close)], axis=1).max(axis=1)
        return float(tr.rolling(window=self.atr_period).mean().iloc[-1])

    def calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Calculate Volume Weighted Average Price."""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        return (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

    def get_oi_trend(self, symbol: str) -> str:
        """Determine OI trend (Rising, Falling, Flat)."""
        # In a real scenario, we'd fetch historical OI. For now, we compare current to previous.
        # Since Bybit fetch_open_interest usually returns current, we'd need to store/cache.
        # Placeholder for real OI trend logic.
        return "rising" # Assume rising for now or fetch historical if supported by exchange

    def analyze_timeframes(self, symbol: str) -> Dict[str, Any]:
        """Perform multi-timeframe analysis."""
        results = {}
        for tf in config.signal_timeframes:
            df = exchange_client.get_ohlcv(symbol, tf, limit=50)
            if df is not None:
                df['vwap'] = self.calculate_vwap(df)
                current_price = df['close'].iloc[-1]
                vwap = df['vwap'].iloc[-1]
                
                results[tf] = {
                    'price_above_vwap': current_price > vwap,
                    'is_reclaiming_vwap': current_price > vwap and df['close'].iloc[-2] <= df['vwap'].iloc[-2],
                    'atr': self.calculate_atr(df),
                    'atr_increasing': self.calculate_atr(df) > self.calculate_atr(df.iloc[:-1])
                }
        return results

    def check_early_exit(self, symbol: str, current_signal: TradeSignal) -> Tuple[bool, str]:
        """Check for early exit conditions."""
        # 1. Nansen distribution
        nansen_signal = nansen_client.get_signal(symbol)
        if nansen_signal and nansen_signal.signal_type == SignalType.DISTRIBUTION and current_signal.direction == TradeDirection.LONG:
            return True, "Nansen Smart Money Distribution"
        
        # 2. Funding extreme (>0.1% or <-0.1%)
        funding = exchange_client.get_funding_rate(symbol)
        if funding and abs(funding) > 0.001:
            return True, f"Extreme Funding: {funding:.4f}"
            
        return False, ""

    def generate_signal(self, symbol: str, account_equity: float) -> Optional[TradeSignal]:
        """Generate ASMM signal based on entry conditions."""
        log_debug(f"Analyzing {symbol} for ASMM signal...")
        
        # 1. Nansen Signal (Inflow or Exchange Outflow)
        nansen_signal = nansen_client.get_signal(symbol)
        if not nansen_signal:
            return None
            
        is_accumulation = (nansen_signal.signal_type == SignalType.ACCUMULATION or 
                          nansen_signal.exchange_netflow < 0)
                          
        if not is_accumulation:
            log_debug(f"{symbol}: No Nansen accumulation/outflow")
            return None

        # 2. Multi-timeframe Technicals
        tf_data = self.analyze_timeframes(symbol)
        if not tf_data or "1h" not in tf_data:
            return None
            
        h1 = tf_data["1h"]
        if not (h1['price_above_vwap'] or h1['is_reclaiming_vwap']):
            log_debug(f"{symbol}: Price below VWAP on 1h")
            return None
            
        if not h1['atr_increasing']:
            log_debug(f"{symbol}: Volatility (ATR) not increasing on 1h")
            return None

        # 3. Funding Check (Neutral to slightly negative for Longs)
        funding = exchange_client.get_funding_rate(symbol)
        if funding is not None and funding > 0.0005: # > 0.05% is getting expensive/crowded
            log_debug(f"{symbol}: Funding too high ({funding:.4f})")
            return None

        # 4. Entry price check on 5m
        df_5m = exchange_client.get_ohlcv(symbol, "5m", limit=20)
        if df_5m is None:
            return None
            
        current_price = df_5m['close'].iloc[-1]
        atr = self.calculate_atr(df_5m)
        
        # Calculate stops and targets
        # ATR-based stop (clamp to 0.8% - 1.2% in risk_manager, but calculate baseline here)
        stop_dist = atr * config.atr_stop_multiplier
        stop_loss = current_price - stop_dist
        
        risk = current_price - stop_loss
        tp_1 = current_price + (risk * 1.5) # Partial 1.5R
        tp_2 = current_price + (risk * 3.0) # Final 3R
        
        # Position sizing (4% risk)
        from risk import risk_manager
        pos_size = risk_manager.calculate_position_size(account_equity, current_price, stop_loss, symbol)
        
        if pos_size <= 0:
            return None

        signal = TradeSignal(
            symbol=symbol,
            direction=TradeDirection.LONG,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit_1=tp_1,
            take_profit_2=tp_2,
            position_size=pos_size,
            atr=atr,
            nansen_signal=nansen_signal,
            oi_trend="rising", # Placeholder
            funding_rate=funding or 0.0,
            is_vwap_confirmed=h1['price_above_vwap'],
            timestamp=datetime.now()
        )
        
        log_signal(
            symbol=symbol,
            signal_type="ASMM_LONG",
            strength=nansen_signal.strength,
            details=f"Entry: {current_price:.2f} | 1.5R TP: {tp_1:.2f} | 3R TP: {tp_2:.2f}"
        )
        
        return signal

# Global instance
trading_strategy = ASMMStrategy()
