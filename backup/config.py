"""
Configuration module for Nansen Perp Trading Bot.
Loads settings from environment variables with sensible defaults.
"""

import os
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List

load_dotenv()


@dataclass
class Config:
    """Centralized bot configuration."""
    
    # API Keys
    bybit_api_key: str = os.getenv("BYBIT_API_KEY", "")
    bybit_api_secret: str = os.getenv("BYBIT_API_SECRET", "")
    nansen_api_key: str = os.getenv("NANSEN_API_KEY", "")
    
    # Trading Pairs
    high_cap_pairs: List[str] = None  # BTC, ETH
    mid_cap_pairs: List[str] = None   # SOL, AVAX, LINK, MATIC
    
    # Capital Allocation
    high_cap_allocation: float = 0.70  # 70% for BTC/ETH
    mid_cap_allocation: float = 0.30   # 30% for mid-caps
    
    # Risk Management
    risk_per_trade: float = 0.04       # 4% risk per trade
    max_concurrent_trades: int = 3
    max_daily_drawdown: float = 0.08   # 8% daily drawdown limit
    take_profit_multiplier: float = 3.0  # 3x risk-reward
    atr_period: int = 14               # ATR calculation period
    atr_stop_multiplier: float = 1.0   # Stop loss = entry ± (ATR × 1.0) - adjusted for 0.8%-1.2% range
    
    # Timeframes
    signal_timeframes: List[str] = None  # 15m, 1h
    execution_timeframe: str = "5m"      # 5m for entry/exit timing
    
    # Trade Frequency
    min_trade_interval_hours: int = 4  # Cooldown between trades per asset
    
    # Execution Settings
    max_leverage: int = 5
    margin_mode: str = "isolated"      # isolated or cross
    timeframe: str = "1h"              # Chart timeframe for analysis
    
    # Bot Mode
    dry_run: bool = True               # Simulation mode (no real trades)
    loop_interval_seconds: int = 300   # 5 minutes between cycles
    
    # Dashboard
    dashboard_port: int = 8000
    
    def __post_init__(self):
        """Parse list-type environment variables."""
        if self.high_cap_pairs is None:
            pairs_str = os.getenv("HIGH_CAP_PAIRS", "BTCUSDT,ETHUSDT")
            self.high_cap_pairs = [p.strip() for p in pairs_str.split(",")]
        
        if self.mid_cap_pairs is None:
            pairs_str = os.getenv("MID_CAP_PAIRS", "SOLUSDT,AVAXUSDT,LINKUSDT,MATICUSDT")
            self.mid_cap_pairs = [p.strip() for p in pairs_str.split(",")]
        
        # Override from env if set
        self.dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
        self.max_leverage = int(os.getenv("MAX_LEVERAGE", "5"))
        self.risk_per_trade = float(os.getenv("RISK_PER_TRADE", "4")) / 100
        self.max_daily_drawdown = float(os.getenv("MAX_DAILY_DRAWDOWN", "8")) / 100
        self.take_profit_multiplier = float(os.getenv("TAKE_PROFIT_MULTIPLIER", "3"))
        self.atr_period = int(os.getenv("ATR_PERIOD", "14"))
        self.atr_stop_multiplier = float(os.getenv("ATR_STOP_MULTIPLIER", "1.0"))
        self.min_trade_interval_hours = int(os.getenv("MIN_TRADE_INTERVAL_HOURS", "4"))
        self.execution_timeframe = os.getenv("TIMEFRAME", "5m")
        self.margin_mode = os.getenv("MARGIN_MODE", "isolated")
        self.dashboard_port = int(os.getenv("DASHBOARD_PORT", "8000"))
        
        if self.signal_timeframes is None:
            self.signal_timeframes = ["15m", "1h"]
    
    @property
    def all_pairs(self) -> List[str]:
        """Get all trading pairs."""
        return self.high_cap_pairs + self.mid_cap_pairs
    
    def get_allocation(self, symbol: str) -> float:
        """Get capital allocation percentage for a symbol."""
        if symbol in self.high_cap_pairs:
            return self.high_cap_allocation / len(self.high_cap_pairs)
        elif symbol in self.mid_cap_pairs:
            return self.mid_cap_allocation / len(self.mid_cap_pairs)
        return 0.0
    
    def is_high_cap(self, symbol: str) -> bool:
        """Check if symbol is a high-cap asset."""
        return symbol in self.high_cap_pairs


# Global config instance
config = Config()
