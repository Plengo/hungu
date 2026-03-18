"""
tests/conftest.py
─────────────────
Shared pytest fixtures for the HUNGU API test suite.

Uses an in-memory SQLite database so tests never touch the real PostgreSQL
instance.  The production models use dialect-agnostic TypeDecorators so
SQLite and PostgreSQL are both supported without any patching.
"""

import os
import uuid
import datetime
import pytest

# ── Set env vars BEFORE importing any module that reads them at import time ────
os.environ["DB_URL"]         = "sqlite:///:memory:"
os.environ["JWT_SECRET"]     = "test-jwt-secret-do-not-use-in-prod"
os.environ["WORKER_API_KEY"] = "test-worker-key"

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "api"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from db import Base, get_db
from main import app

# ── SQLite in-memory engine ────────────────────────────────────────────────────
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once for the whole test session."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def db_session():
    """Yields a DB session per test, rolling back after the test."""
    connection = _engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    """FastAPI TestClient wired to the test DB session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Auth helpers ───────────────────────────────────────────────────────────────

@pytest.fixture()
def device_user(client):
    """Creates a device user and returns {user_id, token}."""
    resp = client.post("/auth/device")
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def auth_headers(device_user):
    """Returns Authorization header dict for the device user."""
    return {"Authorization": f"Bearer {device_user['token']}"}


@pytest.fixture()
def worker_headers():
    """Returns X-Worker-Key header dict."""
    return {
        "X-Worker-Key":  os.environ["WORKER_API_KEY"],
        "Content-Type":  "application/json",
    }


# ── Sample article factory ─────────────────────────────────────────────────────

def make_article(overrides: dict = None) -> dict:
    base = {
        "title":         "Test Article Title",
        "source":        "Test Source",
        "category":      "Politics",
        "location_tier": "Country",
        "location_name": "South Africa",
        "summary":       "Test summary.",
        "full_context":  "Test full context.",
        "impact":        "Test impact.",
        "url":           "https://example.com/test-article",
        "urgent":        False,
        "raw_text":      "Some test raw text content for hashing.",
    }
    if overrides:
        base.update(overrides)
    return base
