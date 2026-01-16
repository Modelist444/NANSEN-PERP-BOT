"""
Risk management module for position sizing and trade frequency control.
Enforces 2% risk per trade and manages capital allocation.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass

from config import config
from logger import log_info, log_warning, log_debug


@dataclass
class TradeRecord:
    """Record of a trade for frequency limiting."""
    symbol: str
    timestamp: datetime
    direction: str
    entry_price: float
    position_size: float


class RiskManager:
    """Manages position sizing and trade frequency."""
    
    def __init__(self):
        # Track last trade time per symbol
        self._last_trade: Dict[str, datetime] = {}
        # Track active positions
        self._active_positions: Dict[str, TradeRecord] = {}
        # Track daily stats for drawdown check
        self._daily_pl: float = 0.0
        self._last_stats_reset: datetime = datetime.now()
    
    def calculate_position_size(
        self,
        account_equity: float,
        entry_price: float,
        stop_loss: float,
        symbol: str
    ) -> float:
        """
        Calculate position size based on risk parameters.
        
        Formula: position_size = risk_amount / stop_distance
        
        Args:
            account_equity: Total account equity
            entry_price: Planned entry price
            stop_loss: Stop loss price
            symbol: Trading pair for allocation check
        
        Returns:
            Position size in base currency units
        """
        # Calculate risk amount
        risk_amount = account_equity * config.risk_per_trade
        
        # Calculate stop distance
        stop_distance = abs(entry_price - stop_loss)
        
        if stop_distance == 0:
            log_warning(f"Invalid stop distance for {symbol}")
            return 0.0
        
        # Base position size from risk
        position_size = risk_amount / stop_distance
        
        # Apply allocation limits
        allocation = config.get_allocation(symbol)
        max_position_value = account_equity * allocation
        max_position_size = max_position_value / entry_price
        
        # Return the smaller of risk-based or allocation-based size
        final_size = min(position_size, max_position_size)
        
        log_debug(
            f"{symbol} position sizing: "
            f"risk_amt={risk_amount:.2f}, stop_dist={stop_distance:.4f}, "
            f"base_size={position_size:.6f}, max_size={max_position_size:.6f}, "
            f"final={final_size:.6f}"
        )
        
        return final_size
    
    def calculate_stop_loss(
        self,
        entry_price: float,
        atr: float,
        is_long: bool
    ) -> float:
        """
        Calculate stop loss price based on ATR, adhering to ASMM (0.8%-1.2%) range.
        
        Args:
            entry_price: Entry price
            atr: Current ATR value
            is_long: True for long position, False for short
        
        Returns:
            Stop loss price
        """
        # ASMM requires stop between 0.8% and 1.2%
        stop_distance = atr * config.atr_stop_multiplier
        stop_pct = (stop_distance / entry_price) * 100
        
        # Clamp stop distance within ASMM range (0.8% - 1.2%)
        min_stop = entry_price * 0.008
        max_stop = entry_price * 0.012
        
        clamped_stop = max(min_stop, min(max_stop, stop_distance))
        
        if is_long:
            return entry_price - clamped_stop
        else:
            return entry_price + clamped_stop
    
    def calculate_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        is_long: bool
    ) -> float:
        """
        Calculate take profit price (3x risk).
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            is_long: True for long position, False for short
        
        Returns:
            Take profit price
        """
        risk_distance = abs(entry_price - stop_loss)
        tp_distance = risk_distance * config.take_profit_multiplier
        
        if is_long:
            return entry_price + tp_distance
        else:
            return entry_price - tp_distance
    
    def can_trade(self, symbol: str) -> bool:
        """
        Check if trading is allowed for a symbol (frequency limit).
        
        Args:
            symbol: Trading pair
        
        Returns:
            True if trade is allowed, False if in cooldown
        """
        if symbol not in self._last_trade:
            return True
        
        last_trade_time = self._last_trade[symbol]
        cooldown = timedelta(hours=config.min_trade_interval_hours)
        time_since_trade = datetime.now() - last_trade_time
        
        if time_since_trade < cooldown:
            remaining = cooldown - time_since_trade
            log_debug(f"{symbol}: Trade cooldown active, {remaining} remaining")
            return False
        
        return True
    
    def record_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        position_size: float
    ):
        """
        Record a trade for frequency limiting.
        
        Args:
            symbol: Trading pair
            direction: 'long' or 'short'
            entry_price: Entry price
            position_size: Position size
        """
        now = datetime.now()
        self._last_trade[symbol] = now
        self._active_positions[symbol] = TradeRecord(
            symbol=symbol,
            timestamp=now,
            direction=direction,
            entry_price=entry_price,
            position_size=position_size
        )
        log_info(f"Recorded trade for {symbol} - next trade allowed after {config.min_trade_interval_hours}h")
    
    def close_position_record(self, symbol: str):
        """Remove position from tracking when closed."""
        if symbol in self._active_positions:
            del self._active_positions[symbol]
    
    def has_position(self, symbol: str) -> bool:
        """Check if there's an active position for a symbol."""
        return symbol in self._active_positions
    
    def get_position_record(self, symbol: str) -> Optional[TradeRecord]:
        """Get the trade record for an active position."""
        return self._active_positions.get(symbol)
    
    def get_allocation_for_asset(self, symbol: str) -> float:
        """Get the capital allocation percentage for an asset."""
        return config.get_allocation(symbol)
    
    def get_max_position_value(self, symbol: str, account_equity: float) -> float:
        """Get maximum position value allowed for a symbol."""
        allocation = config.get_allocation(symbol)
        return account_equity * allocation
    
    def _check_daily_reset(self):
        """Reset daily P/L at midnight."""
        now = datetime.now()
        if now.date() > self._last_stats_reset.date():
            log_info(f"Daily risk reset. Previous daily P/L: {self._daily_pl:.2f}")
            self._daily_pl = 0.0
            self._last_stats_reset = now

    def update_daily_pl(self, pl: float):
        """Update daily P/L for drawdown tracking."""
        self._check_daily_reset()
        self._daily_pl += pl

    def validate_trade(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float,
        account_equity: float
    ) -> tuple[bool, str]:
        """
        Validate a trade before execution based on ASMM rules.
        """
        # Check daily reset
        self._check_daily_reset()
        
        # Check daily drawdown (8%)
        max_drawdown = account_equity * config.max_daily_drawdown
        if self._daily_pl < -max_drawdown:
            return False, f"Daily drawdown limit reached: {self._daily_pl:.2f}"

        # Check concurrent trades (Max 3)
        if len(self._active_positions) >= config.max_concurrent_trades:
            return False, f"Max concurrent trades reached ({config.max_concurrent_trades})"

        # Check trade frequency
        if not self.can_trade(symbol):
            return False, "Trade cooldown active"
        
        # Check if already has position
        if self.has_position(symbol):
            return False, "Already has active position"
        
        # Check position size limits
        max_value = self.get_max_position_value(symbol, account_equity)
        position_value = position_size * entry_price
        
        if position_value > max_value * 1.05:  # 5% tolerance
            return False, f"Position value {position_value:.2f} exceeds limit {max_value:.2f}"
        
        # Check risk-reward
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        rr_ratio = reward / risk if risk > 0 else 0
        
        if rr_ratio < 1.4:  # 10% tolerance for 1.5R partial
            return False, f"Risk-reward {rr_ratio:.2f} below minimum 1.5R"
        
        # Check stop loss distance (ASMM: 0.8% - 1.2%)
        stop_pct = abs(entry_price - stop_loss) / entry_price * 100
        if stop_pct < 0.7 or stop_pct > 1.3:  # Slightly wider tolerance
            return False, f"Stop loss {stop_pct:.2f}% outside ASMM range (0.8-1.2%)"
        
        return True, "OK"


# Global risk manager instance
risk_manager = RiskManager()
