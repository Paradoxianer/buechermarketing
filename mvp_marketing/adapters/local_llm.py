import json
import os
from typing import Any

import requests


class LocalLLMAdapter:
    def __init__(self) -> None:
        self.endpoint = os.getenv("LOCAL_LLM_ENDPOINT", "http://localhost:11434/v1/chat/completions")
        self.model = os.getenv("LOCAL_LLM_MODEL", "llama3:8b")
        self.api_key = os.getenv("LOCAL_LLM_API_KEY", "")
        self.timeout = int(os.getenv("LOCAL_LLM_TIMEOUT", "30"))

    def complete(self, prompt: str, dry_run: bool = True) -> str:
        if dry_run:
            return ""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Du bist ein hilfreicher Offline-Marketing Assistent."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        res = requests.post(self.endpoint, headers=headers, json=payload, timeout=self.timeout)
        res.raise_for_status()
        data = res.json()
        return data["choices"][0]["message"]["content"].strip()

    def complete_json(self, prompt: str, fallback: Any, dry_run: bool = True) -> Any:
        raw = self.complete(prompt, dry_run=dry_run)
        if not raw:
            return fallback
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end >= 0:
                return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return fallback
        return fallback
