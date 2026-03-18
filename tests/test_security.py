"""
tests/test_security.py
──────────────────────
Security-focused tests: JWT expiry, cross-user access, missing keys,
worker key enforcement.  All based on OWASP broken-access-control checklist.
"""

import os
import datetime
import pytest
from jose import jwt

from conftest import make_article


JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO   = "HS256"


def _make_expired_token(user_id: str) -> str:
    """Produce a token that expired 1 second ago."""
    exp = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    return jwt.encode({"sub": str(user_id), "exp": exp}, JWT_SECRET, algorithm=JWT_ALGO)


def _make_token_for(user_id: str) -> str:
    """Produce a valid token for any arbitrary user_id (bypasses device flow)."""
    exp = datetime.datetime.utcnow() + datetime.timedelta(days=1)
    return jwt.encode({"sub": str(user_id), "exp": exp}, JWT_SECRET, algorithm=JWT_ALGO)


class TestJWTSecurity:
    def test_expired_token_returns_401(self, client, device_user):
        token   = _make_expired_token(device_user["user_id"])
        headers = {"Authorization": f"Bearer {token}"}
        resp    = client.get(f"/user/{device_user['user_id']}/bookmarks", headers=headers)
        assert resp.status_code == 401

    def test_no_bearer_prefix_returns_401(self, client, device_user):
        resp = client.get(
            f"/user/{device_user['user_id']}/bookmarks",
            headers={"Authorization": device_user["token"]},  # missing "Bearer "
        )
        assert resp.status_code == 401

    def test_tampered_token_returns_401(self, client, device_user):
        parts   = device_user["token"].split(".")
        tampered = parts[0] + "." + parts[1] + ".badsignature"
        resp    = client.get(
            f"/user/{device_user['user_id']}/bookmarks",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert resp.status_code == 401

    def test_cross_user_bookmark_returns_403(self, client):
        user_a = client.post("/auth/device").json()
        user_b = client.post("/auth/device").json()
        token_a = user_a["token"]
        resp = client.get(
            f"/user/{user_b['user_id']}/bookmarks",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    def test_cross_user_subscription_returns_403(self, client):
        user_a = client.post("/auth/device").json()
        user_b = client.post("/auth/device").json()
        resp = client.get(
            f"/user/{user_b['user_id']}/subscription",
            headers={"Authorization": f"Bearer {user_a['token']}"},
        )
        assert resp.status_code == 403


class TestWorkerKeySecurity:
    def test_post_article_no_key_returns_401(self, client):
        resp = client.post("/articles", json=make_article())
        assert resp.status_code == 401

    def test_post_article_wrong_key_returns_401(self, client):
        resp = client.post(
            "/articles",
            json=make_article(),
            headers={"X-Worker-Key": "wrong-key-here"},
        )
        assert resp.status_code == 401

    def test_archive_no_key_returns_401(self, client):
        resp = client.post("/admin/archive-old")
        assert resp.status_code == 401

    def test_dispatch_no_key_returns_401(self, client):
        resp = client.post("/internal/notifications/dispatch",
                           json={"article_ids": []})
        assert resp.status_code == 401

    def test_hash_check_no_key_returns_401(self, client):
        resp = client.get("/articles/hash/abc123")
        assert resp.status_code == 401


class TestHealthEndpoint:
    def test_health_is_public(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_feed_is_public(self, client):
        resp = client.get("/feed")
        assert resp.status_code == 200
