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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from api.discover import discover
from api.llm import chat_json_or_replay
from api.pipeline import NoTasteDataError, SameBrandError, stream_diligence
from api.presets import DISCOVERED, PRESETS, SCREENS, preset_brands, slug
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
    for event, data in stream_diligence(client, body.acquirer, body.target, chat_json_or_replay):
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
        yield from stream_diligence(client, body.acquirer, body.target, chat_json_or_replay)
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
        mapped = addr.ipv4_mapped if isinstance(addr, ipaddress.IPv6Address) else None
        # The limit protects the public deploy's Qloo quota. Local runs and a judge's container reach the app from
        # loopback, so they are exempt. Not when X-Forwarded-For is present: uvicorn's proxy-headers middleware
        # (trusting 127.0.0.1) turns "X-Forwarded-For: 127.0.0.1" into a loopback client, so a visitor could
        # spoof the exemption. A proxy always sets that header; a direct local caller never does.
        if (addr.is_loopback or (mapped and mapped.is_loopback)) and "x-forwarded-for" not in request.headers:
            return
        if isinstance(addr, ipaddress.IPv6Address):  # one client owns a whole /64, so key on that
            ip = str(mapped or ipaddress.ip_network(f"{addr}/64", strict=False))
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


def run_result(client: QlooClient | None, body: DiligenceRequest) -> dict[str, Any]:
    """One pair's full diligence result, with the recorded fallback. Shared by /api/diligence and /api/screen."""
    return next(data for event, data in run_events(client, body) if event == "result")


@app.post("/api/diligence", dependencies=[Depends(rate_limit)])
def diligence(body: DiligenceRequest, client: Annotated[QlooClient | None, Depends(get_qloo)]) -> dict[str, Any]:
    return run_result(client, body)


MIN_TARGETS, MAX_TARGETS = 2, 5


class ScreenRequest(BaseModel):
    acquirer: BrandName
    targets: Annotated[list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]], Field(max_length=50)]


def screen_row(client: QlooClient | None, acquirer: str, target: str) -> dict[str, Any]:
    try:
        d = run_result(client, DiligenceRequest(acquirer=acquirer, target=target))
    except Exception as exc:  # one target failing must not sink the others
        status, detail = public_error(exc)
        return {"target": target, "ok": False, "status": status, "detail": detail}
    row = {"target": target, "ok": True, "bci": d["scores"]["bci"], "clash": d["scores"]["culture_clash"],
           "churn": d["scores"]["churn_risk"], "verdict": d["memo"]["verdict"]}
    if "recorded" in d:
        row["recorded"] = d["recorded"]["reason"]
    return row


@app.post("/api/screen", dependencies=[Depends(rate_limit)])
def screen(body: ScreenRequest, client: Annotated[QlooClient | None, Depends(get_qloo)]) -> dict[str, Any]:
    """Screens 2 to 5 targets against one acquirer. One rate-limit hit for the whole screen, targets in parallel."""
    seen = {body.acquirer.casefold()}
    targets: list[str] = []
    for t in body.targets:
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            targets.append(t)
    if not MIN_TARGETS <= len(targets) <= MAX_TARGETS:
        raise HTTPException(422, f"Screen {MIN_TARGETS} to {MAX_TARGETS} different targets, other than the acquirer.")
    # ponytail: each run already fans out about 6 Qloo threads and Qloo answers 429 at about 8 parallel requests, so 3 workers is the ceiling.
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda t: screen_row(client, body.acquirer, t), targets))
    return {"acquirer": body.acquirer, "rows": rows}


class DiscoverRequest(BaseModel):
    acquirer: BrandName


@app.post("/api/discover", dependencies=[Depends(rate_limit)])
def discover_targets(body: DiscoverRequest, client: Annotated[QlooClient | None, Depends(get_qloo)]) -> dict[str, Any]:
    """Candidate targets for Screen mode. Same recorded fallback as diligence, for the acquirers we recorded."""
    recorded = slug(body.acquirer) in {slug(a) for a in DISCOVERED}
    if client is None:
        if not recorded:
            raise MissingKeyError("QLOO_API_KEY is not set")
        return {**discover(fixture_client(), body.acquirer), "recorded": {"reason": RECORDED_NO_KEY}}
    if fixture_mode():
        return {**discover(client, body.acquirer), "recorded": {"reason": RECORDED_FIXTURE_MODE}}
    try:
        return discover(client, body.acquirer)
    except QlooAPIError as exc:
        if exc.status not in (401, 403) or not recorded:
            raise
        logger.warning("Qloo rejected the API key (HTTP %s); replaying recorded answers", exc.status)
        return {**discover(fixture_client(), body.acquirer), "recorded": {"reason": RECORDED_KEY_REJECTED}}


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
