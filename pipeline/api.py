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


@app.get("/health")
def health():
    return {"status": "ok"}
