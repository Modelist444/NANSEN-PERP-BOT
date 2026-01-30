"""
Risk management module for Nansen SMF Strategy v4.0.
Implements strict risk rules, circuit breakers, and max trades per day.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from config import config
from logger import log_info, log_warning, log_debug, log_error


@dataclass
class TradeRecord:
    """Record of a trade."""
    symbol: str
    timestamp: datetime
    direction: str
    entry_price: float
    position_size: float
    conviction: str
    stop_loss: float
    take_profit: float


class RiskManager:
    """
    Nansen SMF Strategy v4.0 Risk Manager.
    
    RISK RULES:
    - Per-trade risk: 2-3% of account
    - Max drawdown: 15% (auto-pause)
    - Max consecutive losses: 3 (pause)
    - Daily loss limit: 10%
    - Max trades per day: 5
    - Max concurrent trades: 3 (one per pair for diversification)
    """
    
    def __init__(self):
        # Trade tracking
        self._last_trade: Dict[str, datetime] = {}
        self._active_positions: Dict[str, TradeRecord] = {}
        self._trades_today: int = 0
        
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
        
        # Auto-adjust peak capital on first run if no trades recorded yet
        # This prevents false drawdown halt on restart
        if self.wins == 0 and self.losses == 0 and account_equity < self._peak_capital:
            log_info(f"First run detected. Adjusting peak capital from ${self._peak_capital:.2f} to ${account_equity:.2f}")
            self._peak_capital = account_equity
        
        # 1. Max drawdown: 15%
        if self._peak_capital > 0:
            drawdown_pct = ((self._peak_capital - account_equity) / self._peak_capital)
            log_debug(f"Drawdown check: {drawdown_pct*100:.1f}% (Current: ${account_equity:.2f} | Peak: ${self._peak_capital:.2f})")
            
            if drawdown_pct >= config.max_drawdown_pct:
                self.trading_halted = True
                self.halt_reason = f"Max drawdown: {drawdown_pct*100:.1f}%"
                log_warning(f"CIRCUIT BREAKER: {self.halt_reason}")
                return False, self.halt_reason
        
        # 2. Consecutive losses: 3
        if self.consecutive_losses >= config.max_consecutive_losses:
            self.trading_halted = True
            self.halt_reason = f"{self.consecutive_losses} consecutive losses - Review strategy"
            log_warning(f"CIRCUIT BREAKER: {self.halt_reason}")
            return False, self.halt_reason
        
        # 3. Daily loss limit: 10%
        if account_equity > 0:
            daily_loss_pct = (self._daily_pl / account_equity)
            if daily_loss_pct <= -config.daily_loss_limit_pct:
                return False, f"Daily loss limit: {daily_loss_pct*100:.1f}%"
        
        # 4. Max trades per day
        if self._trades_today >= config.max_trades_per_day:
            return False, f"Max trades per day ({config.max_trades_per_day}) reached"
        
        # 5. Check if halted
        if self.trading_halted:
            return False, f"Trading halted: {self.halt_reason}"
        
        return True, "OK"
    
    def can_trade(self, symbol: str) -> Tuple[bool, str]:
        """Check if we can trade this symbol."""
        if self.trading_halted:
            return False, f"Trading halted: {self.halt_reason}"

        # Check cooldown
        if symbol in self._last_trade:
            last_time = self._last_trade[symbol]
            cooldown = timedelta(hours=config.min_trade_interval_hours)
            if datetime.now() - last_time < cooldown:
                remaining = (last_time + cooldown) - datetime.now()
                return False, f"Trade cooldown: {remaining.seconds // 60}m remaining"
        
        # Check existing position (one per pair for diversification)
        if symbol in self._active_positions:
            return False, "Already has active position for this pair"
        
        # Check max concurrent trades
        if len(self._active_positions) >= config.max_concurrent_trades:
            return False, f"Max concurrent trades ({config.max_concurrent_trades})"
        
        # Check max trades per day
        if self._trades_today >= config.max_trades_per_day:
            return False, f"Max trades per day ({config.max_trades_per_day})"
        
        return True, "OK"
    
    def record_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        position_size: float,
        conviction: str,
        stop_loss: float,
        take_profit: float
    ):
        """Record a new trade."""
        now = datetime.now()
        self._last_trade[symbol] = now
        self._trades_today += 1
        
        self._active_positions[symbol] = TradeRecord(
            symbol=symbol,
            timestamp=now,
            direction=direction,
            entry_price=entry_price,
            position_size=position_size,
            conviction=conviction,
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        log_info(f"Recorded {conviction} {direction.upper()} trade for {symbol}")
    
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
        """Reset daily stats at midnight."""
        now = datetime.now()
        if now.date() > self._last_stats_reset.date():
            log_info(f"Daily reset. Previous P/L: ${self._daily_pl:.2f}, Trades: {self._trades_today}")
            self._daily_pl = 0.0
            self._trades_today = 0
            self._last_stats_reset = now
            
            # Reset daily halt triggers on new day
            if self.trading_halted and "daily" in self.halt_reason.lower():
                self.trading_halted = False
                self.halt_reason = ""
                log_info("Daily halt reset - new trading day")
    
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
            'active_positions': len(self._active_positions),
            'trades_today': self._trades_today,
            'max_trades_per_day': config.max_trades_per_day
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
        
        # Check risk-reward ratio (should be >= 1.67 for our 1.5x SL / 2.5x TP)
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        rr = reward / risk if risk > 0 else 0
        
        # ATR-based targets should give us ~1.67 R:R (2.5 / 1.5)
        min_rr = 1.0  # Minimum acceptable R:R
        if rr < min_rr:
            return False, f"R:R {rr:.2f} below minimum {min_rr}"
        
        return True, "OK"
    
    def reset_halt(self):
        """Manual reset of trading halt."""
        self.trading_halted = False
        self.halt_reason = ""
        self.consecutive_losses = 0
        log_info("Trading halt reset manually")


# Global instance
risk_manager = RiskManager()
