from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Deque, Dict, Tuple

import numpy as np
import pandas as pd


@dataclass
class NewsShockState:
    ns_score: float
    sent_z: float
    price_shock_z: float
    vol_spike: float
    hard: bool
    soft: bool
    risk_on: bool


class NewsShockEngine:
    def __init__(self, config):
        self.config = config
        self.vol_history: Dict[str, Deque] = defaultdict(lambda: deque(maxlen=24 * 30))

    def price_shock_metrics(self, symbol: str, price_window: pd.DataFrame) -> Tuple[float, float]:
        if price_window.empty or "close" not in price_window:
            return 0.0, 1.0
        prices = price_window["close"]
        returns = np.log(prices / prices.shift(1)).dropna()
        if returns.empty:
            return 0.0, 1.0
        start_price = prices.iloc[0]
        if start_price == 0:
            return 0.0, 1.0

        ret_1h = float((prices.iloc[-1] / start_price) - 1)
        vol_1h = float(returns.ewm(alpha=0.2).std().iloc[-1]) if len(returns) > 1 else float(returns.std(ddof=1))
        vol_1h = max(vol_1h, 1e-6)

        self.vol_history[symbol].append(vol_1h)
        vol_baseline = list(self.vol_history[symbol]) or [vol_1h]
        vol_spike = vol_1h / max(np.median(vol_baseline), 1e-6)

        price_shock_z = ret_1h / vol_1h
        return float(price_shock_z), float(vol_spike)

    def evaluate(self, sent_z: float, price_shock_z: float, vol_spike: float) -> NewsShockState:
        ns_score = 0.6 * sent_z - 0.4 * price_shock_z
        cfg = self.config.get("news", {})

        hard = bool(
            sent_z <= cfg.get("sentz_hard", -3.0)
            or price_shock_z <= cfg.get("priceshockz_hard", -3.0)
            or (ns_score <= cfg.get("ns_hard", -2.5) and vol_spike >= cfg.get("volspike_hard", 1.8))
        )

        soft = bool(
            (cfg.get("ns_soft", -1.5) < ns_score <= cfg.get("ns_hard", -2.5))
            or vol_spike >= cfg.get("volspike_soft", 1.5)
        )

        risk_on = bool(sent_z >= 2.0 and price_shock_z >= 1.0)

        return NewsShockState(
            ns_score=ns_score,
            sent_z=sent_z,
            price_shock_z=price_shock_z,
            vol_spike=vol_spike,
            hard=hard,
            soft=soft,
            risk_on=risk_on,
        )
