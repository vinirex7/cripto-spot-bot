# signals/momentum.py
from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple
import math
import sqlite3
import os


# ============================================================
# Helpers: stats + returns
# ============================================================
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
    if sigma <= 0.0:
        return 0.0
    if sigma < min_sigma:
        sigma = min_sigma
    return float(sum(rets) / sigma)


def _days_to_months(days: float) -> float:
    # Mean tropical month ~ 30.4375 days (good enough for gating)
    return float(days) / 30.4375


# ============================================================
# Rolling momentum + confirmed momentum age (Mage)
# ============================================================
def _rolling_momentum_scores(
    closes: List[float],
    times_ms: List[int],
    window: int,
    min_sigma: float,
) -> Tuple[List[float], List[int]]:
    """
    Rolling Momentum 2.0 scores over a window.

    Returns:
      scores: rolling momentum score M
      end_idxs: indices in closes/times corresponding to each score's end point
    """
    n = len(closes)
    if n < window or n != len(times_ms):
        return [], []

    scores: List[float] = []
    end_idxs: List[int] = []
    for i in range(window - 1, n):
        w = closes[i - window + 1 : i + 1]
        scores.append(_momentum_score_from_closes(w, min_sigma=min_sigma))
        end_idxs.append(i)
    return scores, end_idxs


def _rolling_momentum_age_confirmed(
    closes: List[float],
    times_ms: List[int],
    window: int,
    min_sigma: float,
    confirm_bars: int,
) -> Tuple[float, Optional[int], Optional[float]]:
    """
    Age of the CURRENT positive momentum cycle (Mage), based on rolling Momentum 2.0.

    Confirm logic:
      - If last rolling M <= 0 => no active cycle => age=0
      - Else require last `confirm_bars` rolling scores to all be > 0 (noise guard)
      - Walk backward until last non-positive score; cycle start is next positive score
      - start_time_ms is END timestamp of the first positive rolling score in the run

    Returns:
      (age_days, start_time_ms, last_score)
    """
    scores, end_idxs = _rolling_momentum_scores(closes, times_ms, window, min_sigma)
    if not scores:
        return 0.0, None, None

    last_score = float(scores[-1])
    if last_score <= 0.0:
        return 0.0, None, last_score

    cb = max(1, int(confirm_bars))
    if len(scores) < cb:
        return 0.0, None, last_score
    if any(s <= 0.0 for s in scores[-cb:]):
        return 0.0, None, last_score

    k = len(scores) - 1
    while k >= 0 and scores[k] > 0.0:
        k -= 1

    start_pos = k + 1
    start_end_idx = end_idxs[start_pos]

    t_last = times_ms[end_idxs[-1]]
    t_start = times_ms[start_end_idx]
    age_days = (t_last - t_start) / (1000.0 * 86400.0)

    return float(max(0.0, age_days)), int(t_start), last_score


# ============================================================
# SQLite fetch (FORÇA TABELA ohlcv — compatível com seu banco)
# ============================================================
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


# ============================================================
# Robust path discovery
# ============================================================
def _discover_db_path(history_store: Any, cfg: Dict[str, Any], momentum_cfg: Dict[str, Any]) -> str:
    """
    Priority:
      1) momentum.sqlite_path (legacy)
      2) storage.sqlite_path (official)
      3) history_store.sqlite_path (if present)
      4) history_store.config['storage']['sqlite_path'] (if present)
      5) ./data/marketdata.sqlite (safe fallback)
    """
    p = momentum_cfg.get("sqlite_path")
    if p:
        return str(p)

    storage = (cfg.get("storage", {}) or {})
    p2 = storage.get("sqlite_path")
    if p2:
        return str(p2)

    try:
        p_hs = getattr(history_store, "sqlite_path", None)
        if p_hs:
            return str(p_hs)
    except Exception:
        pass

    try:
        hs_cfg = getattr(history_store, "config", None)
        if isinstance(hs_cfg, dict):
            p3 = (hs_cfg.get("storage", {}) or {}).get("sqlite_path")
            if p3:
                return str(p3)
    except Exception:
        pass

    return "./data/marketdata.sqlite"


# ============================================================
# Regime logic (Vini rule)
# ============================================================
def _get_weight_mult(momentum_cfg: Dict[str, Any], regime: str) -> float:
    """
    momentum:
      weight_mult:
        normal: 1.0
        early_reversal: 0.5
        aging: 0.6
        too_old: 0.0
        blocked: 0.0
    """
    wm = momentum_cfg.get("weight_mult", {}) or {}
    # allow also nested config like momentum_cfg["weight_mult"]["normal"]
    default_map = {
        "normal": 1.0,
        "early_reversal": 0.5,
        "aging": 0.6,
        "too_old": 0.0,
        "blocked": 0.0,
    }
    try:
        v = wm.get(regime, default_map.get(regime, 0.0))
        return float(v)
    except Exception:
        return float(default_map.get(regime, 0.0))


def _classify_regime(
    m6: float,
    m12: float,
    delta_m: float,
    mage_months: Optional[float],
    momentum_cfg: Dict[str, Any],
) -> Tuple[str, bool, float, List[str]]:
    """
    Implements your official rule:

    1) Early reversal:
       m6>0 and m12<0 and delta_m > early_delta_threshold  => enter (smaller weight)
       IMPORTANT: early reversal does NOT depend on Mage.

    2) Normal:
       m6>0 and m12>0 and delta_m>0 and mage_months<=12 => enter (normal weight)

    3) Aging:
       m6>0 and m12>0 and delta_m>0 and 12<mage_months<=15 => enter (smaller weight)

    4) Too old:
       mage_months>15 => usually block (weight 0 by default)

    Otherwise: blocked.
    """
    reasons: List[str] = []

    early_delta_threshold = float(momentum_cfg.get("early_delta_threshold", 0.0))
    max_age_months_normal = float(momentum_cfg.get("max_age_months_normal", 12.0))
    max_age_months_aging = float(momentum_cfg.get("max_age_months_aging", 15.0))

    # Hard direction gate for ANY entry regime: m6 must be positive.
    if not (m6 > 0.0):
        reasons.append("direction_block: m6<=0")
        return "blocked", False, _get_weight_mult(momentum_cfg, "blocked"), reasons

    # Early reversal (Mage-independent)
    if (m12 < 0.0) and (delta_m > early_delta_threshold):
        reasons.append(f"early_reversal: m6>0,m12<0,delta>{early_delta_threshold}")
        w = _get_weight_mult(momentum_cfg, "early_reversal")
        return "early_reversal", True, w, reasons

    # For the remaining regimes we require m12>0 and delta>0
    if not (m12 > 0.0):
        reasons.append("blocked: m12<=0 (not early reversal)")
        return "blocked", False, _get_weight_mult(momentum_cfg, "blocked"), reasons

    if not (delta_m > 0.0):
        reasons.append("blocked: delta_m<=0")
        return "blocked", False, _get_weight_mult(momentum_cfg, "blocked"), reasons

    # Need Mage for age-based regimes. If unknown, do NOT enter.
    if mage_months is None:
        reasons.append("blocked: mage_unknown")
        return "blocked", False, _get_weight_mult(momentum_cfg, "blocked"), reasons

    if mage_months <= max_age_months_normal:
        reasons.append(f"normal: mage<= {max_age_months_normal}")
        w = _get_weight_mult(momentum_cfg, "normal")
        return "normal", True, w, reasons

    if (mage_months > max_age_months_normal) and (mage_months <= max_age_months_aging):
        reasons.append(f"aging: {max_age_months_normal}<mage<= {max_age_months_aging}")
        w = _get_weight_mult(momentum_cfg, "aging")
        return "aging", True, w, reasons

    # Too old
    reasons.append(f"too_old: mage>{max_age_months_aging}")
    w = _get_weight_mult(momentum_cfg, "too_old")
    # by default, too_old blocks (weight=0). If user sets weight>0, it becomes "rarely enters" mechanically.
    entry_ok = w > 0.0
    return "too_old", entry_ok, w, reasons


# ============================================================
# Public API
# ============================================================
def compute_momentum_features(
    history_store: Any,
    symbol: str,
    momentum_cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Momentum 2.0 + Mage + regime classification (Vini rule), compatible with your SQLite schema:

      - table: ohlcv (single)
      - uses interval='1d' for momentum (daily candles)

    Returns a dict with:
      - m_6, m_12, delta_m, vol_1d
      - mom_age_days, mage_months, mom_start_ms, mom_age_source
      - rolling_m6_last, rolling_m12_last (audit)
      - momentum_regime, momentum_entry_ok, momentum_weight_mult, regime_reasons
      - debug fields (db_path, counts, etc.)
    """

    # history_store may carry config; if not, keep empty
    cfg = getattr(history_store, "config", None)
    if not isinstance(cfg, dict):
        cfg = {}

    # interval (Momentum uses daily candles)
    interval_1d = str(momentum_cfg.get("interval_1d", "1d")).strip() or "1d"

    # Lookbacks
    lookback_6m = int(momentum_cfg.get("lookback_6m_days", momentum_cfg.get("window_6m_days", 180)))
    lookback_12m = int(momentum_cfg.get("lookback_12m_days", momentum_cfg.get("window_12m_days", 360)))

    # extra bars for age detection (rolling needs enough history to find cycle start)
    age_extra_bars = int(momentum_cfg.get("age_extra_bars", 800))

    # confirmation against noise
    age_confirm_bars = int(momentum_cfg.get("age_confirm_bars", 5))

    # minimum points to compute stable signals
    min_points_6m = int(momentum_cfg.get("min_points_6m", momentum_cfg.get("min_points", 120)))
    min_points_12m = int(momentum_cfg.get("min_points_12m", momentum_cfg.get("min_points", 240)))

    # sigma clamp for stability
    min_sigma = float(momentum_cfg.get("min_sigma", 1e-12))

    # discover DB path robustly
    db_path = _discover_db_path(history_store, cfg, momentum_cfg)

    # ---- Single fetch: enough for 12m + extra for age detection
    fetch_limit = max(lookback_12m + age_extra_bars, lookback_6m, lookback_12m)
    closes_all, times_all = _fetch_closes_sqlite(db_path, symbol, interval_1d, fetch_limit)

    if len(closes_all) < lookback_12m or len(closes_all) < lookback_6m:
        return None

    closes_12 = closes_all[-lookback_12m:]
    closes_6 = closes_all[-lookback_6m:]

    if len(closes_6) < min_points_6m or len(closes_12) < min_points_12m:
        return None

    # canonical scores
    m_6 = _momentum_score_from_closes(closes_6, min_sigma=min_sigma)
    m_12 = _momentum_score_from_closes(closes_12, min_sigma=min_sigma)
    delta_m = m_6 - m_12

    # vol proxy from 6m returns
    rets_6 = _log_returns_from_closes(closes_6)
    vol_1d = _sample_std(rets_6) if len(rets_6) >= 2 else 0.0

    # -----------------------------
    # Mage (Momentum Age) — rolling M12 preferred, fallback to rolling M6
    # -----------------------------
    age_12_days, start_12_ms, last_12 = _rolling_momentum_age_confirmed(
        closes_all, times_all, window=lookback_12m, min_sigma=min_sigma, confirm_bars=age_confirm_bars
    )
    age_6_days, start_6_ms, last_6 = _rolling_momentum_age_confirmed(
        closes_all, times_all, window=lookback_6m, min_sigma=min_sigma, confirm_bars=age_confirm_bars
    )

    mom_age_days: float = 0.0
    mom_start_ms: Optional[int] = None
    mom_age_source: str = "none"

    # IMPORTANT: do not force Mage existence as a hard gate for EARLY REVERSAL.
    # Still, we compute it and expose it to logs.
    if m_6 <= 0.0:
        mom_age_days, mom_start_ms, mom_age_source = 0.0, None, "none"
    else:
        if age_12_days > 0.0 and start_12_ms is not None:
            mom_age_days, mom_start_ms, mom_age_source = float(age_12_days), int(start_12_ms), "m12"
        elif age_6_days > 0.0 and start_6_ms is not None:
            mom_age_days, mom_start_ms, mom_age_source = float(age_6_days), int(start_6_ms), "m6"
        else:
            mom_age_days, mom_start_ms, mom_age_source = 0.0, None, "none"

    # Mage in months: if mom_age_source is none, treat as unknown for age-based regimes.
    mage_months: Optional[float]
    if mom_age_source == "none":
        mage_months = None
    else:
        mage_months = _days_to_months(mom_age_days)

    # -----------------------------
    # Regime classification (your official rule)
    # -----------------------------
    momentum_regime, momentum_entry_ok, momentum_weight_mult, regime_reasons = _classify_regime(
        m6=float(m_6),
        m12=float(m_12),
        delta_m=float(delta_m),
        mage_months=mage_months,
        momentum_cfg=momentum_cfg,
    )

    # For logs/debug: how much history span we loaded
    window_span_days = 0.0
    if times_all:
        window_span_days = (times_all[-1] - times_all[0]) / (1000.0 * 86400.0)

    return {
        # Core signal
        "m_6": float(m_6),
        "m_12": float(m_12),
        "delta_m": float(delta_m),
        "vol_1d": float(vol_1d),

        # Mage outputs
        "mom_age_days": float(mom_age_days),
        "mage_months": float(mage_months) if mage_months is not None else None,
        "mom_start_ms": int(mom_start_ms) if mom_start_ms is not None else None,
        "mom_age_source": str(mom_age_source),

        # Rolling audit
        "rolling_m6_last": float(last_6) if last_6 is not None else None,
        "rolling_m12_last": float(last_12) if last_12 is not None else None,
        "mom_age_6_days": float(age_6_days),
        "mom_start_6_ms": int(start_6_ms) if start_6_ms is not None else None,
        "mom_age_12_days": float(age_12_days),
        "mom_start_12_ms": int(start_12_ms) if start_12_ms is not None else None,

        # Regime outputs (ENGINE SHOULD USE THESE)
        "momentum_regime": str(momentum_regime),
        "momentum_entry_ok": bool(momentum_entry_ok),
        "momentum_weight_mult": float(momentum_weight_mult),
        "regime_reasons": list(regime_reasons),

        # Debug/context
        "db_path": str(db_path),
        "table": "ohlcv",
        "interval_1d": str(interval_1d),
        "n_all": int(len(closes_all)),
        "n_6": int(len(closes_6)),
        "n_12": int(len(closes_12)),
        "window_span_days": float(window_span_days),
        "min_sigma": float(min_sigma),
        "age_extra_bars": int(age_extra_bars),
        "age_confirm_bars": int(age_confirm_bars),

        # Echo key thresholds for audit
        "early_delta_threshold": float(momentum_cfg.get("early_delta_threshold", 0.0)),
        "max_age_months_normal": float(momentum_cfg.get("max_age_months_normal", 12.0)),
        "max_age_months_aging": float(momentum_cfg.get("max_age_months_aging", 15.0)),
        "weight_mult_cfg": dict(momentum_cfg.get("weight_mult", {}) or {}),
    }
