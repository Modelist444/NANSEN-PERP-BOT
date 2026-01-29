"""
Mock Demo Script for Nansen SMF Strategy v4.0.
Runs a separate dashboard on port 8001 with simulated data.
"""

import os
import sys
import json
import time
import asyncio
import random
from datetime import datetime, timedelta
from pathlib import Path

# 1. Setup Mock Environment
os.environ["DRY_RUN"] = "true"
os.environ["DASHBOARD_PORT"] = "8001"
os.environ["TRADING_PAIRS"] = "BTCUSDT,ETHUSDT,SOLUSDT"

# 2. Patch Config and Database BEFORE imports
from config import config
config.dashboard_port = 8001
config.dry_run = True

from database import Database, Trade, Alert, NansenSignalLog, EquitySnapshot
from exchange import exchange_client
from risk import risk_manager

# Override risk manager for mock demo
risk_manager.trading_halted = False
risk_manager.halt_reason = "System Healthy (Mock Mode)"
risk_manager.daily_pnl = 150.0  # Show some profit
risk_manager.max_daily_loss = -500.0

# Override database to a mock file
MOCK_DB_PATH = Path("data/mock_trades.db")
if MOCK_DB_PATH.exists():
    MOCK_DB_PATH.unlink()

mock_db = Database(db_path=MOCK_DB_PATH)

# Monkeypatch the global db in database module and everywhere else it might be imported
import database
database.db = mock_db
import server
server.db = mock_db
import main
main.db = mock_db

def seed_data():
    """Seed the mock database with realistic audit data."""
    print("--- Seeding mock database ---")
    
    # Current time
    now = datetime.now()
    
    # 1. Seed Closed Trades (Audit Log)
    trades = [
        {
            'symbol': 'BTCUSDT',
            'direction': 'long',
            'entry_price': 65200.50,
            'exit_price': 67500.20,
            'pnl': 345.50,
            'pnl_percent': 3.5,
            'status': 'closed',
            'time_offset': -48,
            'nansen_strength': 0.85,
            'acc_balance': 10000.0,
            'audit': {
                'nansen_signal': True,
                'nansen_type': 'accumulation',
                'trend_aligned': True,
                'mtf_alignment': {'4H': 'uptrend', '1H': 'uptrend', '15M': 'uptrend'},
                'rsi_valid': True,
                'confidence_score': 0.85
            }
        },
        {
            'symbol': 'ETHUSDT',
            'direction': 'short',
            'entry_price': 3500.00,
            'exit_price': 3420.50,
            'pnl': 120.40,
            'pnl_percent': 2.2,
            'status': 'closed',
            'time_offset': -24, 
            'nansen_strength': 0.72,
            'acc_balance': 10345.50,
            'audit': {
                'nansen_signal': True,
                'nansen_type': 'distribution',
                'trend_aligned': True,
                'mtf_alignment': {'4H': 'downtrend', '1H': 'downtrend', '15M': 'uptrend'},
                'rsi_valid': True,
                'confidence_score': 0.72
            }
        }
    ]
    
    for t in trades:
        entry_time = now + timedelta(hours=t['time_offset'])
        exit_time = now + timedelta(hours=t['time_offset'] + 2)
        
        trade = Trade(
            id=None,
            symbol=t['symbol'],
            direction=t['direction'],
            entry_price=t['entry_price'],
            exit_price=t['exit_price'],
            stop_loss=t['entry_price'] * 0.95 if t['direction'] == 'long' else t['entry_price'] * 1.05,
            take_profit=t['entry_price'] * 1.1 if t['direction'] == 'long' else t['entry_price'] * 0.9,
            take_profit_2=0,
            position_size=1.5 if t['symbol'] == 'BTCUSDT' else 10.0,
            entry_time=entry_time,
            exit_time=exit_time,
            pnl=t['pnl'],
            pnl_percent=t['pnl_percent'],
            status='closed',
            tp1_hit=True,
            nansen_signal_strength=t['nansen_strength'],
            acc_balance_at_entry=t['acc_balance'],
            leverage=4,
            risk_pct=2.0,
            atr_stop_dist=150.0 if t['symbol'] == 'BTCUSDT' else 5.0,
            fees=2.50,
            slippage=1.20,
            audit_data=t['audit']
        )
        mock_db.insert_trade(trade)

    # 1.1 Seed Today's Trades (for daily stats)
    today_trades = [
        {
            'symbol': 'SOLUSDT',
            'direction': 'long',
            'entry_price': 145.20,
            'exit_price': 148.50,
            'pnl': 165.20,
            'pnl_percent': 2.5,
            'status': 'win',
            'time_offset': -2, 
            'nansen_strength': 0.82,
            'acc_balance': 10500.0,
            'audit': {
                'nansen_signal': True,
                'nansen_type': 'accumulation',
                'trend_aligned': True,
                'mtf_alignment': {'4H': 'uptrend', '1H': 'uptrend', '15M': 'side'},
                'rsi_valid': True,
                'confidence_score': 0.82
            }
        }
    ]
    
    for t in today_trades:
        entry_time = now + timedelta(hours=t['time_offset'])
        exit_time = now + timedelta(hours=t['time_offset'] + 1)
        trade = Trade(
            id=None, symbol=t['symbol'], direction=t['direction'], 
            entry_price=t['entry_price'], exit_price=t['exit_price'],
            stop_loss=t['entry_price']*0.97, take_profit=t['entry_price']*1.05, take_profit_2=0,
            position_size=5.0, entry_time=entry_time, exit_time=exit_time,
            pnl=t['pnl'], pnl_percent=t['pnl_percent'], status=t['status'],
            tp1_hit=True, nansen_signal_strength=t['nansen_strength'],
            acc_balance_at_entry=t['acc_balance'], leverage=4, risk_pct=2.0,
            atr_stop_dist=5.0, fees=1.50, slippage=0.50, audit_data=t['audit']
        )
        mock_db.insert_trade(trade)

    # 1.2 Seed Open Trades
    open_trades = [
        {
            'symbol': 'BTCUSDT',
            'direction': 'long',
            'entry_price': 64000.00,
            'nansen_strength': 0.92,
            'acc_balance': 10520.0,
            'audit': {
                'nansen_signal': True,
                'nansen_type': 'accumulation',
                'trend_aligned': True,
                'mtf_alignment': {'4H': 'uptrend', '1H': 'uptrend', '15M': 'uptrend'},
                'rsi_valid': True,
                'confidence_score': 0.92
            }
        }
    ]
    
    for t in open_trades:
        trade = Trade(
            id=None, symbol=t['symbol'], direction=t['direction'],
            entry_price=t['entry_price'], exit_price=None,
            stop_loss=t['entry_price'] * 0.98, take_profit=t['entry_price'] * 1.05, take_profit_2=0,
            position_size=0.5, entry_time=now - timedelta(minutes=45), exit_time=None,
            pnl=0, pnl_percent=0, status='open', tp1_hit=False,
            nansen_signal_strength=t['nansen_strength'], acc_balance_at_entry=t['acc_balance'],
            leverage=4, risk_pct=3.0, atr_stop_dist=120.0, fees=0, slippage=0, audit_data=t['audit']
        )
        mock_db.insert_trade(trade)

    # 1.3 Seed Signal Logs
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT"]
    for symbol in symbols:
        mock_db.insert_nansen_signal(NansenSignalLog(
            id=None, timestamp=now - timedelta(minutes=random.randint(5, 60)),
            symbol=symbol, signal_type="accumulation" if random.random() > 0.5 else "distribution",
            strength=random.uniform(0.7, 0.95), smart_money_netflow=random.uniform(500000, 2000000),
            exchange_netflow=-random.uniform(100000, 1000000), price_at_signal=60000.0 if "BTC" in symbol else 3000.0,
            would_have_traded=random.choice([True, False])
        ))

    # 2. Seed Equity Snapshots (Chart)
    for i in range(30):
        snap_time = now - timedelta(days=30-i)
        balance = 10000 + (i * 50) + (random.randint(0, 5) * 100)
        mock_db.insert_equity_snapshot(EquitySnapshot(None, snap_time, balance, 0.0, 0.0))

    # 3. Seed Alerts
    mock_db.insert_alert(Alert(None, now, "info", "BTCUSDT", "Mock accumulation signal detected.", {}, False))
    mock_db.insert_alert(Alert(None, now - timedelta(minutes=30), "warning", "SYSTEM", "Daily loss limit reached (Simulated).", {}, False))

    print("--- Mock data seeded successfully ---")

async def run_server():
    """Run the FastAPI server."""
    import uvicorn
    from server import app
    
    print(f"Server starting MOCK Dashboard on http://localhost:8001")
    config_uvicorn = uvicorn.Config(app, host="0.0.0.0", port=8001, log_level="info")
    server_uvicorn = uvicorn.Server(config_uvicorn)
    await server_uvicorn.serve()

if __name__ == "__main__":
    seed_data()
    asyncio.run(run_server())
