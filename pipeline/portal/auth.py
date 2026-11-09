from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from pipeline.settings import settings
from pipeline.portal import store, mail
from pipeline.portal.security import CSRF_COOKIE, SESSION_COOKIE, check_origin, digest, principal, rate_limit

router = APIRouter(prefix="/api/auth", tags=["Publisher accounts"])
hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Email(Model):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}", value):
            raise ValueError("Enter a valid email address")
        return value


class Credentials(Email):
    password: SecretStr


class Password(Model):
    password: SecretStr


class Action(Model):
    token: str = Field(min_length=20, max_length=200)


class Reset(Action):
    password: SecretStr


def password_hash(password):
    value = password.get_secret_value()
    if not 12 <= len(value) <= 128:
        raise HTTPException(422, "Use a password between 12 and 128 characters.")
    return hasher.hash(value)


def matches(encoded, supplied):
    if len(supplied.get_secret_value()) > 128:
        return False
    try:
        return hasher.verify(encoded, supplied.get_secret_value())
    except (VerificationError, InvalidHashError):
        return False


def issue_action(conn, user_id, email, purpose):
    token = secrets.token_urlsafe(32)
    store.execute(conn, "UPDATE cdm.portal_email_actions SET used_at=NOW() WHERE user_id=:u AND purpose=:p AND used_at IS NULL", u=user_id, p=purpose)
    store.execute(conn, """INSERT INTO cdm.portal_email_actions(token_hash,user_id,purpose,expires_at)
        VALUES (:hash,:user,:purpose,NOW()+INTERVAL '30 minutes')""", hash=digest(token), user=user_id, purpose=purpose)
    mail.enqueue(conn, email, purpose, token)


def new_session(conn, response, user_id):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.portal_session_hours)
    store.execute(conn, """INSERT INTO cdm.portal_sessions(token_hash,user_id,csrf_hash,expires_at)
        VALUES (:hash,:user,:csrf,:expires)""", hash=digest(token), user=user_id, csrf=digest(csrf), expires=expires)
    for name, value, http_only in [(SESSION_COOKIE, token, True), (CSRF_COOKIE, csrf, False)]:
        response.set_cookie(name, value, httponly=http_only, secure=settings.portal_cookie_secure,
                            samesite="lax", path="/", max_age=settings.portal_session_hours * 3600)


@router.post("/register", status_code=202)
def register(body: Credentials, request: Request):
    check_origin(request)
    rate_limit(request, "register", body.email, 5)
    mail.configured()
    encoded = password_hash(body.password)
    with store.engine().begin() as conn:
        store.execute(conn, "SELECT pg_advisory_xact_lock(hashtext(:email))", email=body.email)
        row = store.one(conn, """INSERT INTO cdm.portal_users(email,password_hash) VALUES (:email,:hash)
            ON CONFLICT(email) DO NOTHING RETURNING id,email,verified_at""", email=body.email, hash=encoded)
        if not row:
            row = store.one(conn, "SELECT id,email,verified_at FROM cdm.portal_users WHERE email=:email", email=body.email)
        if not row["verified_at"]:
            issue_action(conn, row["id"], row["email"], "verify")
    return {"message": "If this address needs verification, an email has been queued. Check your inbox, then sign in."}


@router.post("/verify")
def verify(body: Action, request: Request):
    check_origin(request)
    rate_limit(request, "verify")
    with store.engine().begin() as conn:
        row = store.one(conn, """UPDATE cdm.portal_email_actions SET used_at=NOW()
            WHERE token_hash=:h AND purpose='verify' AND used_at IS NULL AND expires_at>NOW()
            RETURNING user_id""", h=digest(body.token))
        if not row:
            raise HTTPException(400, "Verification link is invalid or expired. Request a new email.")
        store.execute(conn, "UPDATE cdm.portal_users SET verified_at=NOW() WHERE id=:id", id=row["user_id"])
    return {"message": "Email verified. You can sign in."}


@router.post("/resend-verification", status_code=202)
def resend(body: Email, request: Request):
    check_origin(request)
    rate_limit(request, "resend", body.email, 3)
    mail.configured()
    with store.engine().begin() as conn:
        row = store.one(conn, "SELECT id,email FROM cdm.portal_users WHERE email=:e AND verified_at IS NULL AND is_active=true", e=body.email)
        if row:
            issue_action(conn, row["id"], row["email"], "verify")
    return {"message": "If verification is needed, an email has been queued."}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    check_origin(request)
    rate_limit(request, "login", body.email)
    with store.engine().begin() as conn:
        row = store.one(conn, "SELECT * FROM cdm.portal_users WHERE email=:email AND is_active=true FOR UPDATE", email=body.email)
        valid = matches(row["password_hash"] if row else dummy_hash, body.password)
        if not row or not valid:
            raise HTTPException(401, "Email or password is incorrect.")
        # Rotate an existing session rather than keeping a pre-login cookie.
        store.execute(conn, "DELETE FROM cdm.portal_sessions WHERE token_hash=:h", h=digest(request.cookies.get(SESSION_COOKIE, "")))
        if hasher.check_needs_rehash(row["password_hash"]):
            store.execute(conn, "UPDATE cdm.portal_users SET password_hash=:h WHERE id=:id", h=password_hash(body.password), id=row["id"])
        new_session(conn, response, row["id"])
    return {"email": row["email"], "verified": bool(row["verified_at"])}


@router.get("/me")
async def me(request: Request):
    who = await principal(request)
    if who.token_id:
        raise HTTPException(403, "Use integration endpoints for automated clients.")
    with store.engine().connect() as conn:
        organisations = store.all_rows(conn, """SELECT p.id,p.name,p.details,m.role
            FROM cdm.portal_memberships m JOIN cdm.publishers p ON p.id=m.publisher_id
            WHERE m.user_id=:user AND p.is_active=true ORDER BY p.name""", user=who.user_id)
    return {"email": who.email, "verified": who.verified, "organisations": organisations}


@router.post("/logout")
async def logout(request: Request, response: Response):
    await principal(request)
    with store.engine().begin() as conn:
        store.execute(conn, "DELETE FROM cdm.portal_sessions WHERE token_hash=:h", h=digest(request.cookies.get(SESSION_COOKIE, "")))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"message": "Signed out."}


@router.post("/reauthenticate")
async def reauthenticate(body: Password, request: Request):
    who = await principal(request)
    if who.token_id:
        raise HTTPException(403, "Interactive session required.")
    rate_limit(request, "reauthenticate", str(who.user_id), 5)
    with store.engine().begin() as conn:
        row = store.one(conn, "SELECT password_hash FROM cdm.portal_users WHERE id=:id", id=who.user_id)
        if not matches(row["password_hash"], body.password):
            raise HTTPException(401, "Password is incorrect.")
        store.execute(conn, "UPDATE cdm.portal_sessions SET authenticated_at=NOW() WHERE token_hash=:h", h=digest(request.cookies[SESSION_COOKIE]))
    return {"message": "Password confirmed."}


@router.post("/recover", status_code=202)
def recover(body: Email, request: Request):
    check_origin(request)
    rate_limit(request, "recover", body.email, 3)
    mail.configured()
    with store.engine().begin() as conn:
        row = store.one(conn, "SELECT id,email FROM cdm.portal_users WHERE email=:e AND is_active=true", e=body.email)
        if row:
            issue_action(conn, row["id"], row["email"], "reset")
    return {"message": "If this account exists, a recovery email has been queued."}


@router.post("/reset")
def reset(body: Reset, request: Request):
    check_origin(request)
    rate_limit(request, "reset")
    encoded = password_hash(body.password)
    with store.engine().begin() as conn:
        row = store.one(conn, """UPDATE cdm.portal_email_actions SET used_at=NOW()
            WHERE token_hash=:h AND purpose='reset' AND used_at IS NULL AND expires_at>NOW()
            RETURNING user_id""", h=digest(body.token))
        if not row:
            raise HTTPException(400, "Recovery link is invalid or expired.")
        store.execute(conn, "UPDATE cdm.portal_users SET password_hash=:h WHERE id=:id", h=encoded, id=row["user_id"])
        store.execute(conn, "DELETE FROM cdm.portal_sessions WHERE user_id=:id", id=row["user_id"])
    return {"message": "Password updated. Sign in again."}
