"""
SQLite database for position tracking and bot state.
"""
import sqlite3
import json
from typing import Dict, List, Optional
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)


class Database:
    """
    SQLite database for bot state management.
    
    Tracks:
    - Open positions
    - Closed positions
    - Bot state
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        
        # Create directory if needed
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Positions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                entry_time TEXT NOT NULL,
                exit_price REAL,
                exit_time TEXT,
                pnl REAL,
                pnl_pct REAL,
                status TEXT NOT NULL,
                entry_reason TEXT,
                exit_reason TEXT,
                metadata TEXT
            )
        """)
        
        # Bot state table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_symbol 
            ON positions(symbol)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_status 
            ON positions(status)
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized: {self.db_path}")
    
    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        entry_reason: str = '',
        metadata: Optional[Dict] = None
    ) -> int:
        """
        Record a new open position.
        
        Returns:
            Position ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        entry_time = datetime.utcnow().isoformat()
        metadata_json = json.dumps(metadata) if metadata else '{}'
        
        cursor.execute("""
            INSERT INTO positions 
            (symbol, side, entry_price, quantity, entry_time, status, entry_reason, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, side, entry_price, quantity, entry_time, 'OPEN', entry_reason, metadata_json))
        
        position_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Position opened: {symbol} id={position_id}")
        return position_id
    
    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str = ''
    ):
        """Close a position and calculate P&L."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get position data
        cursor.execute("""
            SELECT entry_price, quantity, side FROM positions WHERE id = ?
        """, (position_id,))
        
        result = cursor.fetchone()
        if not result:
            logger.error(f"Position {position_id} not found")
            conn.close()
            return
        
        entry_price, quantity, side = result
        
        # Calculate P&L
        if side == 'BUY':
            pnl = (exit_price - entry_price) * quantity
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        else:  # SELL
            pnl = (entry_price - exit_price) * quantity
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100
        
        exit_time = datetime.utcnow().isoformat()
        
        # Update position
        cursor.execute("""
            UPDATE positions
            SET exit_price = ?, exit_time = ?, pnl = ?, pnl_pct = ?, status = ?, exit_reason = ?
            WHERE id = ?
        """, (exit_price, exit_time, pnl, pnl_pct, 'CLOSED', exit_reason, position_id))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Position closed: id={position_id} pnl={pnl:.2f} ({pnl_pct:.2f}%)")
    
    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Get all open positions.
        
        Args:
            symbol: Filter by symbol (optional)
        
        Returns:
            List of position dictionaries
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if symbol:
            cursor.execute("""
                SELECT id, symbol, side, entry_price, quantity, entry_time, entry_reason, metadata
                FROM positions
                WHERE status = 'OPEN' AND symbol = ?
            """, (symbol,))
        else:
            cursor.execute("""
                SELECT id, symbol, side, entry_price, quantity, entry_time, entry_reason, metadata
                FROM positions
                WHERE status = 'OPEN'
            """)
        
        results = cursor.fetchall()
        conn.close()
        
        positions = []
        for row in results:
            positions.append({
                'id': row[0],
                'symbol': row[1],
                'side': row[2],
                'entry_price': row[3],
                'quantity': row[4],
                'entry_time': row[5],
                'entry_reason': row[6],
                'metadata': json.loads(row[7]) if row[7] else {}
            })
        
        return positions
    
    def get_closed_positions(
        self,
        symbol: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get closed positions."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if symbol:
            cursor.execute("""
                SELECT id, symbol, side, entry_price, exit_price, quantity, 
                       entry_time, exit_time, pnl, pnl_pct, entry_reason, exit_reason
                FROM positions
                WHERE status = 'CLOSED' AND symbol = ?
                ORDER BY exit_time DESC
                LIMIT ?
            """, (symbol, limit))
        else:
            cursor.execute("""
                SELECT id, symbol, side, entry_price, exit_price, quantity, 
                       entry_time, exit_time, pnl, pnl_pct, entry_reason, exit_reason
                FROM positions
                WHERE status = 'CLOSED'
                ORDER BY exit_time DESC
                LIMIT ?
            """, (limit,))
        
        results = cursor.fetchall()
        conn.close()
        
        positions = []
        for row in results:
            positions.append({
                'id': row[0],
                'symbol': row[1],
                'side': row[2],
                'entry_price': row[3],
                'exit_price': row[4],
                'quantity': row[5],
                'entry_time': row[6],
                'exit_time': row[7],
                'pnl': row[8],
                'pnl_pct': row[9],
                'entry_reason': row[10],
                'exit_reason': row[11]
            })
        
        return positions
    
    def set_state(self, key: str, value: any):
        """Set a bot state value."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        value_json = json.dumps(value)
        updated_at = datetime.utcnow().isoformat()
        
        cursor.execute("""
            INSERT OR REPLACE INTO bot_state (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value_json, updated_at))
        
        conn.commit()
        conn.close()
    
    def get_state(self, key: str, default: any = None) -> any:
        """Get a bot state value."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT value FROM bot_state WHERE key = ?
        """, (key,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return json.loads(result[0])
        return default
