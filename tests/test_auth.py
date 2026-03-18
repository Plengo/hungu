"""
tests/test_auth.py
──────────────────
Tests for anonymous device user creation and JWT authentication.
"""

import pytest


class TestDeviceUserCreation:
    def test_create_device_user_returns_201(self, client):
        resp = client.post("/auth/device")
        assert resp.status_code == 201

    def test_response_contains_user_id_and_token(self, client):
        resp = client.post("/auth/device")
        data = resp.json()
        assert "user_id" in data
        assert "token"   in data
        assert len(data["user_id"]) == 36   # UUID format
        assert len(data["token"])   > 20

    def test_each_call_creates_unique_user(self, client):
        uid1 = client.post("/auth/device").json()["user_id"]
        uid2 = client.post("/auth/device").json()["user_id"]
        assert uid1 != uid2

    def test_token_grants_access_to_own_bookmarks(self, client):
        data    = client.post("/auth/device").json()
        headers = {"Authorization": f"Bearer {data['token']}"}
        resp    = client.get(f"/user/{data['user_id']}/bookmarks", headers=headers)
        assert resp.status_code == 200

    def test_missing_token_returns_401(self, client, device_user):
        resp = client.get(f"/user/{device_user['user_id']}/bookmarks")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client, device_user):
        bad_headers = {"Authorization": "Bearer this.is.not.a.valid.jwt"}
        resp = client.get(
            f"/user/{device_user['user_id']}/bookmarks",
            headers=bad_headers,
        )
        assert resp.status_code == 401

    def test_wrong_user_token_returns_403(self, client):
        """User A's token must not grant access to User B's data."""
        user_a = client.post("/auth/device").json()
        user_b = client.post("/auth/device").json()
        headers_a = {"Authorization": f"Bearer {user_a['token']}"}
        resp = client.get(f"/user/{user_b['user_id']}/bookmarks", headers=headers_a)
        assert resp.status_code == 403
