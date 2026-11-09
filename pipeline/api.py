"""One authenticated publisher API; public catalog browsing remains anonymous."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from pipeline.settings import settings
from pipeline.portal import auth, datasets, legacy, organisations
from pipeline.portal.security import principal, rate_limit

app = FastAPI(title="Nigeria Open Data - Publisher API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url.rstrip("/")], allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "Authorization"])

from sqlalchemy import text
from pipeline.db.warehouse import get_engine

if settings.catalog_backend == "local":
    from pipeline.catalog.api import router as catalog_router
    app.include_router(catalog_router)

class ResponsePolicy(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/api/portal") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            try:
                who = await principal(request)
                if not who.verified:
                    raise HTTPException(403, "Verify your email first.")
                rate_limit(request, "publisher-write", str(who.user_id or who.token_id), 30)
            except HTTPException as error:
                return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)
        length = request.headers.get("content-length")
        limit = 8192 if request.url.path.startswith("/api/auth") else 52 * 1024 * 1024
        if length and (not length.isdigit() or int(length) > limit):
            return JSONResponse({"detail": "Request exceeds the permitted size."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith(("/api/auth", "/api/portal")):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(ResponsePolicy)


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = 8192 if scope["path"].startswith("/api/auth") else 52 * 1024 * 1024
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                raise HTTPException(413, "Request exceeds the permitted size.")
            return message

        await self.app(scope, bounded_receive, send)


app.add_middleware(BodyLimit)


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, error: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in error.errors()
    ]})


app.include_router(auth.router)
app.include_router(organisations.router)
app.include_router(datasets.router)
app.include_router(datasets.public_router)
app.include_router(legacy.router)

@app.get("/api/status")
def data_status():
    """How fresh and complete the data is, per source. Public and read-only.

    Built from the pipeline's own records of what it loaded and when, so it
    describes what actually happened, not what was scheduled.
    """
    engine = get_engine()
    with engine.connect() as conn:
        loaded = conn.execute(text("""
            SELECT source_system,
                   count(*) FILTER (WHERE status = 'success' AND COALESCE(row_count, 0) > 0) AS with_data,
                   count(*) FILTER (WHERE status = 'success' AND COALESCE(row_count, 0) = 0) AS no_data,
                   count(*) FILTER (WHERE status = 'failed')                                AS failed,
                   count(*) FILTER (WHERE publish_state = 'failed')                         AS unpublished,
                   max(last_ingested) FILTER (WHERE status = 'success')                     AS last_success,
                   max(last_ingested)                                                       AS last_checked
            FROM cdm.ingest_manifest
            GROUP BY source_system
        """)).mappings().all()
        observations = dict(conn.execute(text(
            "SELECT source_system, count(*) FROM cdm.indicator_observation GROUP BY source_system"
        )).fetchall())
        names = {
            row[0]: (row[1] or {}).get("source_name") or row[0]
            for row in conn.execute(text("SELECT source_id, options FROM cdm.data_sources")).fetchall()
        }

    from pipeline.harvest.portals import HARVEST_PORTALS
    portal_titles = {f"harvest:{p['id']}": p["title"] for p in HARVEST_PORTALS}

    def iso(value):
        return value.isoformat() if value else None

    sources = []
    for row in loaded:
        key = row["source_system"]
        harvested = key.startswith("harvest:")
        sources.append({
            "id": key,
            "name": portal_titles.get(key) or names.get(key) or key,
            "kind": "listed from another portal" if harvested else "data held here",
            "datasets": row["with_data"],
            "checked_without_data": row["no_data"],
            "failed": row["failed"],
            "awaiting_publication": row["unpublished"],
            "observations": observations.get(key, 0),
            "last_successful_update": iso(row["last_success"]),
            "last_checked": iso(row["last_checked"]),
        })
    sources.sort(key=lambda item: (-item["datasets"], item["name"]))

    stamps = [s["last_successful_update"] for s in sources if s["last_successful_update"]]
    return {
        "sources": sources,
        "totals": {
            "datasets": sum(s["datasets"] for s in sources),
            "observations": sum(s["observations"] for s in sources),
            "sources": len(sources),
            "failed": sum(s["failed"] for s in sources),
            "last_successful_update": max(stamps) if stamps else None,
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}
