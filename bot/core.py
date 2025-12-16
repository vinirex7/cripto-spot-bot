import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import requests
import yaml

from execution.orders import OrderExecutor
from news.cryptopanic import CryptoPanicClient
from risk.guards import RiskGuards
from risk.news_shock import NewsShockEngine
from signals.momentum import compute_momentum_signals
from signals.microstructure import MicrostructureAnalyzer

logger = logging.getLogger("strategy_mother_v1")
logging.basicConfig(level=logging.INFO)


def load_config(config_path: str = "config.yaml") -> Dict:
    if not Path(config_path).exists() and Path("config.yam").exists():
        config_path = "config.yam"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


class StrategyMotherEngine:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.last_slot = None
        self.cooldown_until = None
        self.micro = MicrostructureAnalyzer(self.config)
        self.news_client = CryptoPanicClient(self.config)
        self.news_shock = NewsShockEngine(self.config)
        self.risk = RiskGuards(self.config)
        self.executor = OrderExecutor(self.config)
        self.log_dir = Path(self.config.get("bot", {}).get("log_dir", "./logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _current_slot(self):
        return datetime.utcnow().replace(second=0, microsecond=0)

    def _fetch_klines(self, symbol: str, interval: str = "1d", limit: int = 400) -> pd.DataFrame:
        url = f"{self.config.get('exchange', {}).get('base_url', 'https://api.binance.com')}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            cols = [
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "trades",
                "taker_base",
                "taker_quote",
                "ignore",
            ]
            df = pd.DataFrame(data, columns=cols)
            df["close"] = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            return df
        except Exception:
            # Graceful fallback to synthetic data (random walk) to keep the loop alive in paper mode.
            dates = pd.date_range(end=datetime.utcnow(), periods=limit, freq="D")
            steps = np.random.normal(0, 0.01, size=limit)
            prices = 100 * np.exp(np.cumsum(steps))
            logger.warning("Using synthetic price fallback for %s (%s)", symbol, interval)
            return pd.DataFrame({"close": prices, "volume": [1.0] * limit})

    def _fetch_book_ticker(self, symbol: str) -> Dict:
        url = f"{self.config.get('exchange', {}).get('base_url', 'https://api.binance.com')}/api/v3/ticker/bookTicker"
        try:
            resp = requests.get(url, params={"symbol": symbol}, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {"bidPrice": 0, "askPrice": 0, "bidQty": 0, "askQty": 0}

    def _persist_log(self, payload: Dict):
        day = datetime.utcnow().strftime("%Y-%m-%d")
        file_path = self.log_dir / f"{day}-signals.jsonl"
        with open(file_path, "a") as f:
            f.write(json.dumps(payload) + "\n")

    def _handle_cooldown(self):
        if self.cooldown_until and datetime.utcnow() < self.cooldown_until:
            return True
        return False

    def step(self) -> Dict:
        slot = self._current_slot()
        if self.last_slot == slot:
            return {"status": "skipped", "reason": "already-executed", "timestamp": slot.isoformat()}
        self.last_slot = slot

        self.config = load_config(self.config_path)

        if self._handle_cooldown():
            payload = {"timestamp": slot.isoformat(), "action": "cooldown", "cooldown_until": self.cooldown_until.isoformat()}
            self._persist_log(payload)
            return payload

        universe = self.config.get("universe", {}).get("symbols", [])
        actions: List[Dict] = []
        sent_z = self.news_client.sentiment_z()

        for symbol in universe:
            daily = self._fetch_klines(symbol, interval="1d", limit=400)
            momentum = compute_momentum_signals(daily["close"], self.config.get("momentum", {}))

            if momentum.risk_off:
                actions.append({"symbol": symbol, "action": "risk_off_momentum"})
                continue

            hour_window = self._fetch_klines(symbol, interval="1m", limit=60)
            book = self._fetch_book_ticker(symbol)
            price_shock_z, vol_spike = self.news_shock.price_shock_metrics(symbol, hour_window)
            shock_state = self.news_shock.evaluate(sent_z, price_shock_z, vol_spike)

            if shock_state.hard:
                self.executor.close_all_positions(reason="news_shock_hard")
                self.cooldown_until = datetime.utcnow() + timedelta(hours=self.config.get("news", {}).get("cooldown_hours_hard", 6))
                payload = {
                    "timestamp": slot.isoformat(),
                    "symbol": symbol,
                    "action": "hard_risk_off",
                    "ns": shock_state.ns_score,
                    "sent_z": shock_state.sent_z,
                    "price_shock_z": shock_state.price_shock_z,
                    "vol_spike": shock_state.vol_spike,
                    "cooldown_until": self.cooldown_until.isoformat(),
                }
                self._persist_log(payload)
                actions.append(payload)
                continue

            micro = self.micro.evaluate(symbol, book, hour_window[["close", "volume"]], momentum.long_bias, risk_on=shock_state.risk_on)
            risk_assessment = self.risk.assess(
                portfolio_value=1.0,
                open_positions=self.executor.open_positions_count(),
                vol_1d=momentum.vol_1d,
                illiq=micro.illiq,
                soft_risk_off=shock_state.soft,
                current_allocation=self.executor.gross_exposure(),
            )

            if not micro.entry_allowed or not risk_assessment.allow_entry:
                payload = {
                    "timestamp": slot.isoformat(),
                    "symbol": symbol,
                    "action": "no_trade",
                    "ofi_z": micro.ofi_z,
                    "vwap": micro.vwap_1h,
                    "sent_z": sent_z,
                    "ns": shock_state.ns_score,
                    "reason": "microstructure" if not micro.entry_allowed else risk_assessment.reason,
                }
                self._persist_log(payload)
                actions.append(payload)
                continue

            weight = risk_assessment.weight * micro.size_multiplier
            order = self.executor.place_order(symbol, side="BUY", weight=weight, price=micro.last_price, risk_on=shock_state.risk_on)
            payload = {
                "timestamp": slot.isoformat(),
                "symbol": symbol,
                "M6": momentum.m6,
                "M12": momentum.m12,
                "delta_m": momentum.delta_m,
                "OFI_z": micro.ofi_z,
                "SentZ": sent_z,
                "NS": shock_state.ns_score,
                "regime": "risk_on" if shock_state.risk_on else ("soft_risk_off" if shock_state.soft else "neutral"),
                "risk_state": risk_assessment.reason,
                "action": "order_submitted",
                "order": order.client_id,
            }
            self._persist_log(payload)
            actions.append(payload)

        return {"status": "ok", "timestamp": slot.isoformat(), "actions": actions}
