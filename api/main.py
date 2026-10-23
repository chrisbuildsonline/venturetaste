import json
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

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from api.pipeline import NoTasteDataError, SameBrandError, run_diligence, stream_diligence
from api.presets import PRESETS
from api.qloo import (
    BrandNotFoundError,
    MissingKeyError,
    QlooAPIError,
    QlooClient,
    QlooError,
    QlooParseError,
)

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


def get_qloo() -> QlooClient:
    """Built per request (never at import) so a missing key is a 503, not a crash."""
    if os.environ.get("VENTURETASTE_FIXTURES") == "1":  # e2e runs: recorded Qloo answers, no key, no network
        from api.tests.qloo_fake import fixture_handler, make_client

        return make_client(Path(tempfile.mkdtemp(prefix="venturetaste-fixtures-")), fixture_handler([]))
    return QlooClient()


@app.exception_handler(QlooError)
def qloo_error(request: Request, exc: QlooError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=ERROR_STATUS.get(type(exc), 502))


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/presets")
def presets() -> list[dict[str, str]]:
    return [asdict(p) for p in PRESETS]


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
def diligence(body: DiligenceRequest, client: Annotated[QlooClient, Depends(get_qloo)]) -> dict[str, Any]:
    return run_diligence(client, body.acquirer, body.target)


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/diligence/stream", dependencies=[Depends(rate_limit)])
def diligence_stream(body: DiligenceRequest, client: Annotated[QlooClient, Depends(get_qloo)]) -> StreamingResponse:
    """Same run as /api/diligence, as server-sent events: agent start/finish, then result (or error)."""

    def events() -> Iterator[str]:
        try:
            for event, data in stream_diligence(client, body.acquirer, body.target):
                yield sse(event, data)
        except QlooError as exc:
            yield sse("error", {"status": ERROR_STATUS.get(type(exc), 502), "detail": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


WEB_OUT = Path(__file__).resolve().parent.parent / "web" / "out"
if WEB_OUT.is_dir():
    app.mount("/", StaticFiles(directory=WEB_OUT, html=True), name="web")
