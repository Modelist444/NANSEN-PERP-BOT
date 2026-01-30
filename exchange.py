"""
Exchange integration module using ccxt for Bybit Futures.
Handles order execution, position management, and market data.
"""

import ccxt
import pandas as pd
import random
import numpy as np
import time
from typing import Optional, Dict, List, Any, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
from dataclasses import dataclass
from enum import Enum
import math

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
        
        # v3.3.1: Auto-Mock if keys are missing
        self.mock_mode = not self.api_key or not self.api_secret or config.dry_run
        
        # Initialize ccxt exchange
        if not self.mock_mode:
            self.exchange = ccxt.bybit({
                'apiKey': self.api_key,
                'secret': self.api_secret,
                'sandbox': config.use_testnet,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'linear',
                    'hedgeMode': False,
                    'adjustForTimeDifference': True,
                    'recvWindow': 30000
                }
            })
        else:
            self.exchange = None
            log_info("🔑 API Keys missing or Dry Run: ENTERING FULL SIMULATION MODE")
        
        self.initialized_symbols: Set[str] = set()
        self.leverage_set: Set[str] = set()
        self._mock_positions: List[Position] = []
        self._mock_balance = 10000.0

    def set_leverage(self, symbol: str, leverage: int):
        """Set leverage for a specific symbol (v3.3 tiered leverage)."""
        log_info(f"Skipping leverage set for {symbol} (handled manually / preconfigured)")
        return
    
    def _ensure_initialized(self, symbol: str):
        """Ensure margin mode is set correctly for a symbol."""
        if symbol in self.initialized_symbols:
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
            
            self.initialized_symbols.add(symbol)
            
        except ccxt.BaseError as e:
            log_warning(f"Error initializing {symbol}: {e}")
    
    def get_account_balance(self) -> float:
        """Get available USDT balance."""
        if self.mock_mode:
            return self._mock_balance
            
        try:
            balance = self.exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {})
            return float(usdt_balance.get('free', 0))
        except Exception as e:
            log_error(f"Error fetching balance: {e}")
            return self._mock_balance if self.mock_mode else 0.0
    
    def get_total_equity(self) -> float:
        """Get total account equity (balance + unrealized PnL)."""
        if self.mock_mode:
            unrealized = sum(p.unrealized_pnl for p in self._mock_positions)
            return self._mock_balance + unrealized
            
        try:
            balance = self.exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {})
            return float(usdt_balance.get('total', 0))
        except Exception as e:
            log_error(f"Error fetching equity: {e}")
            return self._mock_balance if self.mock_mode else 0.0
    
    def get_ohlcv(
        self, 
        symbol: str, 
        timeframe: str = None, 
        limit: int = 100
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data for a symbol (with Mock support)."""
        timeframe = timeframe or config.signal_timeframe or '4h'
        
        if self.mock_mode:
            # v3.3.1: Aggressive "Sine Wave" Volatility for Demo
            # Price oscillates +/- 4% to FORCE visible PnL swings
            # Period: ~90s (fast cycling)
            timestamp = time.time()
            cycle = math.sin(timestamp / 15) # 15s factor -> Faster cycle
            
            # Trend direction + random noise
            trend = cycle * 0.04 # +/- 4% swings
            jitter = random.uniform(-0.003, 0.003) # 0.3% noise
            
            base_price = (98000 if "BTC" in symbol else 3800) * (1 + trend + jitter)
            now = datetime.now()
            timestamps = [now - timedelta(hours=4*i) for i in range(limit)]
            timestamps.reverse()
            
            prices = []
            
            # Generate history ending at the drifted base_price
            if "BTC" in symbol:
                # Historical uptrend + noise
                for i in range(limit):
                    hist_drift = (i - limit + 1) * 0.005
                    p = base_price * (1 + hist_drift + random.uniform(-0.001, 0.001))
                    prices.append(p)
            else:
                curr = base_price / (1.01 ** limit) # Start lower
                for _ in range(limit):
                    curr *= (1 + random.uniform(-0.005, 0.006))
                    prices.append(curr)
            
            df = pd.DataFrame({
                'open': [p * (1 - random.uniform(0.001, 0.002)) for p in prices],
                'high': [p * (1 + random.uniform(0.002, 0.005)) for p in prices],
                'low': [p * (1 - random.uniform(0.003, 0.006)) for p in prices],
                'close': prices,
                'volume': [random.uniform(100, 1000) for _ in range(limit)],
                'timestamp': timestamps
            })
            df.set_index('timestamp', inplace=True)
            return df

        try:
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            
            df = pd.DataFrame(
                ohlcv, 
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
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
        if self.mock_mode:
            return random.uniform(-0.0001, 0.0001)
        try:
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            funding = self.exchange.fetch_funding_rate(ccxt_symbol)
            return float(funding['fundingRate'])
        except Exception as e:
            log_error(f"Error fetching funding for {symbol}: {e}")
            return None
    
    def get_long_short_ratio(self, symbol: str) -> Optional[float]:
        """Fetch long/short ratio (with Mock support)."""
        if self.mock_mode:
            # Force bullish ratio for BTC (low ratio means shorts are crowded or longs are not excessive)
            return 0.95 if "BTC" in symbol else 1.1
        
        if config.dry_run:
            return 1.0  # Neutral
            
        try:
            # Bybit provides this via their API
            # Using ccxt's fetch_funding_rate which includes positioning info
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            
            # Try to get from market info
            ticker = self.exchange.fetch_ticker(ccxt_symbol)
            
            # Bybit includes long/short info in some endpoints
            # Fallback to neutral if not available
            if 'info' in ticker and 'longShortRatio' in ticker['info']:
                return float(ticker['info']['longShortRatio'])
            
            # Default neutral ratio if not available
            return 1.0
            
        except ccxt.BaseError as e:
            log_debug(f"Could not fetch L/S ratio for {symbol}: {e}")
            return 1.0  # Default neutral
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current market price (with Mock support)."""
        if self.mock_mode:
            df = self.get_ohlcv(symbol, limit=1)
            return float(df['close'].iloc[-1]) if df is not None else None
            
        try:
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            self.exchange.load_markets()
            ticker = self.exchange.fetch_ticker(ccxt_symbol)
            return float(ticker.get('last', 0))
        except Exception as e:
            log_error(f"Error fetching price for {symbol}: {e}")
            return None
    
    def place_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        reduce_only: bool = False
    ) -> Optional[Order]:
        """Place a market order (Simulated in Mock Mode)."""
        if self.mock_mode:
            price = self.get_current_price(symbol)
            order_id = f"mock_order_{random.randint(1000, 9999)}"
            log_info(f"[SIMULATION] {side.value.upper()} {quantity} {symbol} at {price}")
            
            # Simple mock position management
            if not reduce_only:
                pos_side = PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT
                new_pos = Position(
                    symbol=symbol,
                    side=pos_side,
                    size=quantity,
                    entry_price=price,
                    unrealized_pnl=0.0,
                    leverage=config.base_leverage,
                    liquidation_price=price * 0.8,
                    margin_mode="isolated"
                )
                self._mock_positions.append(new_pos)
            else:
                # Remove position if mock exists
                self._mock_positions = [p for p in self._mock_positions if p.symbol != symbol]

            return Order(
                id=order_id,
                symbol=symbol,
                side=side,
                type="market",
                quantity=quantity,
                price=price,
                status="closed",
                timestamp=datetime.now()
            )
        
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
            # Bybit linear perpetuals use 'BTC/USDT'
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            
            # Plan B: Use simplified one-liner
            order = self.exchange.create_market_order(
                ccxt_symbol,
                side.value,
                quantity,
                params={'reduceOnly': reduce_only}
            )
            
            if order is None:
                log_error(f"Order failed for {symbol}: API returned None")
                return None
                
            # Safely parse order details with fallbacks
            order_id = str(order.get('id', 'unknown'))
            order_status = order.get('status', 'open')
            order_amount = order.get('amount')
            order_price = order.get('average') or order.get('price')
            fill_price = order.get("average") or order.get("price") or "MKT"
            
            log_info(f"✅ Market Order Filled: {side.value} {quantity} {symbol} @ {fill_price}")
            
            # Safely parse timestamp
            ts = order.get("timestamp")
            if ts is None:
                ts = time.time() * 1000
            order_timestamp = datetime.fromtimestamp(ts / 1000)
            
            result = Order(
                id=order_id,
                symbol=symbol,
                side=side,
                type="market",
                quantity=float(order_amount) if order_amount is not None else float(quantity),
                price=float(order_price) if order_price is not None else self.get_current_price(symbol),
                status=order_status,
                timestamp=order_timestamp
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
        """Place a stop-loss order (Mock-aware)."""
        if self.mock_mode:
            log_info(f"[SIMULATION] SL {side.value.upper()} {quantity} {symbol} @ {stop_price}")
            return Order(
                id="mock_sl_" + datetime.now().strftime("%Y%m%d%H%M%S"),
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
        """Place a take-profit order (Mock-aware)."""
        if self.mock_mode:
            log_info(f"[SIMULATION] TP {side.value.upper()} {quantity} {symbol} @ {tp_price}")
            return Order(
                id="mock_tp_" + datetime.now().strftime("%Y%m%d%H%M%S"),
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
    
    def set_sl_tp(self, symbol: str, stop_loss: float, take_profit: float):
        """Set stop-loss and take-profit using Bybit's trading stop (more reliable than separate orders)."""
        if self.mock_mode:
            log_info(f"[SIMULATION] SL/TP set for {symbol} | SL={stop_loss} | TP={take_profit}")
            return
        
        try:
            # Bybit linear perpetuals use 'BTC/USDT'
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            
            self.exchange.set_trading_stop(
                ccxt_symbol,
                stopLoss=stop_loss,
                takeProfit=take_profit,
                params={
                    "category": "linear",
                    "positionIdx": 0  # one-way mode
                }
            )
            log_info(f"SL/TP set for {symbol} | SL={stop_loss} | TP={take_profit}")
        except Exception as e:
            log_error(f"Failed to set SL/TP for {symbol}: {e}")
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions (with Mock support)."""
        if self.mock_mode:
            # Update unrealized PnL for mock positions
            for pos in self._mock_positions:
                curr_price = self.get_current_price(pos.symbol)
                direction = 1 if pos.is_long else -1
                pos.unrealized_pnl = (curr_price - pos.entry_price) * pos.size * direction
            return self._mock_positions
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
