import itertools
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests


@dataclass
class Order:
    symbol: str
    side: str
    qty: float
    price: float
    ts: datetime
    mode: str
    client_id: str


class OrderExecutor:
    def __init__(self, config: Dict):
        self.config = config
        self.mode = config.get("bot", {}).get("mode", "paper")
        self.base_url = config.get("exchange", {}).get("base_url", "https://api.binance.com")
        self.open_orders: Dict[str, Order] = {}
        self.positions: Dict[str, float] = {}
        self._client_seq = itertools.count(1)
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")
        if self.mode == "trade" and (not self.api_key or not self.api_secret):
            raise RuntimeError("Trade mode requires BINANCE_API_KEY and BINANCE_API_SECRET environment variables.")

    def _client_order_id(self, symbol: str, side: str) -> str:
        return f"{symbol}-{side}-{next(self._client_seq)}"

    def _place_live_order(self, symbol: str, side: str, qty: float, price: float, allow_market: bool = False) -> Optional[Order]:
        # Placeholder live order via Binance API if credentials exist.
        # A production implementation must sign requests, handle errors/retries,
        # and parse responses to ensure orders are acknowledged or rejected deterministically.
        api_key = self.api_key
        api_secret = self.api_secret
        if not api_key or not api_secret:
            return None
        # A full signed implementation is intentionally omitted for safety in this scaffold.
        return None

    def place_order(self, symbol: str, side: str, weight: float, price: float, risk_on: bool = False, allow_market: bool = False) -> Order:
        client_id = self._client_order_id(symbol, side)
        if client_id in self.open_orders:
            return self.open_orders[client_id]

        qty = max(weight, 0)
        limit_offset = self.config.get("exchange", {}).get("price_offset_bps", 3) / 10000
        price_adj = price
        if price > 0:
            price_adj = price * (1 - limit_offset) if side.upper() == "BUY" else price * (1 + limit_offset)

        order = Order(
            symbol=symbol,
            side=side.upper(),
            qty=qty,
            price=price_adj,
            ts=datetime.now(timezone.utc),
            mode=self.mode,
            client_id=client_id,
        )

        if self.mode == "trade":
            live = self._place_live_order(symbol, side, qty, price_adj, allow_market=allow_market)
            if live:
                self.open_orders[client_id] = live
                return live
            raise NotImplementedError(
                "Live trading mode enabled but no signed order implementation is available. "
                "Provide credentials and implement signed order placement before enabling trade mode."
            )

        # Paper mode bookkeeping
        self.open_orders[client_id] = order
        self.positions[symbol] = self.positions.get(symbol, 0) + qty * (1 if side.upper() == "BUY" else -1)
        return order

    def close_all_positions(self, reason: str = "") -> List[Order]:
        exits: List[Order] = []
        for symbol, qty in list(self.positions.items()):
            if qty == 0:
                continue
            side = "SELL" if qty > 0 else "BUY"
            order = self.place_order(symbol, side, abs(qty), price=0, allow_market=True)
            exits.append(order)
            self.positions[symbol] = 0.0
        return exits

    def open_positions_count(self) -> int:
        return len([p for p in self.positions.values() if abs(p) > 0])

    def gross_exposure(self) -> float:
        return float(sum(abs(v) for v in self.positions.values()))
