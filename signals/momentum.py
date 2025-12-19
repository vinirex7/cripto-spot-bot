"""Momentum signal computation (Momentum 2.0) — corrected gates.

Key fixes:
- Delta (acceleration) NEVER authorizes BUY by itself.
- Hard direction gate: if m_6 <= 0 => momentum_ok = False.
- Optional stricter gate: require m_12 > 0 too (config).
- Reads closes from SQLite ohlcv table and computes:
  m_6, m_12, delta_m, vol_1d, m_age_days.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple
import math
import sqlite3
import os


# -----------------------------
# Helpers: stats + returns
# -----------------------------
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


def _momentum_score_from_closes(closes: List[float]) -> float:
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


# -----------------------------
# SQLite fetch
# -----------------------------
def _fetch_closes_sqlite(
    db_path: str,
    symbol: str,
    interval: str,
    limit: int,
) -> Tuple[List[float], List[int]]:
    """
    Fetch last `limit` closes and open_time_ms from SQLite.
    Returns closes and times in chronological order (oldest -> newest).
    """
    if not db_path or not os.path.exists(db_path):
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

    closes: List[float] = []
    times: List[int] = []
    for c, t in rows:
        try:
            closes.append(float(c))
            times.append(int(t))
        except Exception:
            continue

    return closes, times


def _discover_db_path(history_store: Any, momentum_cfg: Dict[str, Any]) -> str:
    """
    Tries multiple places to discover sqlite path.
    Priority:
      1) momentum_cfg["sqlite_path"]
      2) history_store.config["storage"]["sqlite_path"]
      3) ./bot.db
    """
    db_path = momentum_cfg.get("sqlite_path")
    if db_path:
        return str(db_path)

    try:
        cfg = getattr(history_store, "config", None)
        if isinstance(cfg, dict):
            p = cfg.get("storage", {}).get("sqlite_path")
            if p:
                return str(p)
    except Exception:
        pass

    return "./bot.db"


# -----------------------------
# Public API
# -----------------------------
def compute_momentum_features(
    history_store: Any,
    symbol: str,
    momentum_cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Compute Momentum 2.0 features + corrected gating flags.

    Returns dict with:
      m_6, m_12, delta_m, vol_1d, m_age (days),
      direction_ok, acceleration_ok, momentum_ok
    or None if insufficient data.
    """

    # ---- Config defaults
    interval_1d = str(momentum_cfg.get("interval_1d", "1d"))

    # Use "days" as bar count for 1d candles (limit-based, robust)
    lookback_6m_days = int(momentum_cfg.get("lookback_6m_days", 180))
    lookback_12m_days = int(momentum_cfg.get("lookback_12m_days", 360))

    # Minimum closes required for each window
    min_points_6m = int(momentum_cfg.get("min_points_6m", momentum_cfg.get("min_points", 120)))
    min_points_12m = int(momentum_cfg.get("min_points_12m", momentum_cfg.get("min_points", 240)))

    # Gates / thresholds
    require_m12_positive = bool(momentum_cfg.get("require_m12_positive", False))
    delta_threshold = float(momentum_cfg.get("delta_threshold", 0.0))  # allow >0 by default

    # ---- Discover DB and fetch closes
    db_path = _discover_db_path(history_store, momentum_cfg)

    closes_6, times_6 = _fetch_closes_sqlite(db_path, symbol, interval_1d, lookback_6m_days)
    closes_12, times_12 = _fetch_closes_sqlite(db_path, symbol, interval_1d, lookback_12m_days)

    # ---- Data sufficiency
    if len(closes_6) < min_points_6m or len(closes_12) < min_points_12m:
        return None

    # ---- Scores
    m_6 = _momentum_score_from_closes(closes_6)
    m_12 = _momentum_score_from_closes(closes_12)
    delta_m = m_6 - m_12

    # ---- vol_1d = sample std of daily log returns over 6m window
    rets_6 = _log_returns_from_closes(closes_6)
    vol_1d = _sample_std(rets_6) if len(rets_6) >= 2 else 0.0

    # ---- m_age: span (days) covered by the 12m window (proxy)
    m_age = 0.0
    if times_12:
        m_age = (times_12[-1] - times_12[0]) / (1000.0 * 86400.0)

    # -----------------------------
    # Corrected gates (IMPORTANT)
    # -----------------------------
    # Hard direction gate: MUST be positive trend on 6m to even consider BUY.
    direction_ok = (m_6 > 0.0)

    # Optional stricter: also require m_12 > 0
    if require_m12_positive:
        direction_ok = direction_ok and (m_12 > 0.0)

    # Acceleration is secondary (quality), never primary
    acceleration_ok = (delta_m > delta_threshold)

    # Final momentum_ok: direction gate FIRST, then acceleration
    momentum_ok = direction_ok and acceleration_ok

    return {
        "m_age": float(m_age),
        "delta_m": float(delta_m),
        "m_6": float(m_6),
        "m_12": float(m_12),
        "vol_1d": float(vol_1d),
        "direction_ok": bool(direction_ok),
        "acceleration_ok": bool(acceleration_ok),
        "momentum_ok": bool(momentum_ok),
        "db_path": str(db_path),
        "interval_1d": interval_1d,
        "n_6": int(len(closes_6)),
        "n_12": int(len(closes_12)),
    }