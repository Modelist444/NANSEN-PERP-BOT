"""
WebSocket server for real-time dashboard updates.
Uses FastAPI with WebSocket support.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from config import config
from database import db
from exchange import exchange_client
from nansen import nansen_client, SignalType
from logger import log_info, log_error


class ConnectionManager:
    """Manage WebSocket connections."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        log_info(f"Dashboard client connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        log_info(f"Dashboard client disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        if not self.active_connections:
            return
        
        data = json.dumps(message, default=str)
        disconnected = []
        
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception:
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


async def get_dashboard_data() -> Dict[str, Any]:
    """Gather all data for the dashboard."""
    try:
        # Get account info
        balance = exchange_client.get_account_balance()
        equity = exchange_client.get_total_equity()
        
        # Get positions from exchange
        positions = exchange_client.get_open_positions()
        positions_data = [
            {
                'symbol': p.symbol,
                'side': p.side.value,
                'size': p.size,
                'entry_price': p.entry_price,
                'unrealized_pnl': p.unrealized_pnl,
                'leverage': p.leverage
            }
            for p in positions
        ]
        
        # Get open trades from database (with SL/TP info)
        open_trades = db.get_open_trades()
        trades_data = [t.to_dict() for t in open_trades]
        
        # Get Nansen signals for all pairs
        signals = []
        for symbol in config.all_pairs:
            signal = nansen_client.get_signal(symbol)
            if signal:
                signals.append({
                    'symbol': symbol,
                    'type': signal.signal_type.value,
                    'strength': signal.strength,
                    'smart_money_netflow': signal.smart_money_netflow,
                    'exchange_netflow': signal.exchange_netflow
                })
            else:
                signals.append({
                    'symbol': symbol,
                    'type': 'unknown',
                    'strength': 0,
                    'smart_money_netflow': 0,
                    'exchange_netflow': 0
                })
        
        # Get trade history
        history = db.get_trade_history(limit=50)
        history_data = [t.to_dict() for t in history]
        
        # Get equity curve
        equity_history = db.get_equity_history(limit=168)
        equity_data = [e.to_dict() for e in equity_history]
        
        # Get alerts
        alerts = db.get_recent_alerts(limit=20)
        alerts_data = [a.to_dict() for a in alerts]
        
        # Get stats
        stats = db.get_trading_stats()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'account': {
                'balance': balance,
                'equity': equity,
                'unrealized_pnl': equity - balance
            },
            'positions': positions_data,
            'open_trades': trades_data,
            'signals': signals,
            'trade_history': history_data,
            'equity_curve': equity_data,
            'alerts': alerts_data,
            'stats': stats,
            'config': {
                'dry_run': config.dry_run,
                'pairs': config.all_pairs,
                'risk_per_trade': config.risk_per_trade,
                'tp1_pct': config.tp1_pct,
                'tp2_pct': config.tp2_pct
            }
        }
    except Exception as e:
        log_error(f"Error getting dashboard data: {e}")
        return {'error': str(e)}


async def broadcast_updates():
    """Periodically broadcast updates to all clients."""
    while True:
        try:
            if manager.active_connections:
                data = await get_dashboard_data()
                await manager.broadcast({'type': 'update', 'data': data})
        except Exception as e:
            log_error(f"Error broadcasting updates: {e}")
        
        await asyncio.sleep(5)  # Update every 5 seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    # Start background task
    task = asyncio.create_task(broadcast_updates())
    log_info("Dashboard server started")
    yield
    # Cleanup
    task.cancel()


app = FastAPI(title="Nansen Trading Dashboard", lifespan=lifespan)

# Dashboard directory
DASHBOARD_DIR = Path(__file__).parent / "dashboard"
DASHBOARD_DIR.mkdir(exist_ok=True)


@app.get("/")
async def root():
    """Serve the dashboard HTML."""
    index_file = DASHBOARD_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Dashboard not found. Please create dashboard/index.html"}


@app.get("/api/data")
async def get_data():
    """REST endpoint for dashboard data."""
    return await get_dashboard_data()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    
    try:
        # Send initial data
        data = await get_dashboard_data()
        await websocket.send_json({'type': 'initial', 'data': data})
        
        # Keep connection alive and handle messages
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30
                )
                # Handle client messages if needed
                msg_data = json.loads(message)
                if msg_data.get('type') == 'ping':
                    await websocket.send_json({'type': 'pong'})
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({'type': 'heartbeat'})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log_error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# Mount static files if they exist
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


def run_server():
    """Run the dashboard server."""
    log_info(f"Starting dashboard server on port {config.dashboard_port}")
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=config.dashboard_port,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()
