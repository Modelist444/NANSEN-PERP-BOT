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
    """Represents a completed trade."""
    id: Optional[int]
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    stop_loss: float
    take_profit: float  # Partial TP1 for ASMM
    take_profit_2: float # Final TP2 for ASMM
    position_size: float
    entry_time: datetime
    exit_time: Optional[datetime]
    pnl: Optional[float]
    pnl_percent: Optional[float]
    status: str  # 'open', 'closed_tp', 'closed_sl', 'closed_manual'
    tp1_hit: bool = False
    nansen_signal_strength: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'position_size': self.position_size,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'pnl': self.pnl,
            'pnl_percent': self.pnl_percent,
            'status': self.status,
            'nansen_signal_strength': self.nansen_signal_strength
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
                nansen_signal_strength REAL DEFAULT 0
            )
        ''')
        
        # Migrations (Add columns if they don't exist)
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN take_profit_2 REAL DEFAULT 0')
            cursor.execute('ALTER TABLE trades ADD COLUMN tp1_hit INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass # Columns already exist
        
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
        
        conn.commit()
        conn.close()
        log_info(f"Database initialized at {self.db_path}")
    
    # Trade operations
    def insert_trade(self, trade: Trade) -> int:
        """Insert a new trade and return its ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades 
            (symbol, direction, entry_price, exit_price, stop_loss, take_profit, take_profit_2,
             position_size, entry_time, exit_time, pnl, pnl_percent, status, tp1_hit, nansen_signal_strength)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade.symbol, trade.direction, trade.entry_price, trade.exit_price,
            trade.stop_loss, trade.take_profit, trade.take_profit_2, trade.position_size,
            trade.entry_time.isoformat(), 
            trade.exit_time.isoformat() if trade.exit_time else None,
            trade.pnl, trade.pnl_percent, trade.status, 
            1 if trade.tp1_hit else 0, trade.nansen_signal_strength
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
            take_profit_2=row.get('take_profit_2', 0),
            position_size=row['position_size'],
            entry_time=datetime.fromisoformat(row['entry_time']),
            exit_time=datetime.fromisoformat(row['exit_time']) if row['exit_time'] else None,
            pnl=row['pnl'],
            pnl_percent=row['pnl_percent'],
            status=row['status'],
            tp1_hit=bool(row.get('tp1_hit', 0)),
            nansen_signal_strength=row['nansen_signal_strength']
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
        
        conn.close()
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'average_pnl': avg_pnl
        }


# Global database instance
db = Database()
