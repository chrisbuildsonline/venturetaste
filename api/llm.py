"""One call to an OpenAI-compatible chat endpoint (local Ollama by default). Any failure returns None."""

import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import httpx

DEFAULT_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"
TIMEOUT = httpx.Timeout(30.0, connect=1.0)
REPLAY_FILE = Path(__file__).parent / "fixture_data" / "llm_replay.json"


class Recorded(NamedTuple):
    """A reply replayed from REPLAY_FILE, not produced by a live model just now."""

    model: str
    data: dict[str, Any]


Reply = tuple[str, dict[str, Any]]  # (model name, parsed JSON object); a Recorded is one too
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


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()


def chat_json_or_replay(system: str, user: str) -> Reply | None:
    """chat_json; when it gets no answer, the recorded reply for this exact (system, user) pair, if there is one.
    The caller runs the same checks on a Recorded reply as on a live one."""
    live = chat_json(system, user)
    if live is not None:
        return live
    try:
        entry = json.loads(REPLAY_FILE.read_text())[prompt_hash(system, user)]
        return Recorded(str(entry["model"]), dict(entry["reply"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
