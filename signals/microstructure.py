from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


FALLBACK_VOLUME_SERIES = pd.Series([1.0, 1.0])


@dataclass
class MicrostructureResult:
    entry_allowed: bool
    ofi_z: float
    vwap_1h: float
    illiq: float
    size_multiplier: float
    last_price: float


class MicrostructureAnalyzer:
    def __init__(self, config: Dict):
        self.config = config
        self.ofi_history: Dict[str, Deque] = {}
        self.last_book: Dict[str, Dict] = {}
        self.illiq_history: Dict[str, Deque] = {}

    def _zscore(self, values: List[float]) -> float:
        if not values:
            return 0.0
        series = pd.Series(values)
        if series.std(ddof=1) == 0 or np.isnan(series.std(ddof=1)):
            return 0.0
        return float((series.iloc[-1] - series.mean()) / series.std(ddof=1))

    def _compute_ofi(self, symbol: str, book_ticker: Dict) -> float:
        """
        Order Flow Imbalance proxy using changes in best bid/ask price and size.
        """
        prev = self.last_book.get(symbol)
        self.last_book[symbol] = book_ticker
        if not prev:
            return 0.0

        ofi = 0.0
        bid_price = float(book_ticker.get("bidPrice", 0))
        ask_price = float(book_ticker.get("askPrice", 0))
        bid_qty = float(book_ticker.get("bidQty", 0))
        ask_qty = float(book_ticker.get("askQty", 0))

        prev_bid_price = float(prev.get("bidPrice", 0))
        prev_ask_price = float(prev.get("askPrice", 0))
        prev_bid_qty = float(prev.get("bidQty", 0))
        prev_ask_qty = float(prev.get("askQty", 0))

        if bid_price > prev_bid_price:
            ofi += bid_qty
        elif bid_price == prev_bid_price:
            ofi += bid_qty - prev_bid_qty

        if ask_price < prev_ask_price:
            ofi -= ask_qty
        elif ask_price == prev_ask_price:
            ofi -= (ask_qty - prev_ask_qty)

        return ofi

    def _update_history(self, container: Dict[str, Deque], symbol: str, value: float, horizon_hours: int = 24):
        if symbol not in container:
            container[symbol] = deque()
        container[symbol].append((datetime.utcnow(), value))
        cutoff = datetime.utcnow() - timedelta(hours=horizon_hours)
        while container[symbol] and container[symbol][0][0] < cutoff:
            container[symbol].popleft()

    def _ofi_z(self, symbol: str, book_ticker: Dict) -> float:
        ofi = self._compute_ofi(symbol, book_ticker)
        self._update_history(self.ofi_history, symbol, ofi, horizon_hours=24)
        history_values = [v for _, v in self.ofi_history.get(symbol, [])]
        return self._zscore(history_values)

    @staticmethod
    def _vwap(window: pd.DataFrame) -> float:
        if window.empty or "close" not in window or "volume" not in window:
            return 0.0
        prices = window["close"]
        volume = window["volume"]
        denom = volume.sum()
        if denom == 0:
            return float(prices.iloc[-1])
        return float((prices * volume).sum() / denom)

    def _illiq_guard(self, symbol: str, prices: pd.Series, volumes: pd.Series) -> Tuple[float, float]:
        if prices.empty or volumes.empty:
            return 0.0, 1.0
        latest_ret = abs(np.log(prices.iloc[-1] / prices.iloc[-2])) if len(prices) > 1 else 0.0
        latest_vol = float(volumes.iloc[-1]) if len(volumes) else 1.0
        illiq = latest_ret / max(latest_vol, 1e-9)
        self._update_history(self.illiq_history, symbol, illiq, horizon_hours=24 * 30)
        illiq_values = [v for _, v in self.illiq_history.get(symbol, [])]
        if not illiq_values:
            return illiq, 1.0
        p95 = float(np.percentile(illiq_values, 95))
        size_multiplier = 1.0
        if illiq > p95:
            size_multiplier = 0.5
        return illiq, size_multiplier

    def evaluate(
        self,
        symbol: str,
        book_ticker: Dict,
        price_window: pd.DataFrame,
        long_bias: bool,
        risk_on: bool = False,
    ) -> MicrostructureResult:
        price_window = price_window.copy()
        price_window.columns = [c.lower() for c in price_window.columns]
        if "close" not in price_window:
            raise ValueError("price_window must contain close column")

        ofi_z = self._ofi_z(symbol, book_ticker)
        vwap = self._vwap(price_window.tail(60))
        last_price = float(price_window["close"].iloc[-1])

        volumes = price_window["volume"].tail(2) if "volume" in price_window else FALLBACK_VOLUME_SERIES
        # Use a tiny positive fallback volume to keep Amihud guard stable when no volume is supplied.
        illiq, size_multiplier = self._illiq_guard(symbol, price_window["close"].tail(2), volumes)

        entry_threshold = self.config.get("microstructure", {}).get("ofi_z_entry", 2.0)
        if risk_on:
            entry_threshold = self.config.get("microstructure", {}).get("ofi_z_risk_on", entry_threshold)

        entry_allowed = bool(long_bias and ofi_z >= entry_threshold and last_price > vwap)

        return MicrostructureResult(
            entry_allowed=entry_allowed,
            ofi_z=ofi_z,
            vwap_1h=vwap,
            illiq=illiq,
            size_multiplier=size_multiplier,
            last_price=last_price,
        )
