"""
Structured logging module for Nansen Perp Trading Bot.
Provides file and console logging with trade-specific formatters.
"""

import logging
import os
from datetime import datetime
from typing import Optional
from pathlib import Path


# Create logs directory
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


class TradeFormatter(logging.Formatter):
    """Custom formatter for trade-related logs."""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'
    }
    
    def format(self, record):
        # Add color for console output
        if hasattr(record, 'use_color') and record.use_color:
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)


def setup_logger(name: str = "nansen_bot", log_level: int = logging.INFO) -> logging.Logger:
    """
    Set up and return a configured logger.
    
    Args:
        name: Logger name
        log_level: Logging level
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    logger.setLevel(log_level)
    
    # File handler - all logs
    log_file = LOGS_DIR / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler - info and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = TradeFormatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    
    # Trade-specific file handler
    trade_file = LOGS_DIR / f"trades_{datetime.now().strftime('%Y%m%d')}.log"
    trade_handler = logging.FileHandler(trade_file, encoding='utf-8')
    trade_handler.setLevel(logging.INFO)
    trade_handler.addFilter(lambda record: hasattr(record, 'trade'))
    trade_formatter = logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    trade_handler.setFormatter(trade_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.addHandler(trade_handler)
    
    return logger


# Global logger instance
logger = setup_logger()


def log_trade(
    action: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    pnl: Optional[float] = None
):
    """Log trade execution with structured format."""
    trade_info = {
        'action': action,
        'symbol': symbol,
        'side': side,
        'qty': quantity,
        'price': price
    }
    
    if stop_loss:
        trade_info['sl'] = stop_loss
    if take_profit:
        trade_info['tp'] = take_profit
    if pnl is not None:
        trade_info['pnl'] = pnl
    
    message = " | ".join(f"{k}={v}" for k, v in trade_info.items())
    
    record = logger.makeRecord(
        logger.name, logging.INFO, "", 0, message, None, None
    )
    record.trade = True
    logger.handle(record)


def log_signal(
    symbol: str,
    signal_type: str,
    strength: float,
    details: str = ""
):
    """Log signal detection."""
    logger.info(f"SIGNAL | {symbol} | {signal_type} | strength={strength:.2f} | {details}")


def log_error(message: str, exc_info: bool = True):
    """Log error with optional traceback."""
    logger.error(message, exc_info=exc_info)


def log_info(message: str):
    """Log info message."""
    logger.info(message)


def log_debug(message: str):
    """Log debug message."""
    logger.debug(message)


def log_warning(message: str):
    """Log warning message."""
    logger.warning(message)
