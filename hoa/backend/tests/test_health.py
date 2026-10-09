"""Smoke tests for health endpoints."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_livez():
    resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
