import math
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd


@dataclass
class MomentumResult:
    m6: float
    m12: float
    delta_m: float
    vol_1d: float
    long_bias: bool
    risk_off: bool
    cumulative_return: float
    age_factor: float


def _log_returns(prices: pd.Series) -> pd.Series:
    return np.log(prices / prices.shift(1)).dropna()


def _sample_vol(returns: pd.Series) -> float:
    if returns.empty or returns.std(ddof=1) == 0 or math.isnan(returns.std(ddof=1)):
        return 0.0
    return float(returns.std(ddof=1))


def _momentum_score(returns: pd.Series) -> float:
    vol = _sample_vol(returns)
    if vol == 0:
        return 0.0
    return float(returns.sum() / vol)


def _age_discount(days: int, buckets) -> float:
    for bucket in buckets:
        if days <= bucket.get("max_days", 0):
            return float(bucket.get("factor", 1.0))
    return 1.0


def compute_momentum_signals(prices: pd.Series, config: Dict) -> MomentumResult:
    """
    Canonical Momentum 2.0 implementation.
    M6 = sum r_t / sigma over last 6 months (~182d)
    M12 = sum r_t / sigma over last 12 months (~365d)
    Acceleration = M6 - M12
    Age discount applied to momentum score.
    Fallback to time-series momentum (sign of cumulative return).
    """
    n_short = int(config.get("n_days_short", 182))
    n_long = int(config.get("n_days_long", 365))
    buckets = config.get("age_days_buckets", [])

    prices = prices.dropna()
    age_days = len(prices)
    age_factor = _age_discount(age_days, buckets)

    ret_all = _log_returns(prices)
    vol_1d = float(ret_all.std(ddof=1)) if not ret_all.empty else 0.0

    short_returns = _log_returns(prices.tail(n_short))
    long_returns = _log_returns(prices.tail(n_long))

    m6_raw = _momentum_score(short_returns)
    m12_raw = _momentum_score(long_returns)

    m6 = m6_raw * age_factor
    m12 = m12_raw * age_factor
    delta_m = m6 - m12

    cumulative_return = float((prices.iloc[-1] / prices.iloc[0]) - 1) if len(prices) > 1 else 0.0

    long_bias = m12 > 0 and m6 > 0 and delta_m > 0
    risk_off = m6 < 0 and m12 < 0

    # Fallback time-series momentum if vols collapse
    if not long_bias and (m6 == 0 or m12 == 0):
        long_bias = cumulative_return > 0

    return MomentumResult(
        m6=m6,
        m12=m12,
        delta_m=delta_m,
        vol_1d=vol_1d if vol_1d > 0 else max(abs(m6_raw), abs(m12_raw), 1e-6),
        long_bias=long_bias,
        risk_off=risk_off,
        cumulative_return=cumulative_return,
        age_factor=age_factor,
    )
