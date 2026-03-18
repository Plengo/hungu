"""
tests/test_admin.py
────────────────────
Tests for the admin dashboard endpoint and access control.
"""

import pytest
from conftest import make_article


class TestAdminDashboard:
    def test_dashboard_returns_200_with_valid_key(self, client, admin_headers):
        resp = client.get("/admin/dashboard", headers=admin_headers)
        assert resp.status_code == 200

    def test_dashboard_returns_401_without_key(self, client):
        resp = client.get("/admin/dashboard")
        assert resp.status_code == 401

    def test_dashboard_returns_401_with_wrong_key(self, client):
        resp = client.get("/admin/dashboard", headers={"X-Admin-Key": "wrong"})
        assert resp.status_code == 401

    def test_dashboard_contains_expected_fields(self, client, admin_headers):
        resp = client.get("/admin/dashboard", headers=admin_headers)
        data = resp.json()
        for field in ["total_views", "unique_visitors", "active_last_15min",
                      "daily_active", "total_articles", "articles_enriched",
                      "articles_pending", "total_bookmarks",
                      "articles_by_category", "recent_articles"]:
            assert field in data, f"Missing field: {field}"

    def test_dashboard_counts_articles(self, client, admin_headers, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Admin Count Test", "raw_text": "admin body"}),
                    headers=worker_headers)
        resp = client.get("/admin/dashboard", headers=admin_headers)
        assert resp.json()["total_articles"] >= 1

    def test_dashboard_category_breakdown(self, client, admin_headers, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Politics Item",
                                       "category": "Politics",
                                       "raw_text": "pol body"}),
                    headers=worker_headers)
        resp = client.get("/admin/dashboard", headers=admin_headers)
        cats = resp.json()["articles_by_category"]
        assert "Politics" in cats
        assert cats["Politics"] >= 1

    def test_dashboard_recent_articles_format(self, client, admin_headers, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Recent Format Test",
                                       "raw_text": "recent body"}),
                    headers=worker_headers)
        resp = client.get("/admin/dashboard", headers=admin_headers)
        recent = resp.json()["recent_articles"]
        assert len(recent) >= 1
        art = recent[0]
        for field in ["id", "title", "category", "source", "created_at", "enriched"]:
            assert field in art


class TestArchiveOld:
    def test_archive_requires_worker_key(self, client):
        resp = client.post("/admin/archive-old")
        assert resp.status_code == 401

    def test_archive_runs_with_worker_key(self, client, worker_headers):
        resp = client.post("/admin/archive-old", headers=worker_headers)
        assert resp.status_code == 200
        assert "archived" in resp.json()
