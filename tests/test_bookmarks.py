"""
tests/test_bookmarks.py
────────────────────────
Tests for the bookmarks (saved posts) feature.
"""

import pytest
from conftest import make_article


class TestBookmarks:
    def test_get_bookmarks_empty_on_new_user(self, client, device_user, auth_headers):
        resp = client.get(f"/user/{device_user['user_id']}/bookmarks",
                          headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_add_bookmark(self, client, device_user, auth_headers, worker_headers):
        art = client.post("/articles", json=make_article(), headers=worker_headers).json()
        resp = client.post(
            f"/user/{device_user['user_id']}/bookmark/{art['id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "saved"

    def test_add_bookmark_appears_in_get(self, client, device_user, auth_headers, worker_headers):
        art = client.post("/articles",
                          json=make_article({"title": "Bookmark Me", "raw_text": "bm body"}),
                          headers=worker_headers).json()
        client.post(f"/user/{device_user['user_id']}/bookmark/{art['id']}",
                    headers=auth_headers)
        bks = client.get(f"/user/{device_user['user_id']}/bookmarks",
                         headers=auth_headers).json()
        ids = [b["article_ref"] for b in bks]
        assert art["id"] in ids

    def test_add_bookmark_idempotent(self, client, device_user, auth_headers, worker_headers):
        art = client.post("/articles",
                          json=make_article({"title": "Idempotent BM", "raw_text": "idm body"}),
                          headers=worker_headers).json()
        r1 = client.post(f"/user/{device_user['user_id']}/bookmark/{art['id']}",
                         headers=auth_headers)
        r2 = client.post(f"/user/{device_user['user_id']}/bookmark/{art['id']}",
                         headers=auth_headers)
        assert r1.status_code == 201
        assert r2.status_code == 201  # idempotent — still 201

    def test_remove_bookmark(self, client, device_user, auth_headers, worker_headers):
        art = client.post("/articles",
                          json=make_article({"title": "Remove BM", "raw_text": "rm body"}),
                          headers=worker_headers).json()
        client.post(f"/user/{device_user['user_id']}/bookmark/{art['id']}",
                    headers=auth_headers)
        resp = client.delete(f"/user/{device_user['user_id']}/bookmark/{art['id']}",
                             headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"
        # Verify removed
        bks = client.get(f"/user/{device_user['user_id']}/bookmarks",
                         headers=auth_headers).json()
        assert art["id"] not in [b["article_ref"] for b in bks]

    def test_cross_user_bookmark_access_denied(self, client, worker_headers):
        user_a = client.post("/auth/device").json()
        user_b = client.post("/auth/device").json()
        headers_a = {"Authorization": f"Bearer {user_a['token']}"}
        # User A tries to read User B's bookmarks
        resp = client.get(f"/user/{user_b['user_id']}/bookmarks", headers=headers_a)
        assert resp.status_code == 403
