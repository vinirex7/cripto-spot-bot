import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import requests

from bot.utils import utcnow, write_jsonl
from data.history_store import HistoryStore


BINANCE_REST = "https://api.binance.com/api/v3/klines"


def _fetch_klines(
    symbol: str,
    interval: str,
    start_time: int,
    end_time: int,
    rate_limit_sleep: float,
) -> List[Tuple]:
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_time,
        "endTime": end_time,
        "limit": 1000,
    }
    resp = requests.get(BINANCE_REST, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Binance error {resp.status_code}: {resp.text}")
    data = resp.json()
    candles = []
    for item in data:
        candles.append(
            (
                symbol,
                int(item[0]),
                float(item[1]),
                float(item[2]),
                float(item[3]),
                float(item[4]),
                float(item[5]),
                int(item[6]),
            )
        )
    time.sleep(rate_limit_sleep)
    return candles


def _download_interval(
    symbol: str,
    interval: str,
    lookback_days: int,
    history_store: HistoryStore,
    rate_limit_sleep: float,
) -> int:
    end = utcnow()
    start = end - timedelta(days=lookback_days)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    step_ms = 60 * 60 * 1000 if interval == "1h" else 24 * 60 * 60 * 1000
    # Binance returns at most 1000 candles; iterate in windows
    cursor = start_ms
    stored = 0
    while cursor < end_ms:
        window_end = min(end_ms, cursor + 1000 * step_ms)
        candles = _fetch_klines(
            symbol, interval, cursor, window_end, rate_limit_sleep
        )
        if candles:
            stored += history_store.store_candles(interval, symbol, candles)
            cursor = candles[-1][1] + step_ms
        else:
            cursor = window_end
    return stored


def run_backfill(config: Dict[str, Any], history_store: HistoryStore) -> Dict[str, Any]:
    hist_cfg = config["history"]["backfill"]
    rate_limit_sleep = hist_cfg.get("rest_rate_limit_sleep_s", 0.25)
    parallelism = max(1, hist_cfg.get("symbols_parallelism", 1))
    summary: Dict[str, Any] = {"symbols": {}}
    symbols = config.get("universe", [])
    futures = []
    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        for symbol in symbols:
            futures.append(
                executor.submit(
                    _download_symbol,
                    symbol,
                    config,
                    history_store,
                    rate_limit_sleep,
                )
            )
        for fut in as_completed(futures):
            sym, res = fut.result()
            summary["symbols"][sym] = res
    logs_cfg = config.get("logging", {})
    write_jsonl(
        logs_cfg.get("files", {}).get("system", "logs/system.jsonl"),
        {
            "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": "backfill_summary",
            "summary": summary,
        },
        flush=logs_cfg.get("flush_every_write", True),
    )
    return summary


def _download_symbol(
    symbol: str,
    config: Dict[str, Any],
    history_store: HistoryStore,
    rate_limit_sleep: float,
) -> Tuple[str, Dict[str, Any]]:
    hist_cfg = config["history"]["backfill"]
    stored_1d = _download_interval(
        symbol,
        hist_cfg["interval_1d"],
        hist_cfg["lookback_days_1d"],
        history_store,
        rate_limit_sleep,
    )
    stored_1h = _download_interval(
        symbol,
        hist_cfg["interval_1h"],
        hist_cfg["lookback_days_1h"],
        history_store,
        rate_limit_sleep,
    )
    validate = config["history"].get("validate_gaps", True)
    gaps_1d_ok = True
    gaps_1h_ok = True
    if validate:
        gaps_1d_ok = history_store.validate_gaps(
            hist_cfg["interval_1d"], symbol, hist_cfg["max_gap_candles_1d"]
        )
        gaps_1h_ok = history_store.validate_gaps(
            hist_cfg["interval_1h"], symbol, hist_cfg["max_gap_candles_1h"]
        )
    return symbol, {
        "stored_1d": stored_1d,
        "stored_1h": stored_1h,
        "gaps_1d_ok": gaps_1d_ok,
        "gaps_1h_ok": gaps_1h_ok,
    }
