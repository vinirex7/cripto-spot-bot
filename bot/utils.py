"""Utility functions for the bot."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def write_jsonl(filepath: str, payload: Dict[str, Any], flush: bool = True) -> None:
    """
    Append a JSON line to a file.
    
    Args:
        filepath: Path to the JSONL file
        payload: Dictionary to serialize as JSON
        flush: Whether to flush after writing
    """
    # Ensure directory exists
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
        if flush:
            f.flush()
            os.fsync(f.fileno())


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load YAML configuration file.
    
    Args:
        config_path: Path to the config.yaml file
        
    Returns:
        Configuration dictionary
    """
    import yaml
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
