"""Momentum signal computation (Momentum 2.0)."""

from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple
import math
import sqlite3
import os


def _sample_std(xs: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


def _log_returns_from_closes(closes: List[float]) -> List[float]:
    # closes must be in chronological order (oldest -> newest)
    rets: List[float] = []
    for i in range(1, len(closes)):
        p0 = closes[i - 1]
        p1 = closes[i]
        if p0 <= 0 or p1 <= 0:
            continue
        rets.append(math.log(p1 / p0))
    return rets


def _momentum_score(closes: List[float]) -> float:
    """
    Momentum 2.0 canonical:
    M = sum(log_returns) / sample_std(log_returns)
    """
    rets = _log_returns_from_closes(closes)
    if len(rets) < 2:
        return 0.0
    sigma = _sample_std(rets)
    if sigma <= 0:
        return 0.0
    return sum(rets) / sigma


def _fetch_closes_sqlite(db_path: str, symbol: str, interval: str, limit: int) -> Tuple[List[float], List[int]]:
    """
    Fetch last `limit` closes and open_time_ms from SQLite.
    Returns closes and times in chronological order (oldest -> newest).
    """
    if not os.path.exists(db_path):
        return [], []

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT close, open_time_ms
            FROM ohlcv
            WHERE symbol=? AND interval=?
            ORDER BY open_time_ms DESC
            LIMIT ?
            """,
            (symbol, interval, int(limit)),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # rows are newest -> oldest; reverse to oldest -> newest
    rows.reverse()
    closes = [float(r[0]) for r in rows]
    times = [int(r[1]) for r in rows]
    return closes, times


def compute_momentum_features(
    history_store: Any,  # kept for compatibility with existing calls, but unused
    symbol: str,
    momentum_cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Compute momentum features for a symbol reading directly from SQLite.

    Required DB table: ohlcv(symbol, interval, open_time_ms, close, ...)

    IMPORTANT:
    - We do NOT rely on `history_store` (it may not exist in this project).
    - DB path comes from momentum_cfg['sqlite_path'] or defaults to './bot.db'.
    - Uses LIMIT-based retrieval to avoid timezone/window bugs.
    """

    # Config defaults
    interval_1d = str(momentum_cfg.get("interval_1d", "1d"))

    # How many daily candles to pull (days ~= candles for 1d)
    lookback_6m_days = int(momentum_cfg.get("lookback_6m_days", 180))
    lookback_12m_days = int(momentum_cfg.get("lookback_12m_days", 360))

    # Minimum points required to compute stable sigma
    min_points = int(momentum_cfg.get("min_points", 60))

    # DB path: only from config (no history_store)
    db_path = str(momentum_cfg.get("sqlite_path", "./bot.db"))

    closes_6, times_6 = _fetch_closes_sqlite(db_path, symbol, interval_1d, lookback_6m_days)
    closes_12, times_12 = _fetch_closes_sqlite(db_path, symbol, interval_1d, lookback_12m_days)

    # Data sufficiency checks
    if len(closes_6) < min_points or len(closes_12) < min_points:
        return None

    m_6 = _momentum_score(closes_6)
    m_12 = _momentum_score(closes_12)
    delta_m = m_6 - m_12

    # vol_1d = sample std of daily log returns over 6m window
    rets_6 = _log_returns_from_closes(closes_6)
    vol_1d = _sample_std(rets_6) if len(rets_6) >= 2 else 0.0

    # m_age: span in days covered by the 12m window (proxy)
    m_age = 0.0
    if times_12:
        m_age = (times_12[-1] - times_12[0]) / (1000 * 86400)

    return {
        "m_age": float(m_age),
        "delta_m": float(delta_m),
        "m_6": float(m_6),
        "m_12": float(m_12),
        "vol_1d": float(vol_1d),
    }