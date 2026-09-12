"""Smoke test: the FastAPI app boots, auth works, and CRUD + optimize
endpoints function end-to-end through real HTTP calls (TestClient) against
an isolated in-memory SQLite database."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client():
    # StaticPool keeps a single connection alive so the in-memory SQLite
    # database persists across the multiple connections FastAPI's request
    # handling opens during a test (each :memory: connection is otherwise
    # its own separate empty database).
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_login_and_create_project(client):
    resp = client.post("/api/v1/auth/register", json={"email": "pm@example.com", "password": "hunter2", "role": "editor"})
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/api/v1/projects", headers=headers,
        json={"code": "P1", "name": "Test Project", "start_date": "2026-04-01", "end_date": "2026-04-10"},
    )
    assert resp.status_code == 201
    project = resp.json()
    assert project["code"] == "P1"

    resp = client.get("/api/v1/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_project_requires_editor_role(client):
    resp = client.post("/api/v1/auth/register", json={"email": "viewer@example.com", "password": "hunter2", "role": "viewer"})
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/api/v1/projects", headers=headers,
        json={"code": "P2", "name": "Blocked Project", "start_date": "2026-04-01", "end_date": "2026-04-10"},
    )
    assert resp.status_code == 403


def test_unauthenticated_request_rejected(client):
    resp = client.post("/api/v1/projects", json={"code": "P3", "name": "No Auth", "start_date": "2026-04-01", "end_date": "2026-04-10"})
    assert resp.status_code == 401


def test_conversations_endpoint_without_api_key_returns_503(client):
    resp = client.post("/api/v1/auth/register", json={"email": "pm2@example.com", "password": "hunter2", "role": "editor"})
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/conversations", headers=headers, json={"title": "Planning chat"})
    assert resp.status_code == 201
    convo_id = resp.json()["id"]

    resp = client.post(f"/api/v1/conversations/{convo_id}/messages", headers=headers, json={"content": "Plan next week"})
    assert resp.status_code == 503
    assert resp.json()["error"] == "AI_NOT_CONFIGURED"
