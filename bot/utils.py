import json
import os
from datetime import datetime, timezone
from typing import Any, Dict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_jsonl(path: str, payload: Dict[str, Any], flush: bool = True) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if flush:
            fh.flush()
