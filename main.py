"""
Nansen Perp Trading Bot - Main Entry Point
Orchestrates the trading loop with Nansen signals and exchange execution.
"""

import time
import signal
import sys
from datetime import datetime
from typing import Optional

from config import config
from logger import log_info, log_error, log_warning, log_trade
from nansen import nansen_client
from exchange import exchange_client, OrderSide
from strategy import trading_strategy, TradeDirection
from risk import risk_manager
from database import db, Trade, EquitySnapshot, Alert, NansenSignalLog
from server import run_server
import threading


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self):
        """Initialize the bot."""
        self.running = False
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Set up graceful shutdown handlers."""
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
    
    def _shutdown(self, signum, frame):
        """Handle shutdown signals."""
        log_info("\nShutdown signal received, stopping bot...")
        self.running = False
    
    def _record_equity_snapshot(self):
        """Record current equity for the equity curve."""
        try:
            equity = exchange_client.get_total_equity()
            positions = exchange_client.get_open_positions()
            
            unrealized_pnl = sum(p.unrealized_pnl for p in positions)
            
            # Get total realized PnL from database
            stats = db.get_trading_stats()
            realized_pnl = stats.get('total_pnl', 0)
            
            snapshot = EquitySnapshot(
                id=None,
                timestamp=datetime.now(),
                equity=equity,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl
            )
            db.insert_equity_snapshot(snapshot)
            
        except Exception as e:
            log_error(f"Error recording equity snapshot: {e}")

    def _log_all_nansen_signals(self):
        """Log Nansen signals for all tracked pairs (v3.3 30-day tracking)."""
        try:
            for symbol in config.trading_pairs:
                nansen_signal = nansen_client.get_signal(symbol)
                if not nansen_signal:
                    continue
                
                current_price = exchange_client.get_current_price(symbol)
                if not current_price:
                    continue
                
                log_entry = NansenSignalLog(
                    id=None,
                    timestamp=datetime.now(),
                    symbol=symbol,
                    signal_type=nansen_signal.signal_type.value,
                    strength=nansen_signal.strength,
                    smart_money_netflow=nansen_signal.smart_money_netflow,
                    exchange_netflow=nansen_signal.exchange_netflow,
                    price_at_signal=current_price,
                    would_have_traded=False 
                )
                db.insert_nansen_signal(log_entry)
                
        except Exception as e:
            log_error(f"Error logging Nansen signals: {e}")

    
    def _create_alert(
        self, 
        alert_type: str, 
        symbol: str, 
        message: str,
        data: dict = None
    ):
        """Create and store an alert."""
        alert = Alert(
            id=None,
            timestamp=datetime.now(),
            alert_type=alert_type,
            symbol=symbol,
            message=message,
            data=data,
            read=False
        )
        db.insert_alert(alert)
        log_info(f"ALERT [{alert_type}] {symbol}: {message}")
    
    def _check_open_positions(self):
        """Monitor open positions for ASMM exit rules (TP1, Trailing, Early Exit)."""
        db_trades = db.get_open_trades()
        
        for trade in db_trades:
            current_price = exchange_client.get_current_price(trade.symbol)
            if not current_price:
                continue
            
            # 1. Early Exit Check (Smart Money distribution or Extreme Funding)
            should_exit, reason = trading_strategy.check_early_exit(trade.symbol, trade)
            if should_exit:
                self._create_alert('early_exit', trade.symbol, f"Early exit: {reason}")
                exchange_client.cancel_all_orders(trade.symbol)
                exchange_client.place_market_order(trade.symbol, 
                                               OrderSide.SELL if trade.direction == 'long' else OrderSide.BUY,
                                               trade.position_size, reduce_only=True)
                pnl = db.close_trade(trade.id, current_price, 'closed_early')
                if pnl:
                    risk_manager.update_daily_pnl(pnl)
                risk_manager.close_position_record(trade.symbol)
                log_info(f"Early exit for {trade.symbol}: {reason} | PnL: {pnl:.2f}")
                continue

            # 2. Stop Loss Check
            is_sl_hit = (current_price <= trade.stop_loss if trade.direction == 'long' else current_price >= trade.stop_loss)
            if is_sl_hit:
                self._create_alert('stop_hit', trade.symbol, f"Stop loss hit at {current_price:.2f}")
                pnl = db.close_trade(trade.id, current_price, 'closed_sl')
                if pnl:
                    risk_manager.update_daily_pnl(pnl)
                risk_manager.close_position_record(trade.symbol)
                # If not dry run, Bybit should have closed it, but we ensure state is clean
                if not config.dry_run:
                    exchange_client.cancel_all_orders(trade.symbol)
                continue

            # 3. Partial Take Profit (TP1)
            if not trade.tp1_hit:
                is_tp1_hit = (current_price >= trade.take_profit if trade.direction == 'long' else current_price <= trade.take_profit)
                if is_tp1_hit:
                    close_pct = config.tp1_close_pct
                    log_info(f"{trade.symbol}: TP1 hit! Closing {close_pct*100:.0f}% and moving stop to breakeven.")
                    
                    tp_size = trade.position_size * (close_pct / (1.0 if not trade.tp1_hit else 0.4)) # This is tricky since trade.position_size might be full
                    # Actually, trade.position_size in DB is updated when closed.
                    # If it's the first time TP1 is hit:
                    close_size = trade.position_size * close_pct
                    remaining_size = trade.position_size - close_size
                    
                    # Close TP1 portion
                    exchange_client.place_market_order(trade.symbol, 
                                                   OrderSide.SELL if trade.direction == 'long' else OrderSide.BUY,
                                                   close_size, reduce_only=True)
                    
                    # Update Stop Loss to Breakeven (0.5% buffer)
                    new_stop = trade.entry_price * 1.005 if trade.direction == 'long' else trade.entry_price * 0.995
                    exchange_client.cancel_all_orders(trade.symbol) # Clear old TP/SL
                    
                    sl_side = OrderSide.SELL if trade.direction == 'long' else OrderSide.BUY
                    exchange_client.place_stop_loss(trade.symbol, sl_side, remaining_size, new_stop)
                    exchange_client.place_take_profit(trade.symbol, sl_side, remaining_size, trade.take_profit_2)

                    # Update Database
                    db.update_trade(trade.id, tp1_hit=1, stop_loss=new_stop, position_size=remaining_size)
                    
                    # Track Partial PnL
                    if trade.direction == 'long':
                        pnl_partial = (current_price - trade.entry_price) * close_size
                    else:
                        pnl_partial = (trade.entry_price - current_price) * close_size
                    risk_manager.update_daily_pnl(pnl_partial)
                    
                    self._create_alert('tp_partial', trade.symbol, f"TP1 hit! Closed {close_pct*100:.0f}% at {current_price:.2f}, stop to breakeven. PnL: {pnl_partial:.2f}")
            
            # 4. Final Take Profit (TP2 - 3R+)
            is_tp2_hit = (current_price >= trade.take_profit_2 if trade.direction == 'long' else current_price <= trade.take_profit_2)
            if is_tp2_hit:
                self._create_alert('tp_reached', trade.symbol, f"Final Take Profit reached at {current_price:.2f}")
                pnl = db.close_trade(trade.id, current_price, 'closed_tp')
                if pnl:
                    risk_manager.update_daily_pnl(pnl)
                risk_manager.close_position_record(trade.symbol)
                if not config.dry_run:
                    exchange_client.cancel_all_orders(trade.symbol)
    
    def _process_symbol(self, symbol: str, account_equity: float) -> bool:
        """
        Process a single symbol for trading signals.
        
        Returns:
            True if a trade was executed
        """
        # Check if we can trade this symbol
        if not risk_manager.can_trade(symbol):
            return False
        
        # Check if already has position
        if risk_manager.has_position(symbol):
            return False
        
        # Generate signal
        signal = trading_strategy.generate_signal(symbol, account_equity)
        
        if not signal:
            return False
        
        # Validate trade
        is_valid, reason = risk_manager.validate_trade(
            symbol=signal.symbol,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1, # Check against TP1 for RR
            position_size=signal.position_size,
            account_equity=account_equity
        )
        
        if not is_valid:
            log_warning(f"{symbol}: Trade validation failed - {reason}")
            return False
        
        # Execute trade
        # v3.3: Set tiered leverage before entry
        exchange_client.set_leverage(signal.symbol, signal.leverage)
        
        side = OrderSide.BUY if signal.direction == TradeDirection.LONG else OrderSide.SELL
        
        entry_order = exchange_client.place_market_order(
            symbol=signal.symbol,
            side=side,
            quantity=signal.position_size
        )
        
        if not entry_order:
            log_error(f"{symbol}: Failed to place entry order")
            return False
        
        # Place stop loss
        sl_side = OrderSide.SELL if signal.direction == TradeDirection.LONG else OrderSide.BUY
        exchange_client.place_stop_loss(
            symbol=signal.symbol,
            side=sl_side,
            quantity=signal.position_size,
            stop_price=signal.stop_loss
        )
        
        # Place take profits (TP1 and TP2)
        exchange_client.place_take_profit(
            symbol=signal.symbol,
            side=sl_side,
            quantity=signal.position_size * config.tp1_close_pct, 
            tp_price=signal.take_profit_1
        )
        exchange_client.place_take_profit(
            symbol=signal.symbol,
            side=sl_side,
            quantity=signal.position_size * config.tp2_close_pct,
            tp_price=signal.take_profit_2
        )
        
        # Record in database
        trade = Trade(
            id=None,
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_price=entry_order.price,
            exit_price=None,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            position_size=signal.position_size,
            entry_time=datetime.now(),
            exit_time=None,
            pnl=None,
            pnl_percent=None,
            status='open',
            tp1_hit=False,
            nansen_signal_strength=signal.nansen_signal.strength if signal.nansen_signal else 0.0
        )
        db.insert_trade(trade)
        
        # Record for risk manager
        risk_manager.record_trade(
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_price=entry_order.price,
            position_size=signal.position_size,
            conviction=signal.conviction,
            signal_count=signal.signal_count
        )
        
        # Create alert for strong signal
        if signal.nansen_signal and signal.nansen_signal.strength >= 0.7:
            self._create_alert(
                'strong_signal',
                symbol,
                f"Strong {signal.direction.value} signal (strength: {signal.nansen_signal.strength:.2f})",
                signal.to_dict()
            )
        
        log_trade(
            action="OPEN",
            symbol=signal.symbol,
            side=signal.direction.value,
            quantity=signal.position_size,
            price=entry_order.price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1
        )
        
        return True
    
    def run(self):
        """Main trading loop."""
        # Start dashboard in background
        dashboard_thread = threading.Thread(target=run_server, daemon=True)
        dashboard_thread.start()
        log_info(f"Dashboard available at: http://localhost:{config.dashboard_port}")
        log_info("=" * 50)
        log_info("Nansen Perp Trading Bot Starting")
        log_info(f"Mode: {'DRY RUN' if config.dry_run else 'LIVE TRADING'}")
        log_info(f"Pairs: {config.all_pairs}")
        log_info(f"Timeframe: {config.timeframe}")
        log_info(f"Risk per trade: {config.risk_per_trade * 100:.1f}%")
        log_info("=" * 50)
        
        if not config.dry_run:
            log_warning("⚠️  LIVE TRADING MODE - Real orders will be placed!")
            time.sleep(3)
        
        # Signal Tracking (v3.3 - Displaying status only, enforcement removed)
        first_signal = db.get_first_signal_timestamp()
        if first_signal:
            days_tracked = (datetime.now() - first_signal).days
            log_info(f"📊 Signal Tracking Status: {days_tracked} days of data recorded.")
        else:
            log_info(f"📊 Signal Tracking: No historical data found.")

        
        self.running = True
        cycle_count = 0
        
        while self.running:
            try:
                cycle_count += 1
                log_info(f"--- Cycle {cycle_count} ---")
                
                # Get current equity
                account_equity = exchange_client.get_total_equity()
                if account_equity <= 0:
                    log_warning("Unable to fetch account equity, skipping cycle")
                    time.sleep(60)
                    continue
                
                log_info(f"Account equity: ${account_equity:,.2f}")
                
                # v3.3: Check circuit breakers (Daily Loss 6%, Drawdown 15%, etc.)
                can_trade, reason = risk_manager.check_circuit_breakers(account_equity)
                if not can_trade:
                    log_warning(f"CIRCUIT BREAKER TRIGGERED: {reason}")
                    self._create_alert('circuit_breaker', 'GLOBAL', reason)
                    # We don't stop the loop (to allow exit management), but can_trade() will block entries
                
                # Check existing positions
                self._check_open_positions()
                
                # Record equity snapshot every cycle
                self._record_equity_snapshot()
                
                # Log Nansen signals for v3.3 tracking
                self._log_all_nansen_signals()
                
                # Process each trading pair
                for symbol in config.all_pairs:
                    try:
                        traded = self._process_symbol(symbol, account_equity)
                        if traded:
                            log_info(f"Trade executed for {symbol}")
                    except Exception as e:
                        log_error(f"Error processing {symbol}: {e}")
                
                # Sleep until next cycle
                log_info(f"Sleeping {config.loop_interval_seconds}s until next cycle...")
                
                # Sleep in small increments to allow for graceful shutdown
                for _ in range(config.loop_interval_seconds):
                    if not self.running:
                        break
                    time.sleep(1)
                
            except Exception as e:
                log_error(f"Error in main loop: {e}")
                time.sleep(60)
        
        log_info("Bot stopped.")


def main():
    """Entry point."""
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
