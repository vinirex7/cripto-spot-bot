# execution/binance_client.py
"""Binance Spot API client."""
from __future__ import annotations

import os
import time
import hmac
import hashlib
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests


class BinanceSpotClient:
    def __init__(
        self,
        api_key: Optional[str],
        api_secret: Optional[str],
        config: Optional[Dict[str, Any]],
    ) -> None:
        self.config = config or {}

        # --- API keys: ENV wins; fallback to config.yaml (api_keys.binance) ---
        cfg_keys = (self.config.get("api_keys") or {}).get("binance") or {}
        self.api_key = api_key or os.getenv("BINANCE_API_KEY") or cfg_keys.get("api_key") or ""
        self.api_secret = api_secret or os.getenv("BINANCE_API_SECRET") or cfg_keys.get("api_secret") or ""

        if not self.api_key or not self.api_secret:
            raise ValueError("Missing Binance API key/secret (set ENV or config.yaml api_keys.binance).")

        # --- URLs / settings ---
        ex = self.config.get("exchange", {}) if isinstance(self.config, dict) else {}
        self.base_url = str(ex.get("base_url", "https://api.binance.com")).rstrip("/")

        self.timeout = float(ex.get("timeout_seconds", 20))
        self.recv_window = int(ex.get("recv_window_ms", 5000))

        # Cache exchangeInfo to reduce calls
        self._exchange_info_cache: Optional[Dict[str, Any]] = None
        self._exchange_info_cache_ts: float = 0.0
        self._exchange_info_cache_ttl: float = float(ex.get("exchange_info_cache_ttl_seconds", 300))

    # -------------------------
    # Signing + request
    # -------------------------
    def _canonicalize_params(self, params: Dict[str, Any]) -> Dict[str, str]:
        """
        Convert params to a clean dict[str,str] without None values.
        Binance signature is very sensitive to exact bytes sent.
        """
        out: Dict[str, str] = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            # Keep already formatted strings (orders.py sends qty/price as strings)
            if isinstance(v, bool):
                out[k] = "true" if v else "false"
            else:
                out[k] = str(v)
        return out

    def _build_query_and_signature(self, params: Dict[str, Any]) -> Tuple[str, str]:
        """
        Builds the query string using urllib.parse.urlencode (the same encoding standard requests uses),
        then signs exactly that query string.
        """
        p = self._canonicalize_params(params)

        # Sort keys for stability (recommended; Binance accepts it and avoids random ordering differences)
        query = urlencode(sorted(p.items()), doseq=True)

        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return query, sig

    def _request(self, method: str, endpoint: str, signed: bool = False, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key}

        p = params or {}

        if signed:
            p = dict(p)  # copy
            p["timestamp"] = int(time.time() * 1000)
            p["recvWindow"] = self.recv_window

            _, sig = self._build_query_and_signature(p)
            p["signature"] = sig

            # Ensure everything is str (after signature too)
            p = self._canonicalize_params(p)

        # Binance expects signed params in querystring (requests 'params' does that)
        resp = requests.request(method, url, headers=headers, timeout=self.timeout, params=p)

        # Better error visibility than a naked raise_for_status()
        if resp.status_code >= 400:
            # Binance usually returns JSON: {"code":-1013,"msg":"..."}
            try:
                j = resp.json()
            except Exception:
                j = {"raw": resp.text}
            raise RuntimeError(f"Binance HTTP {resp.status_code} {endpoint} | {j}")

        return resp.json()

    # -------------------------
    # Public endpoints
    # -------------------------
    def get_account(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v3/account", signed=True)

    def get_ticker_price(self, symbol: str) -> Dict[str, Any]:
        return self._request("GET", "/api/v3/ticker/price", params={"symbol": symbol})

    def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Any,
        price: Optional[Any] = None,
        time_in_force: str = "GTC",
    ) -> Dict[str, Any]:
        """
        quantity/price should preferably be strings already (orders.py sends str)
        to avoid float formatting issues.
        """
        ot = str(order_type).upper()
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": str(side).upper(),
            "type": ot,
            "quantity": quantity,
        }
        if ot == "LIMIT":
            params["timeInForce"] = time_in_force
            params["price"] = price

        return self._request("POST", "/api/v3/order", signed=True, params=params)

    # -------------------------
    # Exchange info helpers
    # -------------------------
    def get_exchange_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        now = time.time()
        if (
            not force_refresh
            and self._exchange_info_cache is not None
            and (now - self._exchange_info_cache_ts) < self._exchange_info_cache_ttl
        ):
            return self._exchange_info_cache

        info = self._request("GET", "/api/v3/exchangeInfo", signed=False)
        self._exchange_info_cache = info
        self._exchange_info_cache_ts = now
        return info

    def get_symbol_filters(self, symbol: str) -> Dict[str, Any]:
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol:
                return {f["filterType"]: f for f in s.get("filters", [])}
        raise ValueError(f"Symbol not found: {symbol}")