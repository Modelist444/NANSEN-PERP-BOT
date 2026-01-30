"""
Nansen Perp Trading Bot - Main Entry Point
Nansen SMF Strategy v4.0: Orchestrates the trading loop with Nansen signals and exchange execution.
"""

import time
import signal
import sys
import json
import csv
import os
from datetime import datetime
from typing import Optional

from config import config
from logger import log_info, log_error, log_warning, log_trade
from nansen import nansen_client
from exchange import exchange_client, OrderSide
from strategy import trading_strategy, TradeDirection
from risk import risk_manager
from database import db, Trade, EquitySnapshot, Alert, NansenSignalLog
from server import run_server, shared_state
import threading


class TradingBot:
    """Main trading bot orchestrator for Nansen SMF Strategy v4.0."""

    def __init__(self):
        """Initialize the bot."""
        log_info("🚀 Nansen Perp Bot v4.3.2.1-FIX-422 starting...")
        self.running = False
        self._setup_signal_handlers()
        self._ensure_data_dirs()
    
    def _setup_signal_handlers(self):
        """Set up graceful shutdown handlers."""
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
    
    def _shutdown(self, signum, frame):
        """Handle shutdown signals."""
        log_info("\nShutdown signal received, stopping bot...")
        self.running = False
    
    def _ensure_data_dirs(self):
        """Ensure data directories exist for logging."""
        os.makedirs('data', exist_ok=True)
        os.makedirs('logs', exist_ok=True)
    
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
        """Log Nansen signals for all tracked pairs."""
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

    def _log_trade_to_csv(self, trade_data: dict):
        """Log trade to CSV file for auditability."""
        csv_path = 'data/trades.csv'
        file_exists = os.path.exists(csv_path)
        
        try:
            with open(csv_path, 'a', newline='') as f:
                fieldnames = [
                    'timestamp', 'symbol', 'direction', 'confidence_score',
                    'entry_price', 'stop_loss', 'take_profit', 'position_size',
                    'leverage', 'risk_pct', 'status', 'pnl', 'drawdown'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                writer.writerow(trade_data)
                
        except Exception as e:
            log_error(f"Error writing to trades CSV: {e}")
    
    def _log_trade_to_json(self, trade_data: dict):
        """Log trade to JSON-Lines file for performance."""
        json_path = 'data/trades.jsonl'
        
        try:
            with open(json_path, 'a') as f:
                f.write(json.dumps(trade_data) + '\n')
                
        except Exception as e:
            log_error(f"Error writing to trades JSON: {e}")

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
        """Monitor open positions for exit rules (SL, TP, Early Exit)."""
        db_trades = db.get_open_trades()
        
        for trade in db_trades:
            current_price = exchange_client.get_current_price(trade.symbol)
            if not current_price:
                continue
            
            # 1. Early Exit Check (Nansen signal reversal)
            should_exit, reason = trading_strategy.check_early_exit(trade.symbol, trade)
            if should_exit:
                self._create_alert('early_exit', trade.symbol, f"Early exit: {reason}")
                exchange_client.cancel_all_orders(trade.symbol)
                exchange_client.place_market_order(
                    trade.symbol, 
                    OrderSide.SELL if trade.direction == 'long' else OrderSide.BUY,
                    trade.position_size, 
                    reduce_only=True
                )
                pnl = db.close_trade(trade.id, current_price, 'closed_early')
                if pnl:
                    risk_manager.update_daily_pnl(pnl)
                    risk_manager.record_trade_result(trade.symbol, pnl, exchange_client.get_total_equity())
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
                    risk_manager.record_trade_result(trade.symbol, pnl, exchange_client.get_total_equity())
                risk_manager.close_position_record(trade.symbol)
                if not config.dry_run:
                    exchange_client.cancel_all_orders(trade.symbol)
                continue

            # 3. Take Profit Check
            is_tp_hit = (current_price >= trade.take_profit if trade.direction == 'long' else current_price <= trade.take_profit)
            if is_tp_hit:
                self._create_alert('tp_reached', trade.symbol, f"Take Profit reached at {current_price:.2f}")
                pnl = db.close_trade(trade.id, current_price, 'closed_tp')
                if pnl:
                    risk_manager.update_daily_pnl(pnl)
                    risk_manager.record_trade_result(trade.symbol, pnl, exchange_client.get_total_equity())
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
        can_trade, reason = risk_manager.can_trade(symbol)
        if not can_trade:
            log_info(f"{symbol}: Cannot trade - {reason}")
            return False
        
        # Check if already has position
        if risk_manager.has_position(symbol):
            return False
        
        # Generate signal using v4.0 strategy
        signal = trading_strategy.generate_signal(symbol, account_equity)
        
        if not signal:
            return False
        
        # Validate trade
        is_valid, reason = risk_manager.validate_trade(
            symbol=signal.symbol,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            position_size=signal.position_size,
            account_equity=account_equity
        )
        
        if not is_valid:
            log_warning(f"{symbol}: Trade validation failed - {reason}")
            return False
        
        # Execute trade
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
        
        # Place stop loss (1.5x ATR)
        sl_side = OrderSide.SELL if signal.direction == TradeDirection.LONG else OrderSide.BUY
        exchange_client.place_stop_loss(
            symbol=signal.symbol,
            side=sl_side,
            quantity=signal.position_size,
            stop_price=signal.stop_loss
        )
        
        # Place take profit (2.5x ATR)
        exchange_client.place_take_profit(
            symbol=signal.symbol,
            side=sl_side,
            quantity=signal.position_size,
            tp_price=signal.take_profit
        )
        
        # Record in database
        trade = Trade(
            id=None,
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_price=entry_order.price,
            exit_price=None,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            take_profit_2=signal.trailing_stop,
            position_size=signal.position_size,
            entry_time=datetime.now(),
            exit_time=None,
            pnl=None,
            pnl_percent=None,
            status='open',
            tp1_hit=False,
            nansen_signal_strength=signal.signals.confidence_score,
            acc_balance_at_entry=signal.account_balance,
            leverage=signal.leverage,
            risk_pct=signal.risk_pct,
            atr_stop_dist=signal.stop_distance_atr,
            fees=0.0, # Will update on exit
            slippage=0.0,
            audit_data=signal.to_dict()
        )
        db.insert_trade(trade)
        
        # Record for risk manager
        risk_manager.record_trade(
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_price=entry_order.price,
            position_size=signal.position_size,
            conviction=signal.conviction,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit
        )
        
        # Log trade for auditability
        trade_log = {
            'timestamp': datetime.now().isoformat(),
            'symbol': signal.symbol,
            'direction': signal.direction.value,
            'confidence_score': signal.signals.confidence_score,
            'entry_price': entry_order.price,
            'stop_loss': signal.stop_loss,
            'take_profit': signal.take_profit,
            'position_size': signal.position_size,
            'leverage': signal.leverage,
            'risk_pct': signal.risk_pct * 100,
            'status': 'open',
            'pnl': None,
            'drawdown': 0
        }
        self._log_trade_to_csv(trade_log)
        self._log_trade_to_json(trade_log)
        
        # Create alert for strong signal
        if signal.signals.confidence_score >= 0.7:
            self._create_alert(
                'strong_signal',
                symbol,
                f"Strong {signal.direction.value} signal (confidence: {signal.signals.confidence_score:.2f})",
                signal.to_dict()
            )
        
        log_trade(
            action="OPEN",
            symbol=signal.symbol,
            side=signal.direction.value,
            quantity=signal.position_size,
            price=entry_order.price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit
        )
        
        return True
    
    def run(self):
        """Main trading loop."""
        # Start dashboard in background
        dashboard_thread = threading.Thread(target=run_server, daemon=True)
        dashboard_thread.start()
        log_info(f"Dashboard available at: http://localhost:{config.dashboard_port}")
        log_info("=" * 60)
        log_info(f"  {config.strategy_name} v{config.strategy_version}")
        log_info("=" * 60)
        log_info(f"Mode: {'DRY RUN' if config.dry_run else 'LIVE TRADING'}")
        log_info(f"Testnet: {config.use_testnet}")
        log_info(f"Pairs: {config.all_pairs}")
        log_info(f"Timeframe: {config.timeframe}")
        log_info(f"Risk per trade: {config.risk_per_trade * 100:.1f}%")
        log_info(f"Max trades/day: {config.max_trades_per_day}")
        log_info(f"Leverage: {config.base_leverage}x")
        log_info(f"SL: {config.stop_loss_atr_mult}x ATR | TP: {config.take_profit_atr_mult}x ATR")
        log_info("=" * 60)
        
        if not config.dry_run and not config.use_testnet:
            log_warning("⚠️  LIVE MAINNET TRADING - Real orders will be placed!")
            time.sleep(5)
        elif not config.dry_run and config.use_testnet:
            log_info("🧪 TESTNET LIVE TRADING - Orders will be placed on testnet")
            time.sleep(2)
        
        self.running = True
        cycle_count = 0
        
        while self.running:
            try:
                cycle_count += 1
                log_info(f"--- Cycle {cycle_count} ---")
                
                # Get current equity
                account_equity = exchange_client.get_total_equity()
                if account_equity <= 0:
                    log_warning(f"Account equity is {account_equity}. Ensure your Bybit Testnet account is funded.")
                
                log_info(f"Account equity: ${account_equity:,.2f}")
                
                # Get risk stats
                stats = risk_manager.get_stats()
                log_info(f"Trades today: {stats['trades_today']}/{stats['max_trades_per_day']} | "
                         f"Active: {stats['active_positions']}/{config.max_concurrent_trades}")
                
                # Check circuit breakers
                can_trade, reason = risk_manager.check_circuit_breakers(account_equity)
                if not can_trade:
                    log_warning(f"CIRCUIT BREAKER: {reason}")
                    self._create_alert('circuit_breaker', 'GLOBAL', reason)
                
                # Check existing positions for exits
                self._check_open_positions()
                
                # Record equity snapshot
                self._record_equity_snapshot()
                
                # Log Nansen signals for tracking
                self._log_all_nansen_signals()
                
                # Process each trading pair
                for symbol in config.all_pairs:
                    try:
                        traded = self._process_symbol(symbol, account_equity)
                        if traded:
                            log_info(f"✅ Trade executed for {symbol}")
                    except Exception as e:
                        log_error(f"Error processing {symbol}: {e}")
                
                # Sleep until next cycle
                log_info(f"Sleeping {config.loop_interval_seconds}s until next cycle...")
                
                # Update heartbeat
                shared_state.update_heartbeat()
                shared_state.set_status(f"sleeping_cycle_{cycle_count}")
                
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
