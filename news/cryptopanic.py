import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional

import numpy as np
import requests


@dataclass
class NewsItem:
    title: str
    tags: List[str]
    source: str
    timestamp: datetime
    sentiment: float


class CryptoPanicClient:
    def __init__(self, config: Dict):
        self.config = config
        self.token = os.getenv("CRYPTOPANIC_TOKEN")
        self.decay_half_life = float(config.get("sentiment", {}).get("decay_half_life_hours", 12))
        self.baseline: Deque = deque(maxlen=3000)  # ~30d placeholder

    def fetch_latest(self, limit: int = 20) -> List[NewsItem]:
        if not self.token:
            return []
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {"auth_token": self.token, "kind": "news", "public": "true", "limit": limit}
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("results", [])
        except Exception:
            return []

        items: List[NewsItem] = []
        for entry in data:
            published_at = entry.get("published_at") or entry.get("created_at")
            try:
                ts = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.utcnow()
            tags = entry.get("tags") or []
            title = entry.get("title") or ""
            source = (entry.get("source") or {}).get("title", "")
            sentiment = self._score_item(title, tags, source)
            items.append(NewsItem(title=title, tags=tags, source=source, timestamp=ts, sentiment=sentiment))
        return items

    def _score_item(self, title: str, tags: List[str], source: str) -> float:
        text = title.lower()
        score = 0.0
        positive = ["upgrade", "partnership", "launch", "support", "integration", "etf", "approval"]
        negative = ["hack", "exploit", "outage", "ban", "lawsuit", "fraud", "charge"]
        for word in positive:
            if word in text:
                score += 0.2
        for word in negative:
            if word in text:
                score -= 0.3
        if "bullish" in tags:
            score += 0.5
        if "bearish" in tags:
            score -= 0.5
        trusted_sources = ["coindesk", "cointelegraph", "reuters", "bloomberg"]
        if source and source.lower() in trusted_sources:
            score *= 1.1
        return max(min(score, 1.0), -1.0)

    def sentiment_z(self) -> float:
        items = self.fetch_latest(limit=30)
        if not items:
            return 0.0

        now = datetime.utcnow()
        values = []
        for item in items:
            age_hours = (now - item.timestamp).total_seconds() / 3600
            decay = 0.5 ** (age_hours / self.decay_half_life) if self.decay_half_life > 0 else 1.0
            values.append(item.sentiment * decay)
            self.baseline.append(item.sentiment)

        raw_sent = float(np.mean(values)) if values else 0.0

        baseline_values = np.array(self.baseline) if self.baseline else np.array([0.0])
        mean = baseline_values.mean()
        std = baseline_values.std(ddof=1) if baseline_values.std(ddof=1) > 0 else 1.0
        sent_z = (raw_sent - mean) / std
        return float(sent_z)
