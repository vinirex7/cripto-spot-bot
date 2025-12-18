from typing import Any, Dict


def shock_multiplier(status: Dict[str, Any]) -> float:
    st = status.get("status", "ok")
    if st == "hard":
        return 0.0
    if st == "soft":
        return 0.5
    return 1.0
