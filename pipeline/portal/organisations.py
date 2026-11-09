import json
import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from pipeline.portal import store, mail
from pipeline.portal.auth import Action, Email, Model
from pipeline.portal.security import SCOPES, digest, membership, principal, recent

router = APIRouter(prefix="/api/portal", tags=["Organisations and integrations"])


class Organisation(Model):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    website: str = Field(default="", max_length=500)


class Invitation(Email):
    role: Literal["viewer", "editor", "owner"] = "editor"


class Token(Model):
    name: str = Field(min_length=2, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=6)
    lifetime_days: int = Field(default=90, ge=1, le=365)


async def account(request):
    who = await principal(request)
    if who.token_id:
        raise HTTPException(403, "Sign in to manage memberships and integration credentials.")
    if not who.verified:
        raise HTTPException(403, "Verify your email first.")
    return who


@router.post("/organisations", status_code=201)
async def create_organisation(body: Organisation, request: Request):
    who = await account(request)
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(422, "Enter an organisation name.")
    identifier = uuid.uuid4()
    with store.engine().begin() as conn:
        # Existing names are never an ownership claim; an operator/invitation is needed.
        store.execute(conn, "SELECT pg_advisory_xact_lock(hashtext(:name))", name=name.lower())
        if store.one(conn, "SELECT id FROM cdm.publishers WHERE lower(trim(name))=:name", name=name.lower()):
            raise HTTPException(409, "This organisation already exists. Ask an owner for an invitation or request operator approval.")
        row = store.one(conn, """INSERT INTO cdm.publishers(id,name,contact_email,details,ckan_org_name)
            VALUES (:id,:name,:email,CAST(:details AS jsonb),:ckan) RETURNING id,name""",
            id=identifier, name=name, email=who.email,
            details=json.dumps({"description": body.description, "website": body.website}),
            ckan=f"publisher-{identifier.hex}")
        store.execute(conn, "INSERT INTO cdm.portal_memberships(user_id,publisher_id,role) VALUES (:user,:publisher,'owner')", user=who.user_id, publisher=identifier)
    return row


@router.get("/organisations/{organisation_id}/members")
async def members(organisation_id: uuid.UUID, request: Request):
    who = await account(request)
    with store.engine().connect() as conn:
        membership(conn, who, organisation_id, owner=True)
        return store.all_rows(conn, """SELECT u.id,u.email,m.role FROM cdm.portal_memberships m
            JOIN cdm.portal_users u ON u.id=m.user_id WHERE m.publisher_id=:p ORDER BY u.email""", p=organisation_id)


@router.post("/organisations/{organisation_id}/invitations", status_code=202)
async def invite(organisation_id: uuid.UUID, body: Invitation, request: Request):
    who = await account(request)
    recent(who)
    mail.configured()
    token = secrets.token_urlsafe(32)
    with store.engine().begin() as conn:
        membership(conn, who, organisation_id, owner=True)
        store.execute(conn, """INSERT INTO cdm.portal_invitations
            (token_hash,publisher_id,email,role,created_by,expires_at)
            VALUES (:hash,:publisher,:email,:role,:user,NOW()+INTERVAL '2 days')""",
            hash=digest(token), publisher=organisation_id, email=body.email, role=body.role, user=who.user_id)
        mail.enqueue(conn, body.email, "invite", token)
    return {"message": "Invitation email queued. The recipient must sign in with a verified matching address."}


@router.get("/organisations/{organisation_id}/invitations")
async def invitations(organisation_id: uuid.UUID, request: Request):
    who = await account(request)
    with store.engine().connect() as conn:
        membership(conn, who, organisation_id, owner=True)
        return store.all_rows(conn, """SELECT token_hash AS id,email,role,expires_at,accepted_at,revoked_at
            FROM cdm.portal_invitations WHERE publisher_id=:p ORDER BY expires_at DESC""", p=organisation_id)


@router.delete("/organisations/{organisation_id}/invitations/{invitation_id}")
async def revoke_invitation(organisation_id: uuid.UUID, invitation_id: str, request: Request):
    who = await account(request)
    recent(who)
    with store.engine().begin() as conn:
        membership(conn, who, organisation_id, owner=True)
        store.execute(conn, "UPDATE cdm.portal_invitations SET revoked_at=NOW() WHERE publisher_id=:p AND token_hash=:id", p=organisation_id, id=invitation_id)
    return {"message": "Invitation revoked."}


@router.post("/invitations/accept")
async def accept(body: Action, request: Request):
    who = await account(request)
    with store.engine().begin() as conn:
        row = store.one(conn, """UPDATE cdm.portal_invitations SET accepted_at=NOW()
            WHERE token_hash=:h AND email=:email AND expires_at>NOW()
            AND accepted_at IS NULL AND revoked_at IS NULL RETURNING publisher_id,role""", h=digest(body.token), email=who.email)
        if not row:
            raise HTTPException(403, "Invitation is invalid, expired, or belongs to another email address.")
        store.execute(conn, """INSERT INTO cdm.portal_memberships(user_id,publisher_id,role)
            VALUES (:u,:p,:role) ON CONFLICT(user_id,publisher_id) DO NOTHING""", u=who.user_id, p=row["publisher_id"], role=row["role"])
    return {"message": "Organisation joined."}


class Role(Model):
    role: Literal["owner", "editor", "viewer"]


def protect_last_owner(conn, publisher, user):
    # Lock all memberships to serialize concurrent owner removal/demotion.
    rows = store.all_rows(conn, "SELECT user_id,role FROM cdm.portal_memberships WHERE publisher_id=:p FOR UPDATE", p=publisher)
    owners = [str(row["user_id"]) for row in rows if row["role"] == "owner"]
    if str(user) in owners and len(owners) <= 1:
        raise HTTPException(409, "An organisation must retain at least one owner.")


@router.patch("/organisations/{organisation_id}/members/{user_id}")
async def change_role(organisation_id: uuid.UUID, user_id: uuid.UUID, body: Role, request: Request):
    who = await account(request)
    recent(who)
    with store.engine().begin() as conn:
        membership(conn, who, organisation_id, owner=True)
        if body.role != "owner":
            protect_last_owner(conn, organisation_id, user_id)
        store.execute(conn, "UPDATE cdm.portal_memberships SET role=:role WHERE publisher_id=:p AND user_id=:u", role=body.role, p=organisation_id, u=user_id)
    return {"message": "Role updated."}


@router.delete("/organisations/{organisation_id}/members/{user_id}")
async def remove_member(organisation_id: uuid.UUID, user_id: uuid.UUID, request: Request):
    who = await account(request)
    recent(who)
    with store.engine().begin() as conn:
        membership(conn, who, organisation_id, owner=True)
        protect_last_owner(conn, organisation_id, user_id)
        store.execute(conn, "DELETE FROM cdm.portal_memberships WHERE publisher_id=:p AND user_id=:u", p=organisation_id, u=user_id)
    return {"message": "Membership removed."}


@router.post("/organisations/{organisation_id}/tokens", status_code=201)
async def create_token(organisation_id: uuid.UUID, body: Token, request: Request):
    who = await account(request)
    recent(who)
    if not set(body.scopes) <= SCOPES:
        raise HTTPException(422, "An integration scope is unsupported.")
    raw = f"nod_{secrets.token_urlsafe(32)}"
    with store.engine().begin() as conn:
        membership(conn, who, organisation_id, owner=True)
        row = store.one(conn, """INSERT INTO cdm.portal_integration_tokens
            (publisher_id,name,token_hash,scopes,created_by,expires_at)
            VALUES (:p,:name,:hash,CAST(:scopes AS jsonb),:user,NOW()+make_interval(days=>:days)) RETURNING id""",
            p=organisation_id, name=body.name, hash=digest(raw), scopes=json.dumps(body.scopes), user=who.user_id, days=body.lifetime_days)
    # A new integration token is disclosed once, only to its authorised owner.
    return {"id": row["id"], "token": raw, "message": "Copy this token now. It cannot be retrieved later."}


@router.get("/organisations/{organisation_id}/tokens")
async def tokens(organisation_id: uuid.UUID, request: Request):
    who = await account(request)
    with store.engine().connect() as conn:
        membership(conn, who, organisation_id, owner=True)
        return store.all_rows(conn, """SELECT id,name,scopes,created_at,expires_at,revoked_at,legacy
            FROM cdm.portal_integration_tokens WHERE publisher_id=:p ORDER BY created_at DESC""", p=organisation_id)


@router.delete("/organisations/{organisation_id}/tokens/{token_id}")
async def revoke_token(organisation_id: uuid.UUID, token_id: uuid.UUID, request: Request):
    who = await account(request)
    recent(who)
    with store.engine().begin() as conn:
        membership(conn, who, organisation_id, owner=True)
        store.execute(conn, "UPDATE cdm.portal_integration_tokens SET revoked_at=NOW() WHERE id=:id AND publisher_id=:p", id=token_id, p=organisation_id)
    return {"message": "Integration token revoked."}
