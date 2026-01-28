"""
Trading Strategy Module: Nansen Smart Money Flow Strategy v4.0.
Signal Generation: Nansen Accumulation/Distribution + EMA Trend + RSI Filter.
Exits: ATR-based Stop Loss (1.5x) and Take Profit (2.5x).
"""

import pandas as pd
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from config import config
from indicators import (
    calculate_all_indicators,
    get_trend_direction,
    is_rsi_valid_for_long, is_rsi_valid_for_short,
    is_ema_bullish, is_ema_bearish
)
from nansen import nansen_client, NansenSignal, SignalType
from exchange import exchange_client
from logger import log_info, log_debug, log_signal, log_warning


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class SignalDetails:
    """Details of each individual signal for v4.0 Full Audit."""
    nansen_signal: bool          # Accumulation/Distribution detected
    nansen_type: str             # 'accumulation', 'distribution', 'neutral'
    trend_aligned: bool          # Primary TF EMA trend matches Nansen
    rsi_valid: bool              # RSI not overextended
    confidence_score: float      # Nansen confidence (0.0-1.0)
    mtf_alignment: Dict[str, str] = None # {4H: 'uptrend', 1H: 'uptrend', 15M: 'neutral'}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'nansen_signal': self.nansen_signal,
            'nansen_type': self.nansen_type,
            'trend_aligned': self.trend_aligned,
            'mtf_alignment': self.mtf_alignment or {},
            'rsi_valid': self.rsi_valid,
            'confidence_score': self.confidence_score
        }


@dataclass
class TradeSignal:
    """Complete trade signal for Nansen SMF Strategy v4.0."""
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float            # 1.5x ATR
    take_profit: float          # 2.5x ATR
    trailing_stop: float        # 1x ATR
    position_size: float
    leverage: int
    notional_value: float
    risk_amount: float
    risk_pct: float
    atr: float
    stop_distance_atr: float    # ATR stop distance in price units
    signals: SignalDetails
    conviction: str             # HIGH or STANDARD
    indicators: Dict[str, float]
    nansen_signal: Optional['NansenSignal']
    timestamp: datetime
    account_balance: float = 0.0 # Balance at entry
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'direction': self.direction.value,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'trailing_stop': self.trailing_stop,
            'position_size': self.position_size,
            'leverage': self.leverage,
            'notional_value': self.notional_value,
            'risk_amount': self.risk_amount,
            'risk_pct': self.risk_pct,
            'atr': self.atr,
            'stop_distance_atr': self.stop_distance_atr,
            'signals': self.signals.to_dict(),
            'conviction': self.conviction,
            'indicators': self.indicators,
            'confidence_score': self.signals.confidence_score,
            'timestamp': self.timestamp.isoformat(),
            'account_balance': self.account_balance
        }


class NansenSMFStrategy:
    """
    Nansen Smart Money Flow Strategy v4.0 Implementation.
    
    SIGNAL GENERATION:
    1. Nansen Signal (Weight=2, MANDATORY): Accumulation/Distribution with confidence score.
    2. EMA Trend Alignment: Must match Nansen direction.
       - Accumulation + Uptrend -> Valid LONG
       - Distribution + Downtrend -> Valid SHORT
       - Otherwise -> IGNORE
    3. RSI Filter: Avoid overextended entries.
       - LONG: RSI < 70
       - SHORT: RSI > 30
    
    EXITS (ATR-based):
    - Stop Loss: 1.5x ATR
    - Take Profit: 2.5x ATR
    - Optional Trailing: 1x ATR on 30% of position
    
    RISK:
    - Per-trade risk: 2-3% of account
    - Default leverage: 4x
    """
    
    def __init__(self):
        self.strategy_name = config.strategy_name
        self.strategy_version = config.strategy_version
    
    def check_early_exit(self, symbol: str, trade) -> Tuple[bool, str]:
        """
        Check for early exit conditions.
        
        Returns:
            (should_exit, reason) - True if early exit warranted
        """
        nansen_signal = nansen_client.get_signal(symbol)
        if nansen_signal:
            # Exit LONG if Distribution signal appears
            if nansen_signal.signal_type == SignalType.DISTRIBUTION and trade.direction == 'long':
                return True, "Nansen Distribution detected - exit LONG"
            # Exit SHORT if Accumulation signal appears
            elif nansen_signal.signal_type == SignalType.ACCUMULATION and trade.direction == 'short':
                return True, "Nansen Accumulation detected - exit SHORT"
        
        return False, ""
    
    def validate_signal(
        self,
        symbol: str,
        indicators: Dict[str, float]
    ) -> Tuple[Optional[TradeDirection], SignalDetails]:
        """
        Validate trading signal based on v4.0 rules.
        
        Returns:
            (direction, signal_details) - direction is None if no valid signal
        """
        # Step 1: Get Nansen Signal (MANDATORY)
        nansen_signal = nansen_client.get_signal(symbol)
        
        if nansen_signal is None or nansen_signal.is_neutral:
            log_debug(f"{symbol}: No valid Nansen signal (neutral or missing)")
            return None, SignalDetails(
                nansen_signal=False,
                nansen_type='neutral',
                trend_aligned=False,
                rsi_valid=False,
                confidence_score=0.0
            )
        
        nansen_type = nansen_signal.signal_type.value
        confidence = nansen_signal.confidence_score
        
        # Step 2: Get Trend Direction from EMA
        trend = get_trend_direction(indicators)
        rsi = indicators['rsi']
        
        # Step 3: Validate based on Nansen + Trend + RSI
        direction = None
        trend_aligned = False
        rsi_valid = False
        
        if nansen_signal.is_bullish:  # ACCUMULATION
            trend_aligned = (trend == 'uptrend')
            rsi_valid = is_rsi_valid_for_long(rsi)
            
            if trend_aligned and rsi_valid:
                direction = TradeDirection.LONG
            else:
                log_debug(f"{symbol}: Accumulation but trend={trend}, RSI={rsi:.1f} (valid={rsi_valid})")
                
        elif nansen_signal.is_bearish:  # DISTRIBUTION
            trend_aligned = (trend == 'downtrend')
            rsi_valid = is_rsi_valid_for_short(rsi)
            
            if trend_aligned and rsi_valid:
                direction = TradeDirection.SHORT
            else:
                log_debug(f"{symbol}: Distribution but trend={trend}, RSI={rsi:.1f} (valid={rsi_valid})")
        
        signal_details = SignalDetails(
            nansen_signal=True,
            nansen_type=nansen_type,
            trend_aligned=trend_aligned,
            rsi_valid=rsi_valid,
            confidence_score=confidence
        )
        
        return direction, signal_details
    
    def calculate_exits(
        self,
        entry_price: float,
        direction: TradeDirection,
        atr: float
    ) -> Dict[str, float]:
        """
        Calculate ATR-based exit levels for v4.0.
        
        - Stop Loss: 1.5x ATR
        - Take Profit: 2.5x ATR
        - Trailing Stop: 1x ATR (optional, for 30% position)
        """
        sl_distance = atr * config.stop_loss_atr_mult      # 1.5x ATR
        tp_distance = atr * config.take_profit_atr_mult    # 2.5x ATR
        trail_distance = atr * config.trailing_stop_atr_mult  # 1x ATR
        
        if direction == TradeDirection.LONG:
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
            trailing_stop = entry_price - trail_distance
        else:  # SHORT
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance
            trailing_stop = entry_price + trail_distance
        
        return {
            'stop_loss': round(stop_loss, 2),
            'take_profit': round(take_profit, 2),
            'trailing_stop': round(trailing_stop, 2),
            'stop_distance': sl_distance
        }
    
    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        conviction: str
    ) -> Tuple[float, int, float, float, float]:
        """
        Calculate position size for v4.0.
        
        - Risk: 2% (standard) or 3% (high conviction)
        - Leverage: 4x default
        
        Returns:
            (position_size, leverage, notional_value, risk_amount, risk_pct)
        """
        if conviction == "HIGH":
            risk_pct = config.high_conviction_risk_pct  # 3%
            leverage = config.high_conviction_leverage  # 4x
        else:
            risk_pct = config.base_risk_pct  # 2%
            leverage = config.base_leverage  # 4x
        
        risk_amount = account_balance * risk_pct
        risk_per_unit = abs(entry_price - stop_loss)
        
        if risk_per_unit == 0:
            return 0, leverage, 0, 0, risk_pct
        
        # Position size calculation: Risk Amount / (Stop Distance * Leverage)
        # This ensures we only lose `risk_amount` if SL is hit
        position_size = (risk_amount * leverage) / risk_per_unit
        
        # Convert to contract size (divide by entry price)
        position_size_contracts = position_size / entry_price
        
        notional_value = position_size_contracts * entry_price
        
        # Check minimum sizes
        min_size = 0.001  # Generic minimum
        if position_size_contracts < min_size:
            log_warning(f"Position size {position_size_contracts:.6f} below minimum {min_size}")
            return 0, leverage, 0, 0, risk_pct
        
        return (
            round(position_size_contracts, 6),
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
        Generate Nansen SMF Strategy v4.0 trading signal.
        """
        log_debug(f"Analyzing {symbol} for Nansen SMF v4.0 signal...")
        
        # Fetch OHLCV data
        df = exchange_client.get_ohlcv(symbol, config.signal_timeframe, limit=100)
        if df is None or len(df) < 50:
            log_warning(f"{symbol}: Insufficient OHLCV data")
            return None
        
        # Calculate indicators for multiple timeframes
        indicators = calculate_all_indicators(df)
        
        # MTF Trend checks
        df_4h = exchange_client.get_ohlcv(symbol, "4h", limit=50)
        df_15m = exchange_client.get_ohlcv(symbol, "15m", limit=50)
        
        mtf_alignment = {
            '4h': 'unknown',
            '1h': get_trend_direction(indicators),
            '15m': 'unknown'
        }
        
        if df_4h is not None and len(df_4h) >= 20:
            mtf_alignment['4h'] = get_trend_direction(calculate_all_indicators(df_4h))
        if df_15m is not None and len(df_15m) >= 20:
            mtf_alignment['15m'] = get_trend_direction(calculate_all_indicators(df_15m))

        # Validate signal (Nansen + EMA + RSI)
        direction, signal_details = self.validate_signal(symbol, indicators)
        if signal_details:
            signal_details.mtf_alignment = mtf_alignment
        
        if direction is None:
            log_debug(f"{symbol}: No valid signal - Nansen={signal_details.nansen_type}, "
                      f"Trend={signal_details.trend_aligned}, RSI={signal_details.rsi_valid}")
            return None
        
        # Determine conviction based on confidence score
        if signal_details.confidence_score >= 0.7:
            conviction = "HIGH"
        else:
            conviction = "STANDARD"
        
        # Calculate exits
        entry_price = indicators['price']
        atr = indicators['atr']
        exits = self.calculate_exits(entry_price, direction, atr)
        
        # Calculate position size
        pos_size, leverage, notional, risk_amt, risk_pct = self.calculate_position_size(
            account_equity, entry_price, exits['stop_loss'], conviction
        )
        
        if pos_size <= 0:
            log_warning(f"{symbol}: Position size too small")
            return None
        
        # Get Nansen signal for logging
        nansen_signal = nansen_client.get_signal(symbol)
        
        signal = TradeSignal(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=exits['stop_loss'],
            take_profit=exits['take_profit'],
            trailing_stop=exits['trailing_stop'],
            position_size=pos_size,
            leverage=leverage,
            notional_value=notional,
            risk_amount=risk_amt,
            risk_pct=risk_pct,
            atr=atr,
            stop_distance_atr=exits['stop_distance'],
            signals=signal_details,
            conviction=conviction,
            indicators=indicators,
            nansen_signal=nansen_signal,
            timestamp=datetime.now(),
            account_balance=account_equity
        )
        
        log_signal(
            symbol=symbol,
            signal_type=f"SMF_v4_{direction.value.upper()}",
            strength=signal_details.confidence_score,
            details=f"Conviction: {conviction} | Nansen: {signal_details.nansen_type} | "
                    f"Risk: {risk_pct*100:.1f}% | Lev: {leverage}x"
        )
        
        return signal


# Backward compatibility alias
ASMMv32ProStrategy = NansenSMFStrategy

# Global instance
trading_strategy = NansenSMFStrategy()
