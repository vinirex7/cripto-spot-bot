# bot/positions.py
from __future__ import annotations
import json, os
from typing import Dict, Any

class PositionStore:
    def __init__(self, path: str = "logs/positions.json") -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, symbol: str) -> Dict[str, Any]:
        return self._data.get(symbol, {"in_position": False, "entry_price": 0.0, "peak_price": 0.0})

    def set(self, symbol: str, pos: Dict[str, Any]) -> None:
        self._data[symbol] = pos
        self._save()

    def on_buy_filled(self, symbol: str, fill_price: float) -> None:
        # Versão simples: trata como entrada única.
        pos = self.get(symbol)
        pos["in_position"] = True
        pos["entry_price"] = float(fill_price)
        pos["peak_price"] = float(fill_price)
        self.set(symbol, pos)

    def on_tick(self, symbol: str, current_price: float) -> None:
        pos = self.get(symbol)
        if not pos.get("in_position"):
            return
        peak = float(pos.get("peak_price", 0.0))
        if current_price > peak:
            pos["peak_price"] = float(current_price)
            self.set(symbol, pos)

    def on_sell_filled(self, symbol: str) -> None:
        self.set(symbol, {"in_position": False, "entry_price": 0.0, "peak_price": 0.0})