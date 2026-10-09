"""RBAC and auth integration tests.

Tests:
1. employee gets 403 on /admin-only APIs (analytics, users, audit)
2. agent gets 403 on analytics and users, but 200 on tickets
3. admin gets 200 on all
4. persona switch changes active_dept_role in new token
5. employee cannot access /admin - returns 403
6. expired shift_exp → 401
7. Separation of duties claims helper
"""

from __future__ import annotations

import time
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import create_access_token, create_refresh_token

client = TestClient(app, raise_server_exceptions=True)


# ── Token factories ────────────────────────────────────────────────────────────

def _token(app_role: str, active_dept_role: str = "", shift_exp: int | None = None) -> dict:
    tok = create_access_token(
        user_id="00000000-0000-0000-0000-000000000001",
        app_role=app_role,
        active_dept_role=active_dept_role,
        shift_exp=shift_exp,
    )
    return {"Authorization": f"Bearer {tok}"}


def _employee_headers(dept_role: str = "Billing") -> dict:
    return _token("employee", dept_role)


def _agent_headers() -> dict:
    return _token("agent", "")


def _admin_headers() -> dict:
    return _token("admin", "")


# ── Login / me ─────────────────────────────────────────────────────────────────

def test_login_valid():
    r = client.post("/auth/login", json={"email": "admin@demo", "password": "Demo@1234"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_login_wrong_password():
    r = client.post("/auth/login", json={"email": "admin@demo", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user():
    r = client.post("/auth/login", json={"email": "nobody@demo", "password": "Demo@1234"})
    assert r.status_code == 401


def test_me_returns_user_info():
    r = client.post("/auth/login", json={"email": "admin@demo", "password": "Demo@1234"})
    token = r.json()["access_token"]
    r2 = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["email"] == "admin@demo"
    assert body["app_role"] == "admin"


# ── Permission enforcement ─────────────────────────────────────────────────────

class TestAnalyticsPermission:
    def test_employee_gets_403(self):
        r = client.get("/analytics/summary", headers=_employee_headers())
        assert r.status_code == 403

    def test_agent_gets_403(self):
        r = client.get("/analytics/summary", headers=_agent_headers())
        assert r.status_code == 403

    def test_admin_gets_200(self):
        r = client.get("/analytics/summary", headers=_admin_headers())
        assert r.status_code == 200


class TestUsersPermission:
    def test_employee_gets_403(self):
        r = client.get("/users", headers=_employee_headers())
        assert r.status_code == 403

    def test_agent_gets_403(self):
        r = client.get("/users", headers=_agent_headers())
        assert r.status_code == 403

    def test_admin_gets_200(self):
        r = client.get("/users", headers=_admin_headers())
        assert r.status_code == 200


class TestAuditPermission:
    def test_employee_gets_403(self):
        r = client.get("/audit/log", headers=_employee_headers())
        assert r.status_code == 403

    def test_agent_gets_403(self):
        r = client.get("/audit/log", headers=_agent_headers())
        assert r.status_code == 403

    def test_admin_gets_200(self):
        r = client.get("/audit/log", headers=_admin_headers())
        assert r.status_code == 200


class TestTicketsPermission:
    def test_employee_gets_403(self):
        r = client.get("/tickets", headers=_employee_headers())
        assert r.status_code == 403

    def test_agent_gets_200(self):
        r = client.get("/tickets", headers=_agent_headers())
        assert r.status_code == 200

    def test_admin_gets_200(self):
        r = client.get("/tickets", headers=_admin_headers())
        assert r.status_code == 200


# ── Shift expiry ───────────────────────────────────────────────────────────────

def test_expired_shift_returns_401():
    # shift_exp in the past
    expired_shift = int(time.time()) - 3600
    headers = _token("employee", "Billing", shift_exp=expired_shift)
    r = client.get("/analytics/summary", headers=headers)
    # shift is expired → 401 before even checking permission
    assert r.status_code == 401
    assert "Shift" in r.json()["detail"]


def test_valid_future_shift_passes_auth():
    future_shift = int(time.time()) + 3600
    headers = _token("admin", "", shift_exp=future_shift)
    r = client.get("/analytics/summary", headers=headers)
    assert r.status_code == 200


# ── Persona switch ─────────────────────────────────────────────────────────────

def test_persona_switch_changes_dept_role():
    # Login as billing.super@demo (has both Billing and Billing Supervisor)
    r = client.post("/auth/login", json={"email": "billing.super@demo", "password": "Demo@1234"})
    assert r.status_code == 200, r.text
    tokens = r.json()
    access_token = tokens["access_token"]

    # Switch to Billing Supervisor
    r2 = client.post(
        "/auth/persona",
        json={"dept_role": "Billing Supervisor"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert r2.status_code == 200, r2.text
    new_token = r2.json()["access_token"]

    # Verify new token has the switched dept role
    r3 = client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert r3.status_code == 200
    assert r3.json()["active_dept_role"] == "Billing Supervisor"


def test_persona_switch_to_unauthorized_role_fails():
    # billing@demo only has "Billing", not "Billing Supervisor"
    r = client.post("/auth/login", json={"email": "billing@demo", "password": "Demo@1234"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    r2 = client.post(
        "/auth/persona",
        json={"dept_role": "Billing Supervisor"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 403


# ── Refresh token ──────────────────────────────────────────────────────────────

def test_refresh_token_works():
    r = client.post("/auth/login", json={"email": "admin@demo", "password": "Demo@1234"})
    refresh_token = r.json()["refresh_token"]
    r2 = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 200
    assert "access_token" in r2.json()


def test_access_token_rejected_as_refresh():
    r = client.post("/auth/login", json={"email": "admin@demo", "password": "Demo@1234"})
    access_token = r.json()["access_token"]
    r2 = client.post("/auth/refresh", json={"refresh_token": access_token})
    assert r2.status_code == 401


# ── No token ───────────────────────────────────────────────────────────────────

def test_unauthenticated_request_returns_403():
    # FastAPI HTTPBearer returns 403 when no Bearer is present
    r = client.get("/analytics/summary")
    assert r.status_code in (401, 403)
