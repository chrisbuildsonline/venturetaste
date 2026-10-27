"""One call to an OpenAI-compatible chat endpoint (local Ollama by default). Any failure returns None."""

import json
import os
import re
from collections.abc import Callable
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"
TIMEOUT = httpx.Timeout(30.0, connect=1.0)

Reply = tuple[str, dict[str, Any]]  # (model name, parsed JSON object)
Llm = Callable[[str, str], Reply | None]  # (system prompt, user prompt)


def model() -> str:
    return os.environ.get("VENTURETASTE_LLM_MODEL") or DEFAULT_MODEL


def chat_json(system: str, user: str) -> Reply | None:
    """Ask for a JSON object. None when the LLM is off, unreachable, slow, or answers something that is not a JSON object."""
    if os.environ.get("VENTURETASTE_LLM", "").lower() == "off":
        return None
    url = (os.environ.get("VENTURETASTE_LLM_URL") or DEFAULT_URL).rstrip("/")
    key = os.environ.get("VENTURETASTE_LLM_API_KEY")
    name = model()
    body = {
        "model": name,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "stream": False,
    }
    try:
        resp = httpx.post(f"{url}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=TIMEOUT)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL))
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return None
    return (name, parsed) if isinstance(parsed, dict) else None
