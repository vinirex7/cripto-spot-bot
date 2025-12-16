"""
SQLite storage for historical market data.
"""
import sqlite3
import pandas as pd
from typing import List, Optional, Dict
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


class HistoryStore:
    """SQLite-based storage for historical OHLCV data."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create klines table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS klines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                close_time INTEGER NOT NULL,
                quote_volume REAL,
                num_trades INTEGER,
                taker_buy_base REAL,
                taker_buy_quote REAL,
                UNIQUE(symbol, interval, open_time)
            )
        """)
        
        # Create indexes for fast queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_interval_time 
            ON klines(symbol, interval, open_time)
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized: {self.db_path}")
    
    def store_klines(self, symbol: str, interval: str, klines: List[List]):
        """
        Store klines in database.
        
        Args:
            symbol: Trading pair
            interval: Kline interval
            klines: List of klines from Binance API
        """
        if not klines:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for kline in klines:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO klines 
                    (symbol, interval, open_time, open, high, low, close, volume, 
                     close_time, quote_volume, num_trades, taker_buy_base, taker_buy_quote)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    interval,
                    int(kline[0]),  # open_time
                    float(kline[1]),  # open
                    float(kline[2]),  # high
                    float(kline[3]),  # low
                    float(kline[4]),  # close
                    float(kline[5]),  # volume
                    int(kline[6]),  # close_time
                    float(kline[7]) if len(kline) > 7 else 0.0,  # quote_volume
                    int(kline[8]) if len(kline) > 8 else 0,  # num_trades
                    float(kline[9]) if len(kline) > 9 else 0.0,  # taker_buy_base
                    float(kline[10]) if len(kline) > 10 else 0.0  # taker_buy_quote
                ))
            except Exception as e:
                logger.error(f"Error storing kline: {e}")
        
        conn.commit()
        conn.close()
        logger.info(f"Stored {len(klines)} klines for {symbol} {interval}")
    
    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Retrieve klines from database as pandas DataFrame.
        
        Args:
            symbol: Trading pair
            interval: Kline interval
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            limit: Maximum number of rows to return
        
        Returns:
            DataFrame with OHLCV data
        """
        conn = sqlite3.connect(self.db_path)
        
        query = """
            SELECT open_time, open, high, low, close, volume, close_time,
                   quote_volume, num_trades, taker_buy_base, taker_buy_quote
            FROM klines
            WHERE symbol = ? AND interval = ?
        """
        params = [symbol, interval]
        
        if start_time:
            query += " AND open_time >= ?"
            params.append(start_time)
        
        if end_time:
            query += " AND open_time <= ?"
            params.append(end_time)
        
        query += " ORDER BY open_time ASC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('timestamp', inplace=True)
        
        return df
    
    def get_latest_timestamp(self, symbol: str, interval: str) -> Optional[int]:
        """Get the latest timestamp for a symbol/interval."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT MAX(open_time) FROM klines
            WHERE symbol = ? AND interval = ?
        """, (symbol, interval))
        
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result[0] else None
    
    def get_data_coverage(self, symbol: str, interval: str) -> Dict[str, any]:
        """Get information about data coverage for a symbol."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as count,
                MIN(open_time) as first_timestamp,
                MAX(open_time) as last_timestamp
            FROM klines
            WHERE symbol = ? AND interval = ?
        """, (symbol, interval))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] > 0:
            return {
                "count": result[0],
                "first_timestamp": result[1],
                "last_timestamp": result[2],
                "first_date": datetime.fromtimestamp(result[1] / 1000).isoformat(),
                "last_date": datetime.fromtimestamp(result[2] / 1000).isoformat()
            }
        return {}
