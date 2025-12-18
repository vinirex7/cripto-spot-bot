import os
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.utils import ensure_dir


class HistoryStore:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.db_path = config["paths"]["db_path"]
        ensure_dir(os.path.dirname(self.db_path))
        self._ensure_tables()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_tables(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ohlcv_1d (
                    symbol TEXT NOT NULL,
                    open_time INTEGER NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    close_time INTEGER,
                    PRIMARY KEY (symbol, open_time)
                )
            """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ohlcv_1h (
                    symbol TEXT NOT NULL,
                    open_time INTEGER NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    close_time INTEGER,
                    PRIMARY KEY (symbol, open_time)
                )
            """
            )

    def store_candles(
        self, interval: str, symbol: str, candles: Iterable[Tuple]
    ) -> int:
        table = self._table_name(interval)
        placeholders = ",".join(["?"] * 8)
        rows = list(candles)
        if not rows:
            return 0
        with self._conn() as conn:
            conn.executemany(
                f"""
                INSERT OR REPLACE INTO {table}
                (symbol, open_time, open, high, low, close, volume, close_time)
                VALUES ({placeholders})
                """,
                rows,
            )
            return len(rows)

    def _table_name(self, interval: str) -> str:
        if interval == "1d":
            return "ohlcv_1d"
        if interval == "1h":
            return "ohlcv_1h"
        raise ValueError(f"Unsupported interval {interval}")

    def latest_open_time(self, interval: str, symbol: str) -> Optional[int]:
        table = self._table_name(interval)
        with self._conn() as conn:
            cur = conn.execute(
                f"SELECT MAX(open_time) FROM {table} WHERE symbol=?", (symbol,)
            )
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else None

    def fetch_ohlcv(
        self, interval: str, symbol: str, limit: int
    ) -> List[Tuple[int, float]]:
        table = self._table_name(interval)
        with self._conn() as conn:
            cur = conn.execute(
                f"""
                SELECT open_time, close FROM {table}
                WHERE symbol=?
                ORDER BY open_time DESC
                LIMIT ?
                """,
                (symbol, limit),
            )
            rows = cur.fetchall()
            return rows[::-1]

    def validate_gaps(
        self, interval: str, symbol: str, max_gap_candles: int
    ) -> bool:
        table = self._table_name(interval)
        with self._conn() as conn:
            cur = conn.execute(
                f"""
                SELECT open_time FROM {table}
                WHERE symbol=?
                ORDER BY open_time ASC
                """,
                (symbol,),
            )
            rows = [r[0] for r in cur.fetchall()]
            if len(rows) < 2:
                return True
            expected = 86_400_000 if interval == "1d" else 3_600_000
            gaps = 0
            for prev, nxt in zip(rows, rows[1:]):
                delta = (nxt - prev) // expected - 1
                if delta > 0:
                    gaps += delta
            return gaps <= max_gap_candles
