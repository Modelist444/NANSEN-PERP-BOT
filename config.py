"""
Configuration module for ASMM v3.3.1 Pro - High Win Rate Bybit Strategy.
Optimized for 60%+ win rate with BTC + ETH trading.
"""

import os
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List

load_dotenv()


@dataclass
class Config:
    """ASMM v3.2 Pro configuration."""
    
    # Strategy Identity
    strategy_name: str = "ASMM v3.3.1 Pro"
    strategy_version: str = "3.3.1"
    target_win_rate: int = 60  # 60%+ target
    
    # API Keys
    bybit_api_key: str = os.getenv("BYBIT_API_KEY", "")
    bybit_api_secret: str = os.getenv("BYBIT_API_SECRET", "")
    nansen_api_key: str = os.getenv("NANSEN_API_KEY", "")
    
    # Trading Pairs (v3.2 Pro: BTC + ETH only)
    trading_pairs: List[str] = None
    
    # Capital
    starting_capital: float = 100.0    # $100 starting capital
    
    # Risk Management (v3.3 - Conservative with Nansen Mandatory)
    base_risk_pct: float = 0.02        # 2% standard risk (Tier 2)
    high_conviction_risk_pct: float = 0.03  # 3% high conviction (Tier 1)
    max_drawdown_pct: float = 0.15     # 15% hard stop
    max_consecutive_losses: int = 3    # Pause after 3 losses
    daily_loss_limit_pct: float = 0.06 # 6% daily limit
    min_risk_reward: float = 0.1       # Lowered for fast Scalp Demo
    
    # Leverage (v3.3 - 3x to 6x range)
    base_leverage: int = 3             # 3x for standard (Tier 2)
    high_conviction_leverage: int = 6  # 6x for strong signals (Tier 1)
    
    # Timeframes
    signal_timeframe: str = "4h"       # 4H candle close execution
    momentum_timeframe: str = "1h"     # 1H for MACD confirmation
    
    # Indicator Parameters
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_period: int = 14
    atr_period: int = 14
    
    # Signal Requirements (v3.3 - Nansen is MANDATORY)
    min_signals_required: int = 3      # Need 3/5 for entry
    nansen_mandatory: bool = True      # Nansen signal MUST be one of the 3+
    adx_threshold: float = 25.0        # Minimum ADX for trending
    
    # RSI Thresholds
    rsi_long_min: int = 50             # RSI 50-70 for LONG
    rsi_long_max: int = 70
    rsi_short_min: int = 30            # RSI 30-50 for SHORT
    rsi_short_max: int = 50
    
    # Funding/Positioning Thresholds
    funding_long_max: float = 0.0005   # <0.05% for LONG
    funding_short_min: float = 0.0005  # >0.05% for SHORT (crowded)
    ls_ratio_long_max: float = 1.2     # Long/Short < 1.2 for LONG
    ls_ratio_short_min: float = 0.8    # Long/Short > 0.8 for SHORT
    
    # Exit Parameters (v3.3 - Fixed Percentage Based)
    stop_loss_pct: float = 0.02        # 2% fixed stop loss (Tier 2)
    stop_loss_pct_high: float = 0.03   # 3% fixed stop loss (Tier 1)
    tp1_pct: float = 0.005             # TP1 = 0.5% (Very fast for demo)
    tp2_pct: float = 0.010             # TP2 = 1.0%
    tp1_close_pct: float = 0.60        # Close 60% at TP1
    tp2_close_pct: float = 0.40        # Close 40% at TP2
    
    # Signal Tracking (v3.3 - Track before live trading)
    signal_tracking_days: int = 30     # Track Nansen signals for 30 days
    
    # Execution
    max_concurrent_trades: int = 5     # Max 5 trades
    min_trade_interval_hours: float = 0.005 # ~18 seconds delay
    
    # Bot Mode
    dry_run: bool = False               # LIVE mode (placing orders)
    use_testnet: bool = True            # USE BYBIT TESTNET
    loop_interval_seconds: int = 12    # 12 seconds loop (Slower, easier to watch)
    
    # Dashboard
    dashboard_port: int = 8000
    
    def __post_init__(self):
        """Parse environment variables."""
        if self.trading_pairs is None:
            pairs_str = os.getenv("TRADING_PAIRS", "BTCUSDT,ETHUSDT")
            self.trading_pairs = [p.strip() for p in pairs_str.split(",")]
        
        # Override from env
        self.dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        self.use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
        self.base_risk_pct = float(os.getenv("BASE_RISK_PCT", "2")) / 100
        self.high_conviction_risk_pct = float(os.getenv("HIGH_CONVICTION_RISK_PCT", "3")) / 100
        self.max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PCT", "15")) / 100
        self.daily_loss_limit_pct = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "6")) / 100
        self.base_leverage = int(os.getenv("BASE_LEVERAGE", "3"))
        self.high_conviction_leverage = int(os.getenv("HIGH_CONVICTION_LEVERAGE", "6"))
        self.starting_capital = float(os.getenv("STARTING_CAPITAL", "100"))
    
    @property
    def all_pairs(self) -> List[str]:
        """Get all trading pairs."""
        return self.trading_pairs
    
    @property
    def timeframe(self) -> str:
        """Alias for signal_timeframe for backward compatibility."""
        return self.signal_timeframe
    
    @property
    def execution_timeframe(self) -> str:
        """Alias for signal_timeframe for backward compatibility."""
        return self.signal_timeframe
    
    @property
    def max_leverage(self) -> int:
        """Alias for base_leverage for backward compatibility."""
        return self.base_leverage
    
    @property
    def margin_mode(self) -> str:
        """Default margin mode."""
        return "isolated"
    
    @property
    def risk_per_trade(self) -> float:
        """Alias for base_risk_pct for backward compatibility."""
        return self.base_risk_pct
    
    def get_allocation(self, symbol: str) -> float:
        """Equal allocation per symbol."""
        if symbol in self.trading_pairs:
            return 1.0 / len(self.trading_pairs)
        return 0.0


# Global config instance
config = Config()
