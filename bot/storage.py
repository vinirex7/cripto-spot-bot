"""Data storage for historical price data."""
from __future__ import annotations

import os
import time
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


class HistoryStore:
    """Storage for historical OHLCV data."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize history store.

        Args:
            config: Bot configuration dictionary
        """
        self.config = config
        self.storage_path = config.get("storage", {}).get("sqlite_path", "./bot.db")
        self.cache: Dict[str, List[List[float]]] = {}

        # Ensure DB directory exists (if path has a folder)
        db_dir = os.path.dirname(self.storage_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._conn = sqlite3.connect(self.storage_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._ensure_schema()

        # Binance client (lazy import to avoid breaking if file path differs)
        self._binance_client = None
        try:
            from execution.binance_client import BinanceSpotClient  # type: ignore

            keys = (config.get("api_keys", {}) or {}).get("binance", {}) or {}
            api_key = (keys.get("api_key") or os.getenv("BINANCE_API_KEY") or "").strip()
            api_secret = (keys.get("api_secret") or os.getenv("BINANCE_API_SECRET") or "").strip()

            binance_cfg = config.get("binance", {}) or {}
            self._binance_client = BinanceSpotClient(
                api_key=api_key,
                api_secret=api_secret,
                config=binance_cfg,
            )
        except Exception:
            # If import fails, DB will still work (but no network backfill).
            self._binance_client = None

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time_ms INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                PRIMARY KEY (symbol, interval, open_time_ms)
            );
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_si_ot ON ohlcv(symbol, interval, open_time_ms);")
        self._conn.commit()

    def fetch_ohlcv(self, interval: str, symbol: str, limit: int = 100) -> List[List[float]]:
        """
        Fetch OHLCV data for a symbol.

        Args:
            interval: Time interval (e.g., "1h", "1d")
            symbol: Trading pair symbol
            limit: Number of candles to fetch

        Returns:
            List of OHLCV candles [timestamp, open, high, low, close, volume]
        """
        # Cache key includes limit to avoid mixing sizes
        cache_key = f"{symbol}_{interval}_{limit}"
        cached = self.cache.get(cache_key)
        if cached and len(cached) >= max(1, limit):
            return cached[-limit:]

        end_time_ms = int(time.time() * 1000)

        # 1) Read from DB first
        rows = self._select_from_db(symbol=symbol, interval=interval, limit=limit, end_time_ms=end_time_ms)
        if len(rows) >= limit:
            out = [list(r) for r in rows]
            self.cache[cache_key] = out
            return out

        # 2) If missing and we have a Binance client, backfill a window and upsert
        if self._binance_client is not None:
            interval_ms = self._interval_to_ms(interval)
            # Pull a bit more than limit to be safe
            lookback = limit + 50
            start_time_ms = max(0, end_time_ms - interval_ms * lookback)

            # Many Binance endpoints cap limit; request a reasonable chunk
            req_limit = min(max(200, lookback), 1500)

            try:
                klines = self._binance_client.get_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=req_limit,
                    start_time=start_time_ms,
                    end_time=end_time_ms,
                )
                candles = self._normalize_klines_to_rows(klines)
                if candles:
                    self.store_ohlcv(interval=interval, symbol=symbol, candles=candles)
            except Exception:
                # Network/API error: fall back to what DB has
                pass

        # 3) Re-read from DB after backfill
        rows2 = self._select_from_db(symbol=symbol, interval=interval, limit=limit, end_time_ms=end_time_ms)
        out2 = [list(r) for r in rows2]
        self.cache[cache_key] = out2
        return out2

    def store_ohlcv(self, interval: str, symbol: str, candles: List[List[float]]) -> None:
        """
        Store OHLCV data.

        Args:
            interval: Time interval
            symbol: Trading pair symbol
            candles: List of OHLCV candles [timestamp, open, high, low, close, volume]
        """
        if not candles:
            return

        # Normalize and upsert into SQLite
        payload = []
        for c in candles:
            if not c or len(c) < 6:
                continue
            try:
                ot = int(c[0])
                o = float(c[1])
                h = float(c[2])
                l = float(c[3])
                cl = float(c[4])
                v = float(c[5])
                payload.append((symbol, interval, ot, o, h, l, cl, v))
            except Exception:
                continue

        if not payload:
            return

        self._conn.executemany(
            """
            INSERT OR REPLACE INTO ohlcv
            (symbol, interval, open_time_ms, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            payload,
        )
        self._conn.commit()

        # Update cache too (keep last candles only)
        cache_key = f"{symbol}_{interval}_{len(candles)}"
        self.cache[cache_key] = candles

    # -----------------------
    # Internal helpers
    # -----------------------
    def _select_from_db(
        self, symbol: str, interval: str, limit: int, end_time_ms: int
    ) -> List[Tuple[int, float, float, float, float, float]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT open_time_ms, open, high, low, close, volume
            FROM ohlcv
            WHERE symbol = ? AND interval = ? AND open_time_ms <= ?
            ORDER BY open_time_ms DESC
            LIMIT ?;
            """,
            (symbol, interval, end_time_ms, limit),
        )
        rows = cur.fetchall()
        rows.reverse()  # chronological
        return rows

    def _normalize_klines_to_rows(self, klines: List[List[Any]]) -> List[List[float]]:
        """
        Converts Binance kline format to our storage format:
        [open_time_ms, open, high, low, close, volume]
        """
        out: List[List[float]] = []
        for k in klines or []:
            try:
                ot = int(k[0])
                o = float(k[1])
                h = float(k[2])
                l = float(k[3])
                c = float(k[4])
                v = float(k[5])
                out.append([ot, o, h, l, c, v])
            except Exception:
                continue
        return out

    def _interval_to_ms(self, interval: str) -> int:
        m = interval.strip().lower()
        if m.endswith("m"):
            return int(m[:-1]) * 60_000
        if m.endswith("h"):
            return int(m[:-1]) * 3_600_000
        if m.endswith("d"):
            return int(m[:-1]) * 86_400_000
        if m.endswith("w"):
            return int(m[:-1]) * 7 * 86_400_000
        return 3_600_000  # fallback 1h