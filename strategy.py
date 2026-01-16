"""
Trading Strategy Module: ASMM v3.2 Pro - High Win Rate Strategy.
Implements 3/5 signal requirement for LONG and SHORT entries.
Target: 60%+ win rate with BTC + ETH trading.
"""

import pandas as pd
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from config import config
from indicators import (
    calculate_all_indicators,
    is_ema_bullish, is_ema_bearish,
    is_rsi_bullish, is_rsi_bearish,
    is_macd_bullish, is_macd_bearish,
    is_trending
)
from nansen import nansen_client, NansenSignal, SignalType
from exchange import exchange_client
from logger import log_info, log_debug, log_signal, log_warning


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class SignalDetails:
    """Details of each individual signal."""
    smart_money: bool
    trend_structure: bool
    momentum: bool
    trending_market: bool
    favorable_positioning: bool
    
    opposite_money: bool = False
    
    @property
    def count(self) -> int:
        return sum([
            self.smart_money,
            self.trend_structure,
            self.momentum,
            self.trending_market,
            self.favorable_positioning
        ])
    
    def to_dict(self) -> Dict[str, bool]:
        return {
            'smart_money': self.smart_money,
            'opposite_money': self.opposite_money,
            'trend_structure': self.trend_structure,
            'momentum': self.momentum,
            'trending_market': self.trending_market,
            'favorable_positioning': self.favorable_positioning
        }


@dataclass
class TradeSignal:
    """Complete trade signal for ASMM v3.2 Pro."""
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profit_1: float  # TP1: 60% close at 2×ATR
    take_profit_2: float  # TP2: 40% close at 3×ATR
    breakeven_stop: float
    position_size: float
    leverage: int
    notional_value: float
    risk_amount: float
    risk_pct: float
    atr: float
    signal_count: int
    signals: SignalDetails
    conviction: str  # HIGH (5/5), STANDARD (4/5) or LOW (3/5)
    indicators: Dict[str, float]
    nansen_data: Dict[str, Any]
    nansen_signal: Optional['NansenSignal']  # The actual Nansen signal object
    funding_rate: float
    long_short_ratio: float
    timestamp: datetime
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'direction': self.direction.value,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'tp1': self.take_profit_1,
            'tp2': self.take_profit_2,
            'breakeven_stop': self.breakeven_stop,
            'position_size': self.position_size,
            'leverage': self.leverage,
            'notional_value': self.notional_value,
            'risk_amount': self.risk_amount,
            'risk_pct': self.risk_pct,
            'atr': self.atr,
            'signal_count': self.signal_count,
            'signals': self.signals.to_dict(),
            'conviction': self.conviction,
            'indicators': self.indicators,
            'funding_rate': self.funding_rate,
            'long_short_ratio': self.long_short_ratio,
            'timestamp': self.timestamp.isoformat()
        }


class ASMMv32ProStrategy:
    """
    ASMM v3.2 Pro Strategy Implementation.
    
    LONG Entry Signals (3/5 required):
    1. Nansen Smart Money Accumulation
    2. Strong Trend Structure (Price > EMA20 > EMA50, both rising)
    3. Momentum Confirmation (RSI 50-70 + MACD positive)
    4. Trending Market (ADX > 25)
    5. Favorable Positioning (Funding < 0.05% + LS Ratio < 1.2)
    
    SHORT Entry Signals (3/5 required):
    1. Nansen Smart Money Distribution
    2. Strong Trend Structure (Price < EMA20 < EMA50, both falling)
    3. Momentum Confirmation (RSI 30-50 + MACD negative)
    4. Trending Market (ADX > 25)
    5. Favorable Positioning (Funding > 0.05% + LS Ratio > 0.8)
    """
    
    def __init__(self):
        self.strategy_name = config.strategy_name
    
    def check_early_exit(self, symbol: str, trade) -> Tuple[bool, str]:
        """
        Check for early exit conditions.
        
        Returns:
            (should_exit, reason) - True if early exit warranted
        """
        # 1. Nansen distribution check for longs
        nansen_signal = nansen_client.get_signal(symbol)
        if nansen_signal:
            if nansen_signal.signal_type == SignalType.DISTRIBUTION and trade.direction == 'long':
                return True, "Nansen Smart Money Distribution detected"
            elif nansen_signal.signal_type == SignalType.ACCUMULATION and trade.direction == 'short':
                return True, "Nansen Smart Money Accumulation detected"
        
        # 2. Extreme funding rate check (>0.1% or <-0.1%)
        funding = exchange_client.get_funding_rate(symbol)
        if funding is not None and abs(funding) > 0.001:
            return True, f"Extreme Funding Rate: {funding:.4f}"
        
        return False, ""
        
    def check_long_signals(
        self, 
        symbol: str,
        indicators: Dict[str, float],
        indicators_1h: Dict[str, float],
        funding_rate: float,
        ls_ratio: float
    ) -> Tuple[SignalDetails, int, str]:
        """
        Check LONG entry signals (3/5 required).
        
        Returns:
            (signals, signal_count, conviction)
        """
        # Signal 1: Nansen Smart Money Accumulation
        nansen_signal = nansen_client.get_signal(symbol)
        smart_money = False
        opposite_money = False
        if nansen_signal:
            smart_money = nansen_signal.is_bullish
            opposite_money = nansen_signal.is_bearish
        
        # Signal 2: Strong Trend Structure (EMA)
        trend_structure = is_ema_bullish(indicators)
        
        # Signal 3: Momentum Confirmation (RSI 4H + MACD 1H)
        rsi_ok = is_rsi_bullish(indicators['rsi'])
        macd_ok = is_macd_bullish(indicators_1h['macd'], indicators_1h['macd_signal'])
        momentum = rsi_ok and macd_ok
        
        # Signal 4: Trending Market (ADX > 25)
        trending_market = is_trending(indicators['adx'])
        
        # Signal 5: Favorable Positioning
        funding_ok = funding_rate < config.funding_long_max
        ratio_ok = ls_ratio < config.ls_ratio_long_max
        favorable_positioning = funding_ok and ratio_ok
        
        signals = SignalDetails(
            smart_money=smart_money,
            opposite_money=opposite_money,
            trend_structure=trend_structure,
            momentum=momentum,
            trending_market=trending_market,
            favorable_positioning=favorable_positioning
        )
        
        signal_count = signals.count
        
        # v3.3.1 Conviction Logic
        if opposite_money:
            conviction = "NONE"
        elif smart_money:
            if signal_count >= 4:
                conviction = "HIGH"      # Tier 1: 6x
            elif signal_count == 3:
                conviction = "LOW"       # Tier 2: 3x
            else:
                conviction = "NONE"
        else: # Neutral
            if signal_count == 4:        # Must be 4/5 (all technicals)
                conviction = "LOW"       # Tier 2: 3x
            else:
                conviction = "NONE"
        
        return signals, signal_count, conviction
    
    def check_short_signals(
        self,
        symbol: str,
        indicators: Dict[str, float],
        indicators_1h: Dict[str, float],
        funding_rate: float,
        ls_ratio: float
    ) -> Tuple[SignalDetails, int, str]:
        """
        Check SHORT entry signals (3/5 required).
        
        Returns:
            (signals, signal_count, conviction)
        """
        # Signal 1: Nansen Smart Money Distribution
        nansen_signal = nansen_client.get_signal(symbol)
        smart_money = False
        opposite_money = False
        if nansen_signal:
            smart_money = nansen_signal.is_bearish
            opposite_money = nansen_signal.is_bullish
        
        # Signal 2: Strong Trend Structure (EMA bearish)
        trend_structure = is_ema_bearish(indicators)
        
        # Signal 3: Momentum Confirmation (RSI 4H + MACD 1H)
        rsi_ok = is_rsi_bearish(indicators['rsi'])
        macd_ok = is_macd_bearish(indicators_1h['macd'], indicators_1h['macd_signal'])
        momentum = rsi_ok and macd_ok
        
        # Signal 4: Trending Market (ADX > 25)
        trending_market = is_trending(indicators['adx'])
        
        # Signal 5: Favorable Positioning (crowded longs)
        funding_ok = funding_rate > config.funding_short_min
        ratio_ok = ls_ratio > config.ls_ratio_short_min
        favorable_positioning = funding_ok and ratio_ok
        
        signals = SignalDetails(
            smart_money=smart_money,
            opposite_money=opposite_money,
            trend_structure=trend_structure,
            momentum=momentum,
            trending_market=trending_market,
            favorable_positioning=favorable_positioning
        )
        
        signal_count = signals.count
        
        # v3.3.1 Conviction Logic
        if opposite_money:
            conviction = "NONE"
        elif smart_money:
            if signal_count >= 4:
                conviction = "HIGH"      # Tier 1: 6x
            elif signal_count == 3:
                conviction = "LOW"       # Tier 2: 3x
            else:
                conviction = "NONE"
        else: # Neutral
            if signal_count == 4:        # Must be 4/5 (all technicals)
                conviction = "LOW"       # Tier 2: 3x
            else:
                conviction = "NONE"
        
        return signals, signal_count, conviction
    
    def calculate_exits(
        self, 
        entry_price: float, 
        direction: TradeDirection, 
        conviction: str = "LOW"
    ) -> Dict[str, float]:
        """
        Calculate stop loss and take profit levels.
        
        ASMM v3.3 Exit Strategy (Fixed Percentage):
        - SL = 2% (Tier 2) or 3% (Tier 1)
        - TP1 = 3% profit - Close 60%
        - TP2 = 6% profit - Close 40%
        """
        # Determine stop loss percentage based on conviction
        if conviction in ["HIGH", "STANDARD"]:
            sl_pct = config.stop_loss_pct_high  # 3%
        else:
            sl_pct = config.stop_loss_pct  # 2%
        
        tp1_pct = config.tp1_pct  # 3%
        tp2_pct = config.tp2_pct  # 6%
        
        if direction == TradeDirection.LONG:
            stop_loss = entry_price * (1 - sl_pct)
            tp1 = entry_price * (1 + tp1_pct)
            tp2 = entry_price * (1 + tp2_pct)
            breakeven_stop = entry_price * 1.005  # 0.5% above entry
        else:  # SHORT
            stop_loss = entry_price * (1 + sl_pct)
            tp1 = entry_price * (1 - tp1_pct)
            tp2 = entry_price * (1 - tp2_pct)
            breakeven_stop = entry_price * 0.995  # 0.5% below entry
        
        return {
            'stop_loss': round(stop_loss, 2),
            'tp1': round(tp1, 2),
            'tp2': round(tp2, 2),
            'breakeven_stop': round(breakeven_stop, 2),
            'stop_distance': entry_price * sl_pct  # For risk calc
        }
    
    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        conviction: str
    ) -> Tuple[float, int, float, float, float]:
        """
        Calculate position size for ASMM v3.2 Pro.
        
        - Tier 1 (5/5 or 4/5): 3% risk, 5x leverage
        - Tier 2 (3/5): 2% risk, 4x leverage
        
        Returns:
            (position_size, leverage, notional_value, risk_amount, risk_pct)
        """
        if conviction == "HIGH":  # Tier 1 (Nansen Active + 4/5 signals)
            risk_pct = config.high_conviction_risk_pct  # 3%
            leverage = config.high_conviction_leverage   # 6x
        else:  # LOW / STANDARD (Tier 2 - Nansen Active 3/5 or Neutral 4/5)
            risk_pct = config.base_risk_pct  # 2%
            leverage = config.base_leverage  # 3x
        
        risk_amount = account_balance * risk_pct
        risk_per_unit = abs(entry_price - stop_loss)
        
        if risk_per_unit == 0:
            return 0, leverage, 0, 0, risk_pct
        
        # Base position size from risk
        base_size = risk_amount / risk_per_unit
        
        # Apply leverage
        position_size = base_size * leverage
        notional_value = position_size * entry_price
        
        # Check Bybit minimum (0.001 BTC, 0.01 ETH)
        min_size = 0.001 if 'BTC' in str(entry_price > 10000) else 0.01
        
        if position_size < min_size:
            log_warning(f"Position size {position_size} below minimum {min_size}")
            return 0, leverage, 0, 0, risk_pct
        
        return (
            round(position_size, 4),
            leverage,
            round(notional_value, 2),
            round(risk_amount, 2),
            risk_pct
        )
    
    def generate_signal(
        self, 
        symbol: str, 
        account_equity: float
    ) -> Optional[TradeSignal]:
        """
        Generate ASMM v3.2 Pro trading signal.
        
        Returns TradeSignal if 3/5, 4/5 or 5/5 conditions met, None otherwise.
        """
        log_debug(f"Analyzing {symbol} for ASMM v3.2 Pro signal...")
        
        # Fetch 4H OHLCV data
        df_4h = exchange_client.get_ohlcv(symbol, config.signal_timeframe, limit=100)
        if df_4h is None or len(df_4h) < 50:
            log_warning(f"{symbol}: Insufficient 4H data")
            return None
        
        # Fetch 1H OHLCV data for MACD confirmation
        df_1h = exchange_client.get_ohlcv(symbol, config.momentum_timeframe, limit=50)
        if df_1h is None or len(df_1h) < 30:
            log_warning(f"{symbol}: Insufficient 1H data")
            return None
        
        # Calculate indicators
        indicators_4h = calculate_all_indicators(df_4h)
        indicators_1h = calculate_all_indicators(df_1h)
        
        # Get funding rate and long/short ratio
        funding_rate = exchange_client.get_funding_rate(symbol) or 0.0
        ls_ratio = exchange_client.get_long_short_ratio(symbol) or 1.0
        
        # Check LONG signals
        long_signals, long_count, long_conviction = self.check_long_signals(
            symbol, indicators_4h, indicators_1h, funding_rate, ls_ratio
        )
        
        # Check SHORT signals
        short_signals, short_count, short_conviction = self.check_short_signals(
            symbol, indicators_4h, indicators_1h, funding_rate, ls_ratio
        )
        
        # Decision
        if long_conviction != "NONE":
            direction = TradeDirection.LONG
            conviction = long_conviction
            signals = long_signals
            signal_count = long_count
        elif short_conviction != "NONE":
            direction = TradeDirection.SHORT
            conviction = short_conviction
            signals = short_signals
            signal_count = short_count
        else:
            log_debug(f"{symbol}: Signals insufficient or Nansen conflict (L:{long_count}/5, S:{short_count}/5)")
            return None
        
        # Calculate entry and exits (v3.3: percentage-based)
        entry_price = indicators_4h['price']
        exits = self.calculate_exits(entry_price, direction, conviction)
        
        # Calculate position size
        pos_size, leverage, notional, risk_amt, risk_pct = self.calculate_position_size(
            account_equity, entry_price, exits['stop_loss'], conviction
        )
        
        if pos_size <= 0:
            log_warning(f"{symbol}: Position size too small")
            return None
        
        # Get Nansen data for logging
        nansen_signal = nansen_client.get_signal(symbol)
        nansen_data = {
            'smart_money_netflow': nansen_signal.smart_money_netflow if nansen_signal else 0,
            'exchange_netflow': nansen_signal.exchange_netflow if nansen_signal else 0,
        }
        
        signal = TradeSignal(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=exits['stop_loss'],
            take_profit_1=exits['tp1'],
            take_profit_2=exits['tp2'],
            breakeven_stop=exits['breakeven_stop'],
            position_size=pos_size,
            leverage=leverage,
            notional_value=notional,
            risk_amount=risk_amt,
            risk_pct=risk_pct,
            atr=indicators_4h.get('atr', 0.0),
            signal_count=signal_count,
            signals=signals,
            conviction=conviction,
            indicators=indicators_4h,
            nansen_data=nansen_data,
            nansen_signal=nansen_signal,
            funding_rate=funding_rate,
            long_short_ratio=ls_ratio,
            timestamp=datetime.now()
        )
        
        log_signal(
            symbol=symbol,
            signal_type=f"ASMM_v32_{direction.value.upper()}",
            strength=signal_count / 5,
            details=f"Conviction: {conviction} ({signal_count}/5) | Risk: {risk_pct*100:.0f}% | Lev: {leverage}x"
        )
        
        return signal


# Global instance
trading_strategy = ASMMv32ProStrategy()
