"""
Configuration module for Nansen Smart Money Flow Strategy v4.0.
Focused on Nansen Accumulation/Distribution signals with strict risk management.
"""

import os
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List

load_dotenv()


@dataclass
class Config:
    """Nansen Smart Money Flow Strategy v4.0 configuration."""
    
    # Strategy Identity
    strategy_name: str = "Nansen SMF Strategy"
    strategy_version: str = "4.0"
    target_win_rate: int = 55  # 50-55% target
    
    # API Keys
    bybit_api_key: str = os.getenv("BYBIT_API_KEY", "")
    bybit_api_secret: str = os.getenv("BYBIT_API_SECRET", "")
    nansen_api_key: str = os.getenv("NANSEN_API_KEY", "")
    
    # Trading Pairs (3 high-cap pairs for diversification)
    trading_pairs: List[str] = None
    
    # Capital
    starting_capital: float = 500.0    # $500 starting capital
    
    # ==========================================================================
    # RISK MANAGEMENT (v4.0 - Strict Rules)
    # ==========================================================================
    base_risk_pct: float = 0.02        # 2% per-trade risk (standard)
    high_conviction_risk_pct: float = 0.03  # 3% per-trade risk (high conviction)
    max_drawdown_pct: float = 0.15     # 15% max drawdown - auto-pause
    max_consecutive_losses: int = 3    # Pause after 3 consecutive losses
    daily_loss_limit_pct: float = 0.10 # 10% daily loss limit
    
    # ==========================================================================
    # LEVERAGE
    # ==========================================================================
    base_leverage: int = 4             # Default 4x leverage
    high_conviction_leverage: int = 4  # Keep at 4x for safety
    
    # ==========================================================================
    # TIMEFRAMES
    # ==========================================================================
    signal_timeframe: str = "1h"       # 1H for primary signal generation
    momentum_timeframe: str = "15m"    # 15m for entry timing (optional)
    
    # ==========================================================================
    # INDICATOR PARAMETERS
    # ==========================================================================
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_period: int = 14
    atr_period: int = 14
    
    # ==========================================================================
    # SIGNAL REQUIREMENTS (v4.0 - Nansen Dominant)
    # ==========================================================================
    nansen_signal_weight: int = 2      # Nansen signal has highest priority (Weight=2)
    nansen_mandatory: bool = True      # Nansen signal MUST be present for entry
    
    # RSI Thresholds (v4.0 - Avoid Overextension)
    rsi_long_max: int = 70             # Long only if RSI < 70
    rsi_short_min: int = 30            # Short only if RSI > 30
    
    # ==========================================================================
    # EXIT PARAMETERS (v4.0 - ATR-Based)
    # ==========================================================================
    stop_loss_atr_mult: float = 1.5    # Stop Loss = 1.5x ATR
    take_profit_atr_mult: float = 2.5  # Take Profit = 2.5x ATR
    trailing_stop_atr_mult: float = 1.0  # Trailing stop = 1x ATR (for 30% position)
    trailing_position_pct: float = 0.30  # Apply trailing to 30% of position
    
    # ==========================================================================
    # EXECUTION LIMITS
    # ==========================================================================
    max_concurrent_trades: int = 3     # Max 3 trades (one per pair)
    max_trades_per_day: int = 5        # Max 5 trades per day
    min_trade_interval_hours: float = 1.0  # Minimum 1 hour between trades
    
    # ==========================================================================
    # BOT MODE
    # ==========================================================================
    dry_run: bool = False              # LIVE mode (placing orders)
    use_testnet: bool = True           # USE BYBIT TESTNET
    loop_interval_seconds: int = 60    # 60 seconds loop (1 minute)
    
    # Dashboard
    dashboard_port: int = 8000
    
    def __post_init__(self):
        """Parse environment variables."""
        if self.trading_pairs is None:
            pairs_str = os.getenv("TRADING_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT")
            self.trading_pairs = [p.strip() for p in pairs_str.split(",")]
        
        # Override from env
        self.dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        self.use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
        self.base_risk_pct = float(os.getenv("BASE_RISK_PCT", "2")) / 100
        self.high_conviction_risk_pct = float(os.getenv("HIGH_CONVICTION_RISK_PCT", "3")) / 100
        self.max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PCT", "15")) / 100
        self.daily_loss_limit_pct = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "10")) / 100
        self.base_leverage = int(os.getenv("BASE_LEVERAGE", "4"))
        self.high_conviction_leverage = int(os.getenv("HIGH_CONVICTION_LEVERAGE", "4"))
        self.starting_capital = float(os.getenv("STARTING_CAPITAL", "100"))
        self.max_trades_per_day = int(os.getenv("MAX_TRADES_PER_DAY", "5"))
    
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
