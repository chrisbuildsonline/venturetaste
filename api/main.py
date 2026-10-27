import ipaddress
import json
import logging
import math
import os
import tempfile
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from api.llm import chat_json
from api.pipeline import NoTasteDataError, SameBrandError, stream_diligence
from api.presets import PRESETS, SCREENS, preset_brands, slug
from api.qloo import (
    BrandNotFoundError,
    MissingKeyError,
    QlooAPIError,
    QlooClient,
    QlooError,
    QlooParseError,
    normalize_base_url,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="VentureTaste")

BrandName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

# QlooError subclass -> HTTP status, so every pipeline failure becomes a friendly JSON message.
ERROR_STATUS: dict[type[QlooError], int] = {
    BrandNotFoundError: 422,
    NoTasteDataError: 422,
    SameBrandError: 422,
    MissingKeyError: 503,
    QlooAPIError: 502,
    QlooParseError: 502,
}


class DiligenceRequest(BaseModel):
    acquirer: BrandName
    target: BrandName


def fixture_client() -> QlooClient:
    from api.fixtures import fixture_handler, make_client

    return make_client(Path(tempfile.mkdtemp(prefix="venturetaste-fixtures-")), fixture_handler([]))


def fixture_mode() -> bool:
    return os.environ.get("VENTURETASTE_FIXTURES") == "1"


def get_qloo() -> QlooClient | None:
    """Built per request (never at import). None means no key is set: the run falls back or is a 503."""
    if fixture_mode():  # e2e runs: recorded Qloo answers, no key, no network
        return fixture_client()
    try:
        return QlooClient()
    except MissingKeyError:
        return None


# Why a run replays recorded answers. Shown to the user next to the results.
RECORDED_FIXTURE_MODE = "This server runs in fixture mode: recorded Qloo answers, no live calls."
RECORDED_NO_KEY = "No Qloo API key is set on this server, so this run replays recorded Qloo answers for this preset pair."
RECORDED_KEY_REJECTED = "Qloo rejected this server's API key, so this run replays recorded Qloo answers for this preset pair."


def is_recorded_pair(body: DiligenceRequest) -> bool:
    return {slug(body.acquirer), slug(body.target)} <= {slug(b) for b in preset_brands()}


def recorded_run(client: QlooClient, body: DiligenceRequest, reason: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """stream_diligence, with the result carrying why the answers are recorded."""
    for event, data in stream_diligence(client, body.acquirer, body.target, chat_json):
        yield event, {**data, "recorded": {"reason": reason}} if event == "result" else data


def run_events(client: QlooClient | None, body: DiligenceRequest) -> Iterator[tuple[str, dict[str, Any]]]:
    """stream_diligence, falling back to recorded answers for a preset pair when there is no usable Qloo key.
    Only a missing key or an HTTP 401/403 falls back; every other Qloo failure propagates unchanged."""
    if client is None:
        if not is_recorded_pair(body):
            raise MissingKeyError("QLOO_API_KEY is not set")
        yield from recorded_run(fixture_client(), body, RECORDED_NO_KEY)
        return
    if fixture_mode():
        yield from recorded_run(client, body, RECORDED_FIXTURE_MODE)
        return
    try:
        yield from stream_diligence(client, body.acquirer, body.target, chat_json)
    except QlooAPIError as exc:
        if exc.status not in (401, 403) or not is_recorded_pair(body):
            raise
        logger.warning("Qloo rejected the API key (HTTP %s); replaying recorded answers", exc.status)
        yield from recorded_run(fixture_client(), body, RECORDED_KEY_REJECTED)


UNAVAILABLE = "Taste data from Qloo is temporarily unavailable. Please try again in a moment."
# These messages are written for people. Everything else (transport, HTTP status, parse errors) can carry
# httpx text or response bodies, so the client gets UNAVAILABLE and the raw exception goes to the log.
HUMAN_ERRORS = (BrandNotFoundError, NoTasteDataError, SameBrandError, MissingKeyError)


def public_error(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, HUMAN_ERRORS):
        return ERROR_STATUS[type(exc)], str(exc)
    logger.error("diligence failed: %r", exc, exc_info=exc)
    return 502, UNAVAILABLE


@app.exception_handler(QlooError)
def qloo_error(request: Request, exc: QlooError) -> JSONResponse:
    status, detail = public_error(exc)
    return JSONResponse({"detail": detail}, status_code=status)


def _origin(url: str) -> str:
    """scheme://host[:port] only, so userinfo, path and query in the env URL never leave the server."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "qloo_key": bool(os.environ.get("QLOO_API_KEY")),
        "qloo_url": _origin(normalize_base_url(os.environ.get("QLOO_API_URL"))),
        "fixtures": os.environ.get("VENTURETASTE_FIXTURES") == "1",
    }


@app.get("/api/presets")
def presets() -> list[dict[str, str]]:
    return [asdict(p) for p in PRESETS]


@app.get("/api/screens")
def screens() -> list[dict[str, Any]]:
    return [asdict(s) for s in SCREENS]


RATE_WINDOW = 60.0
_clock = time.monotonic
_hits: dict[str, deque[float]] = {}
_hits_lock = threading.Lock()


def reset_rate_limit() -> None:
    with _hits_lock:
        _hits.clear()


# ponytail: single process, in-memory sliding window; a restart or a second worker resets it. Per-IP behind a
# proxy needs uvicorn --proxy-headers (and FORWARDED_ALLOW_IPS), or every user shares the proxy's address.
def rate_limit(request: Request) -> None:
    limit = int(os.environ.get("VENTURETASTE_RATE_LIMIT") or 30)
    ip = request.client.host if request.client else "unknown"
    try:
        addr = ipaddress.ip_address(ip)
        if isinstance(addr, ipaddress.IPv6Address):  # one client owns a whole /64, so key on that
            ip = str(addr.ipv4_mapped or ipaddress.ip_network(f"{addr}/64", strict=False))
    except ValueError:
        pass  # not an IP (e.g. "testclient"): use it as is
    now = _clock()
    with _hits_lock:
        for key in [k for k, q in _hits.items() if not q or q[-1] <= now - RATE_WINDOW]:
            del _hits[key]  # idle clients, so the dict cannot grow without bound
        hits = _hits.setdefault(ip, deque())
        while hits and hits[0] <= now - RATE_WINDOW:
            hits.popleft()
        if len(hits) >= limit:
            retry = max(1, math.ceil(hits[0] + RATE_WINDOW - now))
            raise HTTPException(
                429,
                "Too many diligence runs from your network. Try again in a minute.",
                headers={"Retry-After": str(retry)},
            )
        hits.append(now)


@app.post("/api/diligence", dependencies=[Depends(rate_limit)])
def diligence(body: DiligenceRequest, client: Annotated[QlooClient | None, Depends(get_qloo)]) -> dict[str, Any]:
    return next(data for event, data in run_events(client, body) if event == "result")


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/diligence/stream", dependencies=[Depends(rate_limit)])
def diligence_stream(body: DiligenceRequest, client: Annotated[QlooClient | None, Depends(get_qloo)]) -> StreamingResponse:
    """Same run as /api/diligence, as server-sent events: agent start/finish, then result (or error)."""
    if client is None and not is_recorded_pair(body):
        raise MissingKeyError("QLOO_API_KEY is not set")  # a plain 503 before streaming starts

    def events() -> Iterator[str]:
        try:
            for event, data in run_events(client, body):
                yield sse(event, data)
        except Exception as exc:  # the stream has started, so even a surprise must end as a clean error event
            status, detail = public_error(exc)
            yield sse("error", {"status": status, "detail": detail})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


WEB_OUT = Path(__file__).resolve().parent.parent / "web" / "out"
if WEB_OUT.is_dir():
    app.mount("/", StaticFiles(directory=WEB_OUT, html=True), name="web")
