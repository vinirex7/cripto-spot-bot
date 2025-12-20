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
    rets: List[float] = []
    for i in range(1, len(closes)):
        p0 = closes[i - 1]
        p1 = closes[i]
        if p0 <= 0 or p1 <= 0:
            continue
        rets.append(math.log(p1 / p0))
    return rets


def _momentum_score_from_closes(closes: List[float], min_sigma: float) -> float:
    """
    Momentum 2.0 canonical:
    M = sum(log_returns) / sample_std(log_returns)
    with sigma clamp to avoid explosion when sigma ~ 0.
    """
    rets = _log_returns_from_closes(closes)
    if len(rets) < 2:
        return 0.0
    sigma = _sample_std(rets)
    if sigma <= 0:
        return 0.0
    if sigma < min_sigma:
        sigma = min_sigma
    return sum(rets) / sigma


def _rolling_momentum_age(
    closes: List[float],
    times_ms: List[int],
    window: int,
    min_sigma: float,
) -> Tuple[float, Optional[int]]:
    """
    Age of momentum sign (>0) based on rolling Momentum 2.0.

    Returns:
      (age_days, start_time_ms_of_positive_run_end)
    Definition:
      - Compute rolling M over 'window' closes ending at each time index i.
      - If last rolling M <= 0 => age = 0, start=None
      - Else walk backward until M <= 0, and the next point is the start of the positive run.
      - start_time_ms corresponds to the END timestamp of the first positive rolling M in the run.
    """
    n = len(closes)
    if n < window or n != len(times_ms):
        return 0.0, None

    # Build rolling scores (end index i corresponds to time times_ms[i])
    end_idxs: List[int] = []
    scores: List[float] = []
    for i in range(window - 1, n):
        w = closes[i - window + 1 : i + 1]
        m = _momentum_score_from_closes(w, min_sigma=min_sigma)
        end_idxs.append(i)
        scores.append(m)

    if not scores:
        return 0.0, None

    # If current momentum (rolling) is not positive => age 0
    if scores[-1] <= 0.0:
        return 0.0, None

    # Walk backward to find the start of the consecutive positive run
    k = len(scores) - 1
    while k >= 0 and scores[k] > 0.0:
        k -= 1

    # start is the next index after the last non-positive
    start_pos = k + 1
    start_end_idx = end_idxs[start_pos]

    t_last = times_ms[end_idxs[-1]]
    t_start = times_ms[start_end_idx]
    age_days = (t_last - t_start) / (1000.0 * 86400.0)

    return float(max(0.0, age_days)), int(t_start)


# -----------------------------
# SQLite fetch
# -----------------------------
def _fetch_closes_sqlite(
    db_path: str,
    symbol: str,
    interval: str,
    limit: int,
) -> Tuple[List[float], List[int]]:
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
    Compute Momentum 2.0 features + corrected gating flags + momentum age (trend age).

    Adds:
      mom_age_6_days, mom_start_6_ms
      mom_age_12_days, mom_start_12_ms
    """

    interval_1d = str(momentum_cfg.get("interval_1d", "1d"))

    # Treat these as BAR COUNTS (LIMIT)
    lookback_6m = int(momentum_cfg.get("lookback_6m_days", 180))
    lookback_12m = int(momentum_cfg.get("lookback_12m_days", 360))

    # Extra bars to estimate "when momentum turned positive" (especially for 12m rolling)
    age_extra_bars = int(momentum_cfg.get("age_extra_bars", 60))

    min_points_6m = int(momentum_cfg.get("min_points_6m", momentum_cfg.get("min_points", 120)))
    min_points_12m = int(momentum_cfg.get("min_points_12m", momentum_cfg.get("min_points", 240)))

    require_m12_positive = bool(momentum_cfg.get("require_m12_positive", False))
    delta_threshold = float(momentum_cfg.get("delta_threshold", 0.0))

    # Sigma clamp for stability
    min_sigma = float(momentum_cfg.get("min_sigma", 1e-12))

    db_path = _discover_db_path(history_store, momentum_cfg)

    # ---- Single fetch: enough for 12m + extra for age detection
    fetch_limit = max(lookback_12m + age_extra_bars, lookback_6m, lookback_12m)
    closes_all, times_all = _fetch_closes_sqlite(db_path, symbol, interval_1d, fetch_limit)

    # Ensure we can compute the current 6m and 12m windows
    if len(closes_all) < lookback_12m or len(closes_all) < lookback_6m:
        return None

    closes_12 = closes_all[-lookback_12m:]
    times_12 = times_all[-lookback_12m:]
    closes_6 = closes_all[-lookback_6m:]
    times_6 = times_all[-lookback_6m:]

    if len(closes_6) < min_points_6m or len(closes_12) < min_points_12m:
        return None

    m_6 = _momentum_score_from_closes(closes_6, min_sigma=min_sigma)
    m_12 = _momentum_score_from_closes(closes_12, min_sigma=min_sigma)
    delta_m = m_6 - m_12

    rets_6 = _log_returns_from_closes(closes_6)
    vol_1d = _sample_std(rets_6) if len(rets_6) >= 2 else 0.0

    # span of data fetched for context (not "trend age")
    window_span_days = 0.0
    if times_all:
        window_span_days = (times_all[-1] - times_all[0]) / (1000.0 * 86400.0)

    # ---- Trend age (when rolling momentum metric turned positive)
    # Only meaningful when current momentum is positive; otherwise age=0.
    mom_age_6_days, mom_start_6_ms = _rolling_momentum_age(
        closes_all, times_all, window=lookback_6m, min_sigma=min_sigma
    )
    mom_age_12_days, mom_start_12_ms = _rolling_momentum_age(
        closes_all, times_all, window=lookback_12m, min_sigma=min_sigma
    )

    # -----------------------------
    # Gates (your corrected logic)
    # -----------------------------
    direction_ok = (m_6 > 0.0)
    if require_m12_positive:
        direction_ok = direction_ok and (m_12 > 0.0)

    acceleration_ok = (delta_m > delta_threshold)
    momentum_ok = direction_ok and acceleration_ok

    return {
        "delta_m": float(delta_m),
        "m_6": float(m_6),
        "m_12": float(m_12),
        "vol_1d": float(vol_1d),
        "direction_ok": bool(direction_ok),
        "acceleration_ok": bool(acceleration_ok),
        "momentum_ok": bool(momentum_ok),

        # Trend age outputs
        "mom_age_6_days": float(mom_age_6_days),
        "mom_start_6_ms": int(mom_start_6_ms) if mom_start_6_ms is not None else None,
        "mom_age_12_days": float(mom_age_12_days),
        "mom_start_12_ms": int(mom_start_12_ms) if mom_start_12_ms is not None else None,

        # Debug/context
        "db_path": str(db_path),
        "interval_1d": interval_1d,
        "n_all": int(len(closes_all)),
        "n_6": int(len(closes_6)),
        "n_12": int(len(closes_12)),
        "window_span_days": float(window_span_days),
        "min_sigma": float(min_sigma),
        "age_extra_bars": int(age_extra_bars),
    }
