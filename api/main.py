from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="VentureTaste")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


WEB_OUT = Path(__file__).resolve().parent.parent / "web" / "out"
if WEB_OUT.is_dir():
    app.mount("/", StaticFiles(directory=WEB_OUT, html=True), name="web")
