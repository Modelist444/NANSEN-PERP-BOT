"""
Database module for trade history and equity tracking.
Uses SQLite for persistence.
"""

import sqlite3
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from dataclasses import dataclass
import json

from logger import log_info, log_error


# Database file path
DB_PATH = Path(__file__).parent / "data" / "trades.db"
DB_PATH.parent.mkdir(exist_ok=True)


@dataclass
class Trade:
    """Represents a completed trade with full audit data."""
    id: Optional[int]
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    stop_loss: float
    take_profit: float
    take_profit_2: float
    position_size: float
    entry_time: datetime
    exit_time: Optional[datetime]
    pnl: Optional[float]
    pnl_percent: Optional[float]
    status: str
    tp1_hit: bool = False
    nansen_signal_strength: float = 0.0
    
    # Audit fields (v4.0 Full Audit Mode)
    acc_balance_at_entry: float = 0.0
    leverage: int = 1
    risk_pct: float = 0.0
    atr_stop_dist: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    audit_data: Optional[Dict] = None  # JSON for EMA, RSI, Scaling, etc.
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'take_profit_2': self.take_profit_2,
            'position_size': self.position_size,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'pnl': self.pnl,
            'pnl_percent': self.pnl_percent,
            'status': self.status,
            'tp1_hit': self.tp1_hit,
            'nansen_signal_strength': self.nansen_signal_strength,
            'acc_balance_at_entry': self.acc_balance_at_entry,
            'leverage': self.leverage,
            'risk_pct': self.risk_pct,
            'atr_stop_dist': self.atr_stop_dist,
            'fees': self.fees,
            'slippage': self.slippage,
            'audit_data': self.audit_data
        }


@dataclass
class EquitySnapshot:
    """Represents an equity snapshot for the equity curve."""
    id: Optional[int]
    timestamp: datetime
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'equity': self.equity,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl
        }


@dataclass
class Alert:
    """Represents an alert notification."""
    id: Optional[int]
    timestamp: datetime
    alert_type: str  # 'stop_hit', 'tp_reached', 'strong_signal', 'error'
    symbol: str
    message: str
    data: Optional[Dict]
    read: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'alert_type': self.alert_type,
            'symbol': self.symbol,
            'message': self.message,
            'data': self.data,
            'read': self.read
        }

@dataclass
class NansenSignalLog:
    """Represents a logged Nansen signal for tracking (v3.3)."""
    id: Optional[int]
    timestamp: datetime
    symbol: str
    signal_type: str
    strength: float
    smart_money_netflow: float
    exchange_netflow: float
    price_at_signal: float
    would_have_traded: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'signal_type': self.signal_type,
            'strength': self.strength,
            'smart_money_netflow': self.smart_money_netflow,
            'exchange_netflow': self.exchange_netflow,
            'price_at_signal': self.price_at_signal,
            'would_have_traded': self.would_have_traded
        }


class Database:
    """SQLite database manager for trade persistence."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """Initialize database tables."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                take_profit_2 REAL NOT NULL DEFAULT 0,
                position_size REAL NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                pnl REAL,
                pnl_percent REAL,
                status TEXT NOT NULL DEFAULT 'open',
                tp1_hit INTEGER DEFAULT 0,
                nansen_signal_strength REAL DEFAULT 0,
                acc_balance_at_entry REAL DEFAULT 0,
                leverage INTEGER DEFAULT 1,
                risk_pct REAL DEFAULT 0,
                atr_stop_dist REAL DEFAULT 0,
                fees REAL DEFAULT 0,
                slippage REAL DEFAULT 0,
                audit_data TEXT
            )
        ''')
        
        # Migrations (Add columns if they don't exist individually)
        for column in [
            ('take_profit_2', 'REAL DEFAULT 0'),
            ('tp1_hit', 'INTEGER DEFAULT 0'),
            ('nansen_signal_strength', 'REAL DEFAULT 0'),
            ('acc_balance_at_entry', 'REAL DEFAULT 0'),
            ('leverage', 'INTEGER DEFAULT 1'),
            ('risk_pct', 'REAL DEFAULT 0'),
            ('atr_stop_dist', 'REAL DEFAULT 0'),
            ('fees', 'REAL DEFAULT 0'),
            ('slippage', 'REAL DEFAULT 0'),
            ('audit_data', 'TEXT')
        ]:
            try:
                cursor.execute(f'ALTER TABLE trades ADD COLUMN {column[0]} {column[1]}')
            except sqlite3.OperationalError:
                pass # Column already exists
        
        # Equity snapshots table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                equity REAL NOT NULL,
                unrealized_pnl REAL DEFAULT 0,
                realized_pnl REAL DEFAULT 0
            )
        ''')
        
        # Alerts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT,
                read INTEGER DEFAULT 0
            )
        ''')

        # Nansen Signals Log table (v3.3 tracking)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nansen_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                strength REAL NOT NULL,
                smart_money_netflow REAL NOT NULL,
                exchange_netflow REAL NOT NULL,
                price_at_signal REAL NOT NULL,
                would_have_traded INTEGER DEFAULT 0
            )
        ''')
        
        conn.commit()
        conn.close()
        log_info(f"Database initialized at {self.db_path}")
    
    # Trade operations
    def insert_trade(self, trade: Trade) -> int:
        """Insert a new trade and return its ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades (symbol, direction, entry_price, exit_price, stop_loss, take_profit, take_profit_2,
             position_size, entry_time, exit_time, pnl, pnl_percent, status, tp1_hit, 
             nansen_signal_strength, acc_balance_at_entry, leverage, risk_pct, atr_stop_dist, 
             fees, slippage, audit_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade.symbol, trade.direction, trade.entry_price, trade.exit_price,
            trade.stop_loss, trade.take_profit, trade.take_profit_2, trade.position_size,
            trade.entry_time.isoformat(), 
            trade.exit_time.isoformat() if trade.exit_time else None,
            trade.pnl, trade.pnl_percent, trade.status, 
            1 if trade.tp1_hit else 0, trade.nansen_signal_strength,
            trade.acc_balance_at_entry, trade.leverage, trade.risk_pct, 
            trade.atr_stop_dist, trade.fees, trade.slippage, 
            json.dumps(trade.audit_data) if trade.audit_data else None
        ))
        
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return trade_id
    
    def update_trade(self, trade_id: int, **updates) -> bool:
        """Update a trade with given fields."""
        if not updates:
            return False
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values())
        values.append(trade_id)
        
        cursor.execute(f'UPDATE trades SET {set_clause} WHERE id = ?', values)
        
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0
    
    def close_trade(
        self, 
        trade_id: int, 
        exit_price: float, 
        status: str
    ) -> bool:
        """Close a trade with exit details."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Get the trade to calculate PnL
        cursor.execute('SELECT * FROM trades WHERE id = ?', (trade_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return False
        
        entry_price = row['entry_price']
        position_size = row['position_size']
        direction = row['direction']
        
        # Calculate PnL
        if direction == 'long':
            pnl = (exit_price - entry_price) * position_size
        else:
            pnl = (entry_price - exit_price) * position_size
        
        pnl_percent = (pnl / (entry_price * position_size)) * 100
        
        cursor.execute('''
            UPDATE trades 
            SET exit_price = ?, exit_time = ?, pnl = ?, pnl_percent = ?, status = ?
            WHERE id = ?
        ''', (exit_price, datetime.now().isoformat(), pnl, pnl_percent, status, trade_id))
        
        conn.commit()
        conn.close()
        return pnl
    
    def get_open_trades(self) -> List[Trade]:
        """Get all open trades."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM trades WHERE status = "open"')
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_trade(row) for row in rows]
    
    def get_trade_history(self, limit: int = 50) -> List[Trade]:
        """Get recent trade history."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?', 
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_trade(row) for row in rows]
    
    def get_trade_by_symbol(self, symbol: str) -> Optional[Trade]:
        """Get open trade for a symbol."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT * FROM trades WHERE symbol = ? AND status = "open"', 
            (symbol,)
        )
        row = cursor.fetchone()
        conn.close()
        
        return self._row_to_trade(row) if row else None
    
    def _row_to_trade(self, row: sqlite3.Row) -> Trade:
        """Convert database row to Trade object."""
        return Trade(
            id=row['id'],
            symbol=row['symbol'],
            direction=row['direction'],
            entry_price=row['entry_price'],
            exit_price=row['exit_price'],
            stop_loss=row['stop_loss'],
            take_profit=row['take_profit'],
            take_profit_2=row['take_profit_2'] if 'take_profit_2' in row.keys() else 0,
            position_size=row['position_size'],
            entry_time=datetime.fromisoformat(row['entry_time']),
            exit_time=datetime.fromisoformat(row['exit_time']) if row['exit_time'] else None,
            pnl=row['pnl'],
            pnl_percent=row['pnl_percent'],
            status=row['status'],
            tp1_hit=bool(row['tp1_hit']) if 'tp1_hit' in row.keys() else False,
            nansen_signal_strength=row['nansen_signal_strength'] if 'nansen_signal_strength' in row.keys() else 0.0,
            acc_balance_at_entry=row['acc_balance_at_entry'] if 'acc_balance_at_entry' in row.keys() else 0.0,
            leverage=row['leverage'] if 'leverage' in row.keys() else 1,
            risk_pct=row['risk_pct'] if 'risk_pct' in row.keys() else 0.0,
            atr_stop_dist=row['atr_stop_dist'] if 'atr_stop_dist' in row.keys() else 0.0,
            fees=row['fees'] if 'fees' in row.keys() else 0.0,
            slippage=row['slippage'] if 'slippage' in row.keys() else 0.0,
            audit_data=json.loads(row['audit_data']) if 'audit_data' in row.keys() and row['audit_data'] else None
        )
    
    # Equity operations
    def insert_equity_snapshot(self, snapshot: EquitySnapshot) -> int:
        """Insert an equity snapshot."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO equity_snapshots (timestamp, equity, unrealized_pnl, realized_pnl)
            VALUES (?, ?, ?, ?)
        ''', (
            snapshot.timestamp.isoformat(),
            snapshot.equity,
            snapshot.unrealized_pnl,
            snapshot.realized_pnl
        ))
        
        snapshot_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return snapshot_id
    
    def get_equity_history(self, limit: int = 168) -> List[EquitySnapshot]:
        """Get equity history (default: 1 week of hourly data)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT * FROM equity_snapshots ORDER BY timestamp DESC LIMIT ?',
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            EquitySnapshot(
                id=row['id'],
                timestamp=datetime.fromisoformat(row['timestamp']),
                equity=row['equity'],
                unrealized_pnl=row['unrealized_pnl'],
                realized_pnl=row['realized_pnl']
            )
            for row in reversed(rows)  # Return in chronological order
        ]
    
    # Alert operations
    def insert_alert(self, alert: Alert) -> int:
        """Insert a new alert."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO alerts (timestamp, alert_type, symbol, message, data, read)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            alert.timestamp.isoformat(),
            alert.alert_type,
            alert.symbol,
            alert.message,
            json.dumps(alert.data) if alert.data else None,
            1 if alert.read else 0
        ))
        
        alert_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return alert_id
    
    def get_unread_alerts(self) -> List[Alert]:
        """Get all unread alerts."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM alerts WHERE read = 0 ORDER BY timestamp DESC')
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_alert(row) for row in rows]
    
    def get_recent_alerts(self, limit: int = 20) -> List[Alert]:
        """Get recent alerts."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?',
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_alert(row) for row in rows]
    
    def mark_alert_read(self, alert_id: int):
        """Mark an alert as read."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE alerts SET read = 1 WHERE id = ?', (alert_id,))
        conn.commit()
        conn.close()
    
    def _row_to_alert(self, row: sqlite3.Row) -> Alert:
        """Convert database row to Alert object."""
        return Alert(
            id=row['id'],
            timestamp=datetime.fromisoformat(row['timestamp']),
            alert_type=row['alert_type'],
            symbol=row['symbol'],
            message=row['message'],
            data=json.loads(row['data']) if row['data'] else None,
            read=bool(row['read'])
        )
    
    # Statistics
    def get_trading_stats(self) -> Dict[str, Any]:
        """Get overall trading statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Total trades
        cursor.execute('SELECT COUNT(*) FROM trades WHERE status != "open"')
        total_trades = cursor.fetchone()[0]
        
        # Winning trades
        cursor.execute('SELECT COUNT(*) FROM trades WHERE pnl > 0')
        winning_trades = cursor.fetchone()[0]
        
        # Total PnL
        cursor.execute('SELECT SUM(pnl) FROM trades WHERE pnl IS NOT NULL')
        total_pnl = cursor.fetchone()[0] or 0
        
        # Average PnL
        cursor.execute('SELECT AVG(pnl) FROM trades WHERE pnl IS NOT NULL')
        avg_pnl = cursor.fetchone()[0] or 0
        
        # Daily trades
        today = datetime.now().date().isoformat()
        cursor.execute('SELECT COUNT(*) FROM trades WHERE entry_time >= ?', (today,))
        trades_today = cursor.fetchone()[0]
        
        conn.close()
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        from risk import risk_manager
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'average_pnl': avg_pnl,
            'trades_today': trades_today,
            'daily_pnl': risk_manager.get_stats().get('daily_pnl', 0.0),
            'max_trades_per_day': risk_manager.get_stats().get('max_trades_per_day', 5),
            'trading_halted': risk_manager.trading_halted,
            'halt_reason': risk_manager.halt_reason
        }

    # Nansen Signal Tracking (v3.3)
    def insert_nansen_signal(self, signal: NansenSignalLog) -> int:
        """Insert a Nansen signal for tracking."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO nansen_signals 
            (timestamp, symbol, signal_type, strength, smart_money_netflow, 
             exchange_netflow, price_at_signal, would_have_traded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal.timestamp.isoformat(),
            signal.symbol,
            signal.signal_type,
            signal.strength,
            signal.smart_money_netflow,
            signal.exchange_netflow,
            signal.price_at_signal,
            1 if signal.would_have_traded else 0
        ))
        
        signal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return signal_id

    def get_nansen_signals(self, limit: int = 100) -> List[NansenSignalLog]:
        """Get recent Nansen signals."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM nansen_signals ORDER BY timestamp DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        return [
            NansenSignalLog(
                id=row['id'],
                timestamp=datetime.fromisoformat(row['timestamp']),
                symbol=row['symbol'],
                signal_type=row['signal_type'],
                strength=row['strength'],
                smart_money_netflow=row['smart_money_netflow'],
                exchange_netflow=row['exchange_netflow'],
                price_at_signal=row['price_at_signal'],
                would_have_traded=bool(row['would_have_traded'])
            ) for row in rows
        ]

    def get_first_signal_timestamp(self) -> Optional[datetime]:
        """Get the timestamp of the very first logged signal."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT MIN(timestamp) FROM nansen_signals')
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None




# Global database instance
db = Database()
