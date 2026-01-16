"""
Exchange integration module using ccxt for Bybit Futures.
Handles order execution, position management, and market data.
"""

import ccxt
import pandas as pd
from typing import Optional, Dict, List, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from config import config
from logger import log_info, log_error, log_trade, log_debug, log_warning


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Position:
    """Represents an open position."""
    symbol: str
    side: PositionSide
    size: float
    entry_price: float
    unrealized_pnl: float
    leverage: int
    liquidation_price: float
    margin_mode: str
    
    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG


@dataclass
class Order:
    """Represents an order."""
    id: str
    symbol: str
    side: OrderSide
    type: str
    quantity: float
    price: Optional[float]
    status: str
    timestamp: datetime


class BybitFuturesClient:
    """Client for Bybit USDT-M Futures."""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key or config.bybit_api_key
        self.api_secret = api_secret or config.bybit_api_secret
        
        # Initialize ccxt exchange
        self.exchange = ccxt.bybit({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'sandbox': True,  # Use testnet by default
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # USDT Linear Perpetuals
                'adjustForTimeDifference': True
            }
        })
        
        self._initialized = False
    
    def _ensure_initialized(self, symbol: str):
        """Ensure margin mode and leverage are set correctly."""
        if self._initialized:
            return
        
        try:
            self.exchange.load_markets()
            
            # Set isolated margin mode
            try:
                if config.margin_mode == "isolated":
                    self.exchange.set_margin_mode('isolated', symbol)
                else:
                    self.exchange.set_margin_mode('cross', symbol)
            except ccxt.BaseError as e:
                # Often occurs if already set, which is fine
                log_debug(f"Note: Margin mode for {symbol} already set or changed: {e}")
            
            # Set leverage
            self.exchange.set_leverage(config.max_leverage, symbol)
            
            log_debug(f"Initialized {symbol}: {config.margin_mode} margin, {config.max_leverage}x leverage")
            self._initialized = True
            
        except ccxt.BaseError as e:
            log_warning(f"Error initializing {symbol}: {e}")
    
    def get_account_balance(self) -> float:
        """Get available USDT balance."""
        if config.dry_run:
            log_debug("Dry run mode: Using mock balance $10,000")
            return 10000.0  # Mock balance for testing
            
        try:
            balance = self.exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {})
            return float(usdt_balance.get('free', 0))
        except ccxt.BaseError as e:
            log_error(f"Error fetching balance: {e}")
            return 0.0
    
    def get_total_equity(self) -> float:
        """Get total account equity (balance + unrealized PnL)."""
        if config.dry_run:
            log_debug("Dry run mode: Using mock equity $10,000")
            return 10000.0  # Mock equity for testing
            
        try:
            balance = self.exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {})
            return float(usdt_balance.get('total', 0))
        except ccxt.BaseError as e:
            log_error(f"Error fetching equity: {e}")
            return 0.0
    
    def get_ohlcv(
        self, 
        symbol: str, 
        timeframe: str = None, 
        limit: int = 100
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a symbol.
        
        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            timeframe: Candle timeframe (e.g., '1h', '4h')
            limit: Number of candles to fetch
        
        Returns:
            DataFrame with OHLCV data or None on error
        """
        timeframe = timeframe or config.execution_timeframe
        
        try:
            # Bybit linear perpetuals use 'BTC/USDT'
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            
            df = pd.DataFrame(
                ohlcv, 
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df
            
        except ccxt.BaseError as e:
            log_error(f"Error fetching OHLCV for {symbol}: {e}")
            return None
    
    def get_open_interest(self, symbol: str) -> Optional[float]:
        """Fetch open interest for a symbol."""
        try:
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            oi_data = self.exchange.fetch_open_interest(ccxt_symbol)
            return float(oi_data['openInterestAmount'])
        except ccxt.BaseError as e:
            log_error(f"Error fetching OI for {symbol}: {e}")
            return None
            
    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """Fetch current funding rate."""
        try:
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            funding = self.exchange.fetch_funding_rate(ccxt_symbol)
            return float(funding['fundingRate'])
        except ccxt.BaseError as e:
            log_error(f"Error fetching funding for {symbol}: {e}")
            return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current market price."""
        try:
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            ticker = self.exchange.fetch_ticker(ccxt_symbol)
            return float(ticker.get('last', 0))
        except ccxt.BaseError as e:
            log_error(f"Error fetching price for {symbol}: {e}")
            return None
    
    def place_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        reduce_only: bool = False
    ) -> Optional[Order]:
        """
        Place a market order.
        
        Args:
            symbol: Trading pair
            side: Buy or sell
            quantity: Order quantity
            reduce_only: If True, only reduces position
        
        Returns:
            Order object or None on error
        """
        if config.dry_run:
            log_info(f"[DRY RUN] Market {side.value} {quantity} {symbol}")
            return Order(
                id="dry_run_" + datetime.now().strftime("%Y%m%d%H%M%S"),
                symbol=symbol,
                side=side,
                type="market",
                quantity=quantity,
                price=self.get_current_price(symbol),
                status="filled",
                timestamp=datetime.now()
            )
        
        try:
            self._ensure_initialized(symbol)
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            
            params = {}
            if reduce_only:
                params['reduceOnly'] = True
            
            # Use ccxt's built-in precision methods
            self.exchange.load_markets()
            formatted_quantity = self.exchange.amount_to_precision(ccxt_symbol, quantity)
            
            order = self.exchange.create_market_order(
                ccxt_symbol,
                side.value,
                formatted_quantity,
                params=params
            )
            
            result = Order(
                id=str(order['id']),
                symbol=symbol,
                side=side,
                type="market",
                quantity=quantity,
                price=float(order.get('average', order.get('price', 0))),
                status=order['status'],
                timestamp=datetime.now()
            )
            
            log_trade(
                action="OPEN" if not reduce_only else "CLOSE",
                symbol=symbol,
                side=side.value,
                quantity=quantity,
                price=result.price
            )
            
            return result
            
        except ccxt.BaseError as e:
            log_error(f"Error placing market order for {symbol}: {e}")
            return None
    
    def place_stop_loss(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        stop_price: float
    ) -> Optional[Order]:
        """Place a stop-loss order."""
        if config.dry_run:
            log_info(f"[DRY RUN] Stop-loss {side.value} {quantity} {symbol} @ {stop_price}")
            return Order(
                id="dry_run_sl_" + datetime.now().strftime("%Y%m%d%H%M%S"),
                symbol=symbol,
                side=side,
                type="stop_market",
                quantity=quantity,
                price=stop_price,
                status="open",
                timestamp=datetime.now()
            )
        
        try:
            self.exchange.load_markets()
            # Bybit linear perpetuals use 'BTC/USDT'
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            formatted_quantity = self.exchange.amount_to_precision(ccxt_symbol, quantity)
            formatted_stop_price = self.exchange.price_to_precision(ccxt_symbol, stop_price)
            
            order = self.exchange.create_order(
                ccxt_symbol,
                'stop_market',
                side.value,
                formatted_quantity,
                formatted_stop_price,
                params={
                    'stopPrice': formatted_stop_price,
                    'reduceOnly': True
                }
            )
            
            return Order(
                id=str(order['id']),
                symbol=symbol,
                side=side,
                type="stop_market",
                quantity=quantity,
                price=stop_price,
                status=order['status'],
                timestamp=datetime.now()
            )
            
        except ccxt.BaseError as e:
            log_error(f"Error placing stop-loss for {symbol}: {e}")
            return None
    
    def place_take_profit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        tp_price: float
    ) -> Optional[Order]:
        """Place a take-profit order."""
        if config.dry_run:
            log_info(f"[DRY RUN] Take-profit {side.value} {quantity} {symbol} @ {tp_price}")
            return Order(
                id="dry_run_tp_" + datetime.now().strftime("%Y%m%d%H%M%S"),
                symbol=symbol,
                side=side,
                type="take_profit_market",
                quantity=quantity,
                price=tp_price,
                status="open",
                timestamp=datetime.now()
            )
        
        try:
            self.exchange.load_markets()
            # Bybit linear perpetuals use 'BTC/USDT'
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            formatted_quantity = self.exchange.amount_to_precision(ccxt_symbol, quantity)
            formatted_tp_price = self.exchange.price_to_precision(ccxt_symbol, tp_price)
            
            order = self.exchange.create_order(
                ccxt_symbol,
                'take_profit_market',
                side.value,
                formatted_quantity,
                formatted_tp_price,
                params={
                    'stopPrice': formatted_tp_price,
                    'reduceOnly': True
                }
            )
            
            return Order(
                id=str(order['id']),
                symbol=symbol,
                side=side,
                type="take_profit_market",
                quantity=quantity,
                price=tp_price,
                status=order['status'],
                timestamp=datetime.now()
            )
            
        except ccxt.BaseError as e:
            log_error(f"Error placing take-profit for {symbol}: {e}")
            return None
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        try:
            positions = self.exchange.fetch_positions()
            
            result = []
            for pos in positions:
                contracts = float(pos.get('contracts', 0))
                if contracts == 0:
                    continue
                
                symbol = pos['symbol'].replace("/USDT:USDT", "USDT")
                side = PositionSide.LONG if pos['side'] == 'long' else PositionSide.SHORT
                
                result.append(Position(
                    symbol=symbol,
                    side=side,
                    size=abs(contracts),
                    entry_price=float(pos.get('entryPrice', 0)),
                    unrealized_pnl=float(pos.get('unrealizedPnl', 0)),
                    leverage=int(pos.get('leverage', config.max_leverage)),
                    liquidation_price=float(pos.get('liquidationPrice', 0)),
                    margin_mode=pos.get('marginMode', config.margin_mode)
                ))
            
            return result
            
        except ccxt.BaseError as e:
            log_error(f"Error fetching positions: {e}")
            return []
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a specific symbol."""
        positions = self.get_open_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return pos
        return None
    
    def close_position(self, symbol: str) -> Optional[Order]:
        """Close an open position."""
        position = self.get_position(symbol)
        
        if not position:
            log_warning(f"No open position for {symbol}")
            return None
        
        # Determine closing side (opposite of position side)
        close_side = OrderSide.SELL if position.is_long else OrderSide.BUY
        
        return self.place_market_order(
            symbol=symbol,
            side=close_side,
            quantity=position.size,
            reduce_only=True
        )
    
    def cancel_all_orders(self, symbol: str):
        """Cancel all open orders for a symbol."""
        if config.dry_run:
            log_info(f"[DRY RUN] Cancel all orders for {symbol}")
            return
        
        try:
            # Bybit linear perpetuals use 'BTC/USDT'
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            self.exchange.cancel_all_orders(ccxt_symbol)
            log_info(f"Cancelled all orders for {symbol}")
        except ccxt.BaseError as e:
            log_error(f"Error cancelling orders for {symbol}: {e}")


# Global client instance
exchange_client = BybitFuturesClient()
