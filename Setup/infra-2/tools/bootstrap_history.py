from __future__ import annotations

import os
import sys
import time
import sqlite3
from typing import Any, Dict, List, Optional

import yaml

from execution.binance_client import BinanceSpotClient


def parse_days(s: str) -> int:
    s = str(s).strip().lower()
    if s.isdigit():
        return int(s)
    if s.endswith("d"):
        return int(s[:-1])
    raise ValueError(f"Invalid days format: {s}")


def parse_interval_ms(interval: str) -> int:
    """Convert Binance interval string to milliseconds."""
    s = interval.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60_000
    if s.endswith("h"):
        return int(s[:-1]) * 3_600_000
    if s.endswith("d"):
        return int(s[:-1]) * 86_400_000
    raise ValueError(f"Unsupported interval: {interval}")


def normalize_klines(klines: List[List[Any]]) -> List[List[float]]:
    out: List[List[float]] = []
    for k in klines or []:
        try:
            out.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
        except Exception:
            continue
    return out


def get_latest_open_time(conn: sqlite3.Connection, symbol: str, interval: str) -> Optional[int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT MAX(open_time_ms) FROM ohlcv WHERE symbol=? AND interval=?;",
        (symbol, interval),
    )
    row = cur.fetchone()
    if not row:
        return None
    v = row[0]
    return int(v) if v is not None else None


def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_interval_time ON ohlcv(symbol, interval, open_time_ms);")
    conn.commit()


def upsert(conn: sqlite3.Connection, symbol: str, interval: str, rows: List[List[float]]) -> int:
    if not rows:
        return 0
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT OR REPLACE INTO ohlcv
        (symbol, interval, open_time_ms, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        [(symbol, interval, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows],
    )
    conn.commit()
    return len(rows)


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def make_client(cfg: Dict[str, Any]) -> BinanceSpotClient:
    keys = (cfg.get("api_keys", {}) or {}).get("binance", {}) or {}
    api_key = (keys.get("api_key") or os.getenv("BINANCE_API_KEY") or "").strip()
    api_secret = (keys.get("api_secret") or os.getenv("BINANCE_API_SECRET") or "").strip()
    binance_cfg = cfg.get("binance", {}) or {}
    return BinanceSpotClient(api_key=api_key, api_secret=api_secret, config=binance_cfg)


def universe(cfg: Dict[str, Any]) -> List[str]:
    u = cfg.get("universe")
    if isinstance(u, list) and u:
        return [str(x).strip().upper() for x in u if str(x).strip()]
    # fallback common place
    u2 = (cfg.get("bot", {}) or {}).get("universe")
    if isinstance(u2, list) and u2:
        return [str(x).strip().upper() for x in u2 if str(x).strip()]
    return ["BTCUSDT", "ETHUSDT"]


def get_sqlite_path(cfg: Dict[str, Any]) -> str:
    # Prefer storage.sqlite_path; fallback to ./data/marketdata.sqlite
    storage = cfg.get("storage", {}) or {}
    p = storage.get("sqlite_path") or "./data/marketdata.sqlite"
    return str(p)


def backfill_symbol(
    client: BinanceSpotClient,
    conn: sqlite3.Connection,
    symbol: str,
    interval: str,
    lookback_days: int,
) -> int:
    ms = parse_interval_ms(interval)
    now_ms = int(time.time() * 1000)

    existing_latest = get_latest_open_time(conn, symbol, interval)
    if existing_latest is None:
        # full backfill
        start_ms = now_ms - (lookback_days * 86_400_000)
    else:
        # incremental: start right after last stored candle
        start_ms = existing_latest + ms

    max_per_call = 1000
    total = 0
    # Loop pulling until "now"
    while start_ms < now_ms:
        klines = client._request(
            method="GET",
            endpoint="/api/v3/klines",
            signed=False,
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": max_per_call,
                "startTime": start_ms,
                "endTime": now_ms,
            },
        )
        rows = normalize_klines(klines)
        if not rows:
            break

        total += upsert(conn, symbol, interval, rows)

        # advance start_ms to last candle + interval
        last_timestamp = int(rows[-1][0])
        new_start_ms = last_timestamp + ms

        # Safety: if API returns same last timestamp, avoid infinite loop
        if new_start_ms <= start_ms:
            break

        start_ms = new_start_ms

    return total


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 tools/bootstrap_history.py <config.yaml>")
        return 2

    cfg_path = sys.argv[1]
    cfg = load_config(cfg_path)

    sqlite_path = get_sqlite_path(cfg)
    os.makedirs(os.path.dirname(sqlite_path) or ".", exist_ok=True)

    print(f"DB: {sqlite_path}")

    u = universe(cfg)
    print(f"Universe: {u}")

    # Defaults from config, with safe fallbacks
    mom_cfg = cfg.get("momentum", {}) or {}
    lookback_1d_days = int(mom_cfg.get("lookback_days_1d", 420) or 420)
    lookback_1h_days = int(mom_cfg.get("lookback_days_1h", 180) or 180)

    print(f"Backfill: 1d={lookback_1d_days} days | 1h={lookback_1h_days} days")

    client = make_client(cfg)
    conn = sqlite3.connect(sqlite_path)
    try:
        ensure_schema(conn)

        for sym in u:
            print(f"\n== {sym} ==")
            n1 = backfill_symbol(client, conn, sym, "1d", lookback_1d_days)
            print(f"[1d] upserted={n1}")
            n2 = backfill_symbol(client, conn, sym, "1h", lookback_1h_days)
            print(f"[1h] upserted={n2}")

        print("\nDONE")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
