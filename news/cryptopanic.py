import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from bot.utils import ensure_dir


def _cache_path(data_dir: str) -> str:
    return os.path.join(data_dir, "news_cache.json")


def _load_cache(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"last_fetch": 0, "items": {}, "seen": {}}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_cache(path: str, cache: Dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)


def fetch_news(now: datetime, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    news_cfg = config.get("news", {})
    cp_cfg = news_cfg.get("cryptopanic", {})
    if not cp_cfg.get("enabled", True):
        return []
    token = os.getenv("CRYPTOPANIC_TOKEN")
    if not token:
        return []
    data_dir = config.get("paths", {}).get("data_dir", "data")
    cache_file = _cache_path(data_dir)
    cache = _load_cache(cache_file)
    last_fetch = cache.get("last_fetch", 0)
    cache_minutes = cp_cfg.get("cache_minutes", 720)
    if now.timestamp() - last_fetch < cache_minutes * 60 and cache.get("items"):
        return list(cache["items"].values())
    url = "https://cryptopanic.com/api/v1/posts/"
    params = {
        "auth_token": token,
        "kind": "news",
        "public": "true",
        "limit": cp_cfg.get("max_items_per_fetch", 50),
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items: List[Dict[str, Any]] = []
    for idx, item in enumerate(data.get("results", [])):
        news_id = item.get("id") or f"cp_{idx}"
        title = item.get("title", "")
        link = item.get("url") or ""
        published_at = item.get("published_at") or now.isoformat()
        items.append(
            {
                "id": f"cp_{news_id}",
                "title": title,
                "url": link,
                "published_at": published_at,
                "source": "cryptopanic",
            }
        )
    dedupe_hours = cp_cfg.get("dedupe_window_hours", 72)
    expiry_ts = now.timestamp() - dedupe_hours * 3600
    seen = cache.get("seen", {})
    seen = {k: v for k, v in seen.items() if v >= expiry_ts}
    deduped: List[Dict[str, Any]] = []
    for itm in items:
        key = itm["url"] or itm["title"]
        if key in seen:
            continue
        seen[key] = now.timestamp()
        deduped.append(itm)
    cache["last_fetch"] = int(now.timestamp())
    cache["items"] = {itm["id"]: itm for itm in deduped}
    cache["seen"] = seen
    _save_cache(cache_file, cache)
    return deduped
