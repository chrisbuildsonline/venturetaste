import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from api.pipeline import NoTasteDataError, SameBrandError, run_diligence
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


@app.post("/api/diligence")
def diligence(body: DiligenceRequest, client: Annotated[QlooClient, Depends(get_qloo)]) -> dict[str, Any]:
    return run_diligence(client, body.acquirer, body.target)


WEB_OUT = Path(__file__).resolve().parent.parent / "web" / "out"
if WEB_OUT.is_dir():
    app.mount("/", StaticFiles(directory=WEB_OUT, html=True), name="web")
