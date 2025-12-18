import math
import random
from typing import Any, Dict, List, Optional

import numpy as np

from data.history_store import HistoryStore


def _age_discount(months: float) -> float:
    if months <= 12:
        return 1.0
    if months <= 15:
        return 0.75
    if months <= 18:
        return 0.50
    return 0.25


def _momentum(series: List[float]) -> Optional[float]:
    if len(series) < 2:
        return None
    rets = np.diff(np.log(np.array(series)))
    sigma = np.std(rets, ddof=1)
    if sigma == 0:
        return None
    return float(np.sum(rets) / sigma)


def _bootstrap_pwin(rets: np.ndarray, n_resamples: int, block: int) -> float:
    if len(rets) == 0:
        return 0.0
    wins = 0
    for _ in range(n_resamples):
        idx = np.random.randint(0, len(rets), size=max(1, block))
        resample = rets[idx]
        sigma = np.std(resample, ddof=1) if len(resample) > 1 else 0
        m = np.sum(resample) / sigma if sigma else 0
        if m > 0:
            wins += 1
    return wins / n_resamples


def compute_momentum_features(
    history_store: HistoryStore, symbol: str, cfg: Dict[str, Any]
) -> Optional[Dict[str, float]]:
    long_days = int(cfg.get("lookback_months_long", 12) * 30)
    short_days = int(cfg.get("lookback_months_short", 6) * 30)
    rows = history_store.fetch_ohlcv("1d", symbol, limit=long_days + 2)
    if len(rows) < long_days:
        return None
    closes = [r[1] for r in rows]
    m12 = _momentum(closes[-long_days:])
    m6 = _momentum(closes[-short_days:])
    if m12 is None or m6 is None:
        return None
    delta_m = m6 - m12
    months_age = (len(closes) - 1) / 30.0
    m_age = m12 * _age_discount(months_age)
    bootstrap_cfg = cfg.get("bootstrap", {})
    pwin_mom = 0.0
    if bootstrap_cfg.get("enabled", False):
        rets = np.diff(np.log(np.array(closes[-long_days:])))
        pwin_mom = _bootstrap_pwin(
            rets,
            bootstrap_cfg.get("n_resamples", 300),
            max(1, int(bootstrap_cfg.get("block_size_days", 7))),
        )
    return {
        "m6": float(m6),
        "m12": float(m12),
        "delta_m": float(delta_m),
        "m_age": float(m_age),
        "pwin_mom": float(pwin_mom),
    }
