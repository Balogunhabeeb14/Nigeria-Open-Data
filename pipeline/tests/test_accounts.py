from fastapi.testclient import TestClient
from sqlalchemy import text
from pipeline.api import app
from pipeline.tests.conftest import action_token, sign_in, upload


def test_registration_verification_session_logout_expiry(client, portal):
    password = sign_in(client, portal, verified=False)
    assert client.get("/api/auth/me").json()["verified"] is False
    assert client.post("/api/portal/organisations", json={"name": "Blocked"}).status_code == 403
    token = action_token(portal, "owner@example.org")
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 200
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 400
    assert client.get("/api/auth/me").json()["verified"] is True
    with portal.begin() as conn:
        encoded = conn.execute(text("SELECT password_hash FROM cdm.portal_users")).scalar_one()
        assert password not in encoded and encoded.startswith("$argon2id$")
        assert client.cookies["nod_session"] not in conn.execute(text("SELECT token_hash FROM cdm.portal_sessions")).scalar_one()
        conn.execute(text("UPDATE cdm.portal_sessions SET expires_at=NOW()-INTERVAL '1 second'"))
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@example.org", "password": password}).status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies["nod_csrf"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_recovery_invalidates_sessions_and_is_single_use(client, portal):
    sign_in(client, portal)
    assert client.post("/api/auth/recover", json={"email": "owner@example.org"}).status_code == 202
    body = {"token": action_token(portal, "owner@example.org", "reset"), "password": "Changed-fixture-password-123"}
    assert client.post("/api/auth/reset", json=body).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/reset", json=body).status_code == 400
    assert client.post("/api/auth/login", json={"email": "owner@example.org", "password": body["password"]}).status_code == 200


def test_csrf_origin_and_validation_do_not_leak_credentials(client, owner):
    assert client.post("/api/portal/organisations", json={"name": "CSRF"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/portal/organisations", json={"name": "Origin"}, headers={"Origin": "https://attacker.invalid"}).status_code == 403
    secret = "never-return-this-password"
    result = client.post("/api/auth/login", json={"email": "invalid", "password": secret})
    assert result.status_code == 422 and secret not in result.text
    assert result.headers["Cache-Control"] == "no-store"
    assert client.post("/api/auth/login", content=b" " * 9000, headers={"Content-Type": "application/json"}).status_code == 413


def test_login_rate_limit(client):
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": "absent@example.org", "password": "bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "absent@example.org", "password": "bad"}).status_code == 429


def test_cross_organisation_and_existing_name_do_not_grant_access(client, portal, owner):
    result = upload(client, owner)
    assert result.status_code == 202
    dataset = result.json()["dataset_id"]
    with TestClient(app, base_url="http://localhost:3000", headers={"Origin": "http://localhost:3000"}) as other:
        sign_in(other, portal, "outsider@example.org")
        assert other.post("/api/portal/organisations", json={"name": "Fixture organisation"}).status_code == 409
        assert other.get(f"/api/portal/datasets/{dataset}").status_code == 403
        assert upload(other, owner).status_code == 403
        assert other.post(f"/api/portal/datasets/{dataset}/ingest").status_code == 403
        assert other.post(f"/api/portal/datasets/{dataset}/publish", json={"reviewed": True}).status_code == 403
        assert other.get(f"/api/portal/jobs/{result.json()['job_id']}").status_code == 403
        assert other.get(f"/api/portal/organisations/{owner}/tokens").status_code == 403


def test_last_owner_reauthentication_and_revocable_tokens(client, portal, owner):
    user = client.get(f"/api/portal/organisations/{owner}/members").json()[0]["id"]
    assert client.delete(f"/api/portal/organisations/{owner}/members/{user}").status_code == 409
    with portal.begin() as conn:
        conn.execute(text("UPDATE cdm.portal_sessions SET authenticated_at=NOW()-INTERVAL '16 minutes'"))
    body = {"name": "Fixture automation", "scopes": ["datasets:read"]}
    result = client.post(f"/api/portal/organisations/{owner}/tokens", json=body)
    assert result.status_code == 401 and result.headers["X-Reauthentication-Required"] == "true"
    assert client.post("/api/auth/reauthenticate", json={"password": "Long-fixture-password-123"}).status_code == 200
    result = client.post(f"/api/portal/organisations/{owner}/tokens", json=body)
    assert result.status_code == 201
    token = result.json()["token"]
    assert token not in client.get(f"/api/portal/organisations/{owner}/tokens").text
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/api/portal/datasets?organisation_id={owner}", headers=headers).status_code == 200
    assert client.post("/api/portal/datasets", headers=headers, json={}).status_code in {403, 422}
    assert client.delete(f"/api/portal/organisations/{owner}/tokens/{result.json()['id']}").status_code == 200
    assert client.get(f"/api/portal/datasets?organisation_id={owner}", headers=headers).status_code == 401


def test_invitation_matches_verified_email_and_viewer_cannot_write(client, portal, owner):
    assert client.post(f"/api/portal/organisations/{owner}/invitations", json={"email": "viewer@example.org", "role": "viewer"}).status_code == 202
    token = action_token(portal, "viewer@example.org", "invite")
    assert client.post("/api/portal/invitations/accept", json={"token": token}).status_code == 403
    sign_in(client, portal, "viewer@example.org")
    assert client.post("/api/portal/invitations/accept", json={"token": token}).status_code == 200
    assert client.post("/api/portal/invitations/accept", json={"token": token}).status_code == 403
    assert client.get(f"/api/portal/datasets?organisation_id={owner}").status_code == 200
    assert upload(client, owner).status_code == 403
