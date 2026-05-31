import json
import os
from typing import Any


def default_state() -> dict[str, Any]:
    return {
        "campaigns": [],
        "contacts": [],
        "outreach_queue": [],
        "coverage": [],
        "reviews": [],
        "approvals": {},
        "followups": [],
    }


def load_state(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return default_state()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    base = default_state()
    base.update(data)
    return base


def save_state(path: str, state: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
