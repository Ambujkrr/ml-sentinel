import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.routes.health import router as health_router
from app.api.routes.models import router as models_router
from app.api.routes.datasets import router as datasets_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.demo import router as demo_router
from app.api.routes.admin import router as admin_router
from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml_sentinel")

app = FastAPI(
    title=settings.APP_NAME,
    description="Machine Learning Monitoring & Drift Detection Platform",
)

app.include_router(health_router)
app.include_router(models_router)
app.include_router(datasets_router)
app.include_router(profiles_router)
app.include_router(monitoring_router)
app.include_router(alerts_router)
app.include_router(demo_router)
app.include_router(admin_router)

WEB_DIR = Path(__file__).parent / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = perf_counter()
    # Form parsers can spool multipart bodies before the endpoint runs.
    if request.method == "POST" and request.url.path.endswith("/datasets"):
        size = request.headers.get("content-length")
        if size and size.isdigit() and int(size) > settings.MAX_UPLOAD_BYTES + 1_000_000:
            return JSONResponse({"detail": "Upload exceeds the configured size limit"}, status_code=413)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request failure: %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
    if request.url.path.startswith("/admin/") or request.method == "DELETE" or request.url.path.endswith("/deletion-preview"):
        response.headers["Cache-Control"] = "no-store"
    logger.info("%s %s %s %.3fs", request.method, request.url.path,
                response.status_code, perf_counter() - start)
    return response


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(WEB_DIR / "dashboard.html", headers={
        "Cache-Control": "no-store", "X-Frame-Options": "DENY",
        "Content-Security-Policy": "frame-ancestors 'none'"})


@app.get("/")
def read_root() -> dict[str, str]:
    return {"name": settings.APP_NAME, "status": "running"}
