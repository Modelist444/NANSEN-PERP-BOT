"""
Technical Indicators Module for ASMM v3.2 Pro.
Provides EMA, RSI, MACD, ADX, ATR calculations for signal generation.
"""

import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any

from config import config


def calculate_ema(df: pd.DataFrame, period: int, column: str = 'close') -> pd.Series:
    """
    Calculate Exponential Moving Average.
    
    Args:
        df: OHLCV DataFrame
        period: EMA period (e.g., 20, 50)
        column: Column to calculate EMA on
    
    Returns:
        EMA series
    """
    return df[column].ewm(span=period, adjust=False).mean()


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI).
    
    RSI = 100 - (100 / (1 + RS))
    where RS = Average Gain / Average Loss
    
    Args:
        df: OHLCV DataFrame
        period: RSI period (default 14)
    
    Returns:
        RSI series (0-100)
    """
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.inf)
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_macd(
    df: pd.DataFrame, 
    fast: int = 12, 
    slow: int = 26, 
    signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD (Moving Average Convergence Divergence).
    
    MACD Line = EMA(fast) - EMA(slow)
    Signal Line = EMA(MACD Line, signal)
    Histogram = MACD Line - Signal Line
    
    Args:
        df: OHLCV DataFrame
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line period (default 9)
    
    Returns:
        (macd_line, signal_line, histogram)
    """
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average Directional Index (ADX).
    
    ADX measures trend strength (not direction).
    ADX > 25 = Strong trend
    ADX < 20 = Weak/ranging market
    
    Args:
        df: OHLCV DataFrame
        period: ADX period (default 14)
    
    Returns:
        ADX series
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    
    # Smoothed averages
    atr = tr.rolling(window=period, min_periods=1).mean()
    plus_di = 100 * (plus_dm.rolling(window=period, min_periods=1).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period, min_periods=1).mean() / atr)
    
    # ADX
    di_diff = abs(plus_di - minus_di)
    di_sum = plus_di + minus_di
    dx = 100 * (di_diff / di_sum.replace(0, np.inf))
    adx = dx.rolling(window=period, min_periods=1).mean()
    
    return adx


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).
    
    ATR = Moving Average of True Range
    Used for position sizing and stop loss calculation.
    
    Args:
        df: OHLCV DataFrame
        period: ATR period (default 14)
    
    Returns:
        ATR series
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=1).mean()
    
    return atr


def calculate_all_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate all indicators needed for ASMM v3.2 Pro.
    
    Args:
        df: OHLCV DataFrame with at least 100 candles
    
    Returns:
        Dictionary with all indicator values for latest candle
    """
    # EMAs
    ema_20 = calculate_ema(df, config.ema_fast)
    ema_50 = calculate_ema(df, config.ema_slow)
    
    # RSI
    rsi = calculate_rsi(df, config.rsi_period)
    
    # MACD
    macd_line, macd_signal, macd_hist = calculate_macd(
        df, config.macd_fast, config.macd_slow, config.macd_signal
    )
    
    # ADX
    adx = calculate_adx(df, config.adx_period)
    
    # ATR
    atr = calculate_atr(df, config.atr_period)
    
    # Get current and previous values
    return {
        'price': float(df['close'].iloc[-1]),
        'ema_20': float(ema_20.iloc[-1]),
        'ema_50': float(ema_50.iloc[-1]),
        'ema_20_prev': float(ema_20.iloc[-2]),
        'ema_50_prev': float(ema_50.iloc[-2]),
        'rsi': float(rsi.iloc[-1]),
        'macd': float(macd_line.iloc[-1]),
        'macd_signal': float(macd_signal.iloc[-1]),
        'macd_hist': float(macd_hist.iloc[-1]),
        'adx': float(adx.iloc[-1]),
        'atr': float(atr.iloc[-1]),
    }


def is_ema_bullish(indicators: Dict) -> bool:
    """Check if EMAs show bullish structure."""
    return (
        indicators['price'] > indicators['ema_20'] and
        indicators['price'] > indicators['ema_50'] and
        indicators['ema_20'] > indicators['ema_50'] and
        indicators['ema_20'] > indicators['ema_20_prev'] and
        indicators['ema_50'] > indicators['ema_50_prev']
    )


def is_ema_bearish(indicators: Dict) -> bool:
    """Check if EMAs show bearish structure."""
    return (
        indicators['price'] < indicators['ema_20'] and
        indicators['price'] < indicators['ema_50'] and
        indicators['ema_20'] < indicators['ema_50'] and
        indicators['ema_20'] < indicators['ema_20_prev'] and
        indicators['ema_50'] < indicators['ema_50_prev']
    )


def is_rsi_bullish(rsi: float) -> bool:
    """Check if RSI is in bullish zone (50-70)."""
    return config.rsi_long_min <= rsi <= config.rsi_long_max


def is_rsi_bearish(rsi: float) -> bool:
    """Check if RSI is in bearish zone (30-50)."""
    return config.rsi_short_min <= rsi <= config.rsi_short_max


def is_macd_bullish(macd: float, macd_signal: float) -> bool:
    """Check if MACD is bullish (above signal and positive)."""
    return macd > macd_signal and macd > 0


def is_macd_bearish(macd: float, macd_signal: float) -> bool:
    """Check if MACD is bearish (below signal and negative)."""
    return macd < macd_signal and macd < 0


def is_trending(adx: float) -> bool:
    """Check if market is trending (ADX > 25)."""
    return adx > config.adx_threshold
