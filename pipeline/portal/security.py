from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request

from pipeline.settings import settings
from pipeline.portal import store

SESSION_COOKIE = "nod_session"
CSRF_COOKIE = "nod_csrf"
SCOPES = {"datasets:read", "datasets:submit", "datasets:publish", "sources:write", "uploads:write", "ingest:trigger"}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def vault() -> Fernet:
    if not settings.portal_secret_key:
        raise HTTPException(503, "Account and credential encryption must be configured by the operator.")
    try:
        return Fernet(settings.portal_secret_key.get_secret_value().encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "Account encryption configuration is invalid.") from None


def seal(value: str) -> str:
    return vault().encrypt(value.encode()).decode()


def unseal(value: str) -> str:
    return vault().decrypt(value.encode()).decode()


def check_origin(request: Request):
    if request.headers.get("origin") != settings.frontend_url.rstrip("/"):
        raise HTTPException(403, "Request origin is not authorised.")


def rate_limit(request: Request, category: str, subject: str = "", limit: int = 10):
    peer = request.client.host if request.client else "unknown"
    slot = int(time.time()) // 300
    buckets = [(f"{category}:ip:{digest(peer)}:{slot}", 30),
               (f"{category}:subject:{digest(subject or peer)}:{slot}", limit)]
    with store.engine().begin() as conn:
        counts = [store.one(conn, """INSERT INTO cdm.portal_rate_limits(bucket,count,expires_at)
            VALUES (:bucket,1,NOW()+INTERVAL '5 minutes')
            ON CONFLICT(bucket) DO UPDATE SET count=cdm.portal_rate_limits.count+1
            RETURNING count""", bucket=bucket)["count"] for bucket, _ in buckets]
    if any(count > bound for count, (_, bound) in zip(counts, buckets)):
        raise HTTPException(429, "Too many attempts. Please try again later.", headers={"Retry-After": "300"})


@dataclass
class Principal:
    user_id: object | None
    email: str | None
    verified: bool
    authenticated_at: datetime | None
    token_id: object | None = None
    publisher_id: object | None = None
    scopes: frozenset = frozenset()


async def principal(request: Request, scope: str | None = None, legacy: bool = False) -> Principal:
    token = request.headers.get("authorization", "")
    if token.startswith("Bearer "):
        token = token[7:]
    else:
        token = ""
    if not token and legacy and not request.cookies.get(SESSION_COOKIE):
        if request.headers.get("content-type", "").startswith("application/json"):
            token = (await request.json()).get("publisher_api_key", "")
        elif request.headers.get("content-type", "").startswith("multipart/form-data"):
            token = (await request.form()).get("publisher_api_key", "")
    with store.engine().connect() as conn:
        if token:
            row = store.one(conn, """SELECT t.* FROM cdm.portal_integration_tokens t
                JOIN cdm.publishers p ON p.id=t.publisher_id
                WHERE t.token_hash=:hash AND t.revoked_at IS NULL AND p.is_active=true
                AND (t.expires_at IS NULL OR t.expires_at>NOW())""", hash=digest(str(token)))
            if not row:
                raise HTTPException(401, "Integration token is invalid or expired.")
            if scope and scope not in row["scopes"]:
                raise HTTPException(403, "Integration token does not have the required scope.")
            return Principal(None, None, True, None, row["id"], row["publisher_id"], frozenset(row["scopes"]))
        raw = request.cookies.get(SESSION_COOKIE, "")
        row = store.one(conn, """SELECT s.*,u.email,u.verified_at FROM cdm.portal_sessions s
            JOIN cdm.portal_users u ON u.id=s.user_id
            WHERE s.token_hash=:hash AND s.expires_at>NOW() AND u.is_active=true""", hash=digest(raw))
    if not row:
        raise HTTPException(401, "Please sign in. Your session may have expired.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not csrf or not secrets.compare_digest(csrf, cookie) or not secrets.compare_digest(digest(csrf), row["csrf_hash"]):
            raise HTTPException(403, "Session verification failed. Refresh the page and try again.")
    return Principal(row["user_id"], row["email"], bool(row["verified_at"]), row["authenticated_at"])


def membership(conn, who: Principal, publisher_id, write=False, owner=False):
    if not who.verified:
        raise HTTPException(403, "Verify your email before managing datasets.")
    if who.token_id:
        if str(who.publisher_id) != str(publisher_id):
            raise HTTPException(403, "This organisation is not authorised.")
        if not store.one(conn, "SELECT id FROM cdm.publishers WHERE id=:id AND is_active=true", id=publisher_id):
            raise HTTPException(403, "This organisation is inactive.")
        return "integration"
    sql = """SELECT m.role FROM cdm.portal_memberships m
        JOIN cdm.publishers p ON p.id=m.publisher_id
        WHERE m.user_id=:user AND m.publisher_id=:publisher AND p.is_active=true"""
    if write or owner:
        sql += " FOR UPDATE OF m,p"
    row = store.one(conn, sql,
        user=who.user_id, publisher=publisher_id)
    if not row or (write and row["role"] == "viewer") or (owner and row["role"] != "owner"):
        raise HTTPException(403, "You do not have permission in this organisation.")
    return row["role"]


def recent(who: Principal):
    if who.token_id:
        return
    if not who.authenticated_at or (datetime.now(timezone.utc) - who.authenticated_at).total_seconds() > 900:
        raise HTTPException(401, "Please confirm your password for this sensitive action.", headers={"X-Reauthentication-Required": "true"})
