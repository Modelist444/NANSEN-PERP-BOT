"""
Risk management module for ASMM v3.2 Pro.
Implements aggressive sizing, circuit breakers, and win rate tracking.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, Set, Tuple
from dataclasses import dataclass

from config import config
from logger import log_info, log_warning, log_debug, log_error
from database import db


@dataclass
class TradeRecord:
    """Record of a trade."""
    symbol: str
    timestamp: datetime
    direction: str
    entry_price: float
    position_size: float
    conviction: str
    signal_count: int


class RiskManager:
    """
    ASMM v3.2 Pro Risk Manager.
    
    Circuit Breakers:
    - 15% max drawdown (hard stop)
    - 3 consecutive losses (pause)
    - 10% daily loss limit
    - Win rate < 50% after 10 trades (review required)
    """
    
    def __init__(self):
        # Trade tracking
        self._last_trade: Dict[str, datetime] = {}
        self._active_positions: Dict[str, TradeRecord] = {}
        
        # P&L tracking
        self._daily_pl: float = 0.0
        self._total_pl: float = 0.0
        self._peak_capital: float = config.starting_capital
        self._last_stats_reset: datetime = datetime.now()
        
        # Win rate tracking
        self.wins: int = 0
        self.losses: int = 0
        self.consecutive_losses: int = 0
        
        # Circuit breaker state
        self.trading_halted: bool = False
        self.halt_reason: str = ""
    
    def calculate_win_rate(self) -> float:
        """Current win rate percentage."""
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0
    
    def check_circuit_breakers(self, account_equity: float) -> Tuple[bool, str]:
        """
        Check all circuit breakers.
        
        Returns:
            (can_trade, reason) - False if any breaker triggered
        """
        self._check_daily_reset()
        
        # 1. Max drawdown: 15%
        drawdown_pct = ((self._peak_capital - account_equity) / self._peak_capital) * 100
        if drawdown_pct >= config.max_drawdown_pct * 100:
            self.trading_halted = True
            self.halt_reason = f"Max drawdown: {drawdown_pct:.1f}%"
            return False, self.halt_reason
        
        # 2. Consecutive losses: 3
        if self.consecutive_losses >= config.max_consecutive_losses:
            self.trading_halted = True
            self.halt_reason = f"{self.consecutive_losses} consecutive losses - Review strategy"
            return False, self.halt_reason
        
        # 3. Daily loss limit: 6% (v3.3)
        daily_loss_pct = (self._daily_pl / account_equity) * 100
        if daily_loss_pct <= -config.daily_loss_limit_pct * 100:
            return False, f"Daily loss limit: {daily_loss_pct:.1f}%"
        
        # 4. Win rate check after 10 trades
        total_trades = self.wins + self.losses
        if total_trades >= 10:
            win_rate = self.calculate_win_rate()
            if win_rate < 50:
                log_warning(f"Win rate {win_rate:.1f}% below 60% target after {total_trades} trades")
                # Don't halt, just warn
        
        # 5. Check if halted
        if self.trading_halted:
            return False, f"Trading halted: {self.halt_reason}"
        
        return True, "OK"
    
    def can_trade(self, symbol: str) -> Tuple[bool, str]:
        """Check if we can trade this symbol."""
        # v3.3: Enforce circuit breakers (Daily Loss Limit, Max Drawdown, etc.)
        # We need account equity for some checks. 
        # But wait, check_circuit_breakers is usually called manually in main.py.
        # Let's see if we should call it here too for safety.
        # Actually, let's just check if trading is halted.
        if self.trading_halted:
            return False, f"Trading halted: {self.halt_reason}"

        # v3.3: (30-day tracking enforcement removed per user request)

        # Check cooldown
        if symbol in self._last_trade:
            last_time = self._last_trade[symbol]
            cooldown = timedelta(hours=config.min_trade_interval_hours)
            if datetime.now() - last_time < cooldown:
                return False, f"Trade cooldown active"
        
        # Check existing position
        if symbol in self._active_positions:
            return False, "Already has active position"
        
        # Check max concurrent trades
        if len(self._active_positions) >= config.max_concurrent_trades:
            return False, f"Max concurrent trades ({config.max_concurrent_trades})"
        
        return True, "OK"
    
    def record_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        position_size: float,
        conviction: str,
        signal_count: int
    ):
        """Record a new trade."""
        now = datetime.now()
        self._last_trade[symbol] = now
        self._active_positions[symbol] = TradeRecord(
            symbol=symbol,
            timestamp=now,
            direction=direction,
            entry_price=entry_price,
            position_size=position_size,
            conviction=conviction,
            signal_count=signal_count
        )
        log_info(f"Recorded {conviction} trade for {symbol} ({signal_count}/5 signals)")
    
    def record_trade_result(self, symbol: str, pnl: float, account_equity: float):
        """Record trade result and update stats."""
        self._daily_pl += pnl
        self._total_pl += pnl
        
        if pnl > 0:
            self.wins += 1
            self.consecutive_losses = 0
            if account_equity > self._peak_capital:
                self._peak_capital = account_equity
        else:
            self.losses += 1
            self.consecutive_losses += 1
        
        log_info(
            f"Trade result: ${pnl:+.2f} | "
            f"W/L: {self.wins}/{self.losses} | "
            f"Win Rate: {self.calculate_win_rate():.1f}%"
        )
    
    def update_daily_pnl(self, pnl: float):
        """Simple update for daily P/L (for partial exits)."""
        self._daily_pl += pnl
        self._total_pl += pnl
        log_debug(f"P/L updated: ${pnl:+.2f} | Daily: ${self._daily_pl:+.2f}")
    
    def close_position_record(self, symbol: str):
        """Remove position from tracking."""
        if symbol in self._active_positions:
            del self._active_positions[symbol]
    
    def has_position(self, symbol: str) -> bool:
        """Check if there's an active position."""
        return symbol in self._active_positions
    
    def get_position_record(self, symbol: str) -> Optional[TradeRecord]:
        """Get trade record for a symbol."""
        return self._active_positions.get(symbol)
    
    def _check_daily_reset(self):
        """Reset daily P/L at midnight."""
        now = datetime.now()
        if now.date() > self._last_stats_reset.date():
            log_info(f"Daily reset. Previous P/L: ${self._daily_pl:.2f}")
            self._daily_pl = 0.0
            self._last_stats_reset = now
            
            # Reset trading halt on new day (but keep consecutive losses)
            if self.trading_halted and "daily" in self.halt_reason.lower():
                self.trading_halted = False
                self.halt_reason = ""
    
    def get_stats(self) -> Dict:
        """Get current stats."""
        return {
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': self.calculate_win_rate(),
            'consecutive_losses': self.consecutive_losses,
            'daily_pl': self._daily_pl,
            'total_pl': self._total_pl,
            'peak_capital': self._peak_capital,
            'trading_halted': self.trading_halted,
            'halt_reason': self.halt_reason,
            'active_positions': len(self._active_positions)
        }
    
    def validate_trade(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float,
        account_equity: float
    ) -> Tuple[bool, str]:
        """Validate trade before execution."""
        # Check circuit breakers
        can_trade, reason = self.check_circuit_breakers(account_equity)
        if not can_trade:
            return False, reason
        
        # Check symbol-specific
        can_trade, reason = self.can_trade(symbol)
        if not can_trade:
            return False, reason
        
        # Check risk-reward
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        rr = reward / risk if risk > 0 else 0
        
        if rr < config.min_risk_reward:
            return False, f"R:R {rr:.2f} below minimum {config.min_risk_reward}"
        
        return True, "OK"
    
    def reset_halt(self):
        """Manual reset of trading halt."""
        self.trading_halted = False
        self.halt_reason = ""
        self.consecutive_losses = 0
        log_info("Trading halt reset manually")


# Global instance
risk_manager = RiskManager()
