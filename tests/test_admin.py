"""
tests/test_admin.py
────────────────────
Tests for:
  - GET   /admin/dashboard                  — full platform stats (admin key)
  - POST  /admin/archive-old                — archive articles older than 30 days
  - PATCH /admin/articles/{id}/urgent       — toggle urgent / breaking news flag
  - DELETE /admin/articles/{id}             — delete an article
  - PATCH /admin/articles/{id}/rescan       — wipe AI fields so worker re-enriches
"""

import pytest
import uuid
from conftest import make_article


# ─── Dashboard ────────────────────────────────────────────────────────────────

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
                    json=make_article({"title": "Admin Count Test",
                                       "raw_text": "admin body"}),
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


# ─── Archive old ──────────────────────────────────────────────────────────────

class TestArchiveOld:
    def test_archive_requires_worker_key(self, client):
        resp = client.post("/admin/archive-old")
        assert resp.status_code == 401

    def test_archive_runs_with_worker_key(self, client, worker_headers):
        resp = client.post("/admin/archive-old", headers=worker_headers)
        assert resp.status_code == 200
        assert "archived" in resp.json()

    def test_archive_count_is_integer(self, client, worker_headers):
        resp = client.post("/admin/archive-old", headers=worker_headers)
        assert isinstance(resp.json()["archived"], int)


# ─── Toggle urgent ────────────────────────────────────────────────────────────

class TestToggleUrgent:
    def test_toggle_urgent_requires_admin(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Urgent Auth Test",
                                                  "raw_text": "urgent body"}),
                               headers=worker_headers).json()
        resp = client.patch(f"/admin/articles/{created['id']}/urgent",
                            json={"urgent": True})
        assert resp.status_code == 401

    def test_toggle_urgent_initially_sets_flag(self, client, admin_headers, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Urgent Toggle Article",
                                                  "raw_text": "toggle urgent body"}),
                               headers=worker_headers).json()
        resp = client.patch(f"/admin/articles/{created['id']}/urgent",
                            json={"urgent": True},
                            headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["urgent"] is True

    def test_toggle_urgent_twice_returns_false(self, client, admin_headers, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Double Toggle Article",
                                                  "raw_text": "double toggle body"}),
                               headers=worker_headers).json()
        art_id = created["id"]
        client.patch(f"/admin/articles/{art_id}/urgent",
                     json={"urgent": True}, headers=admin_headers)
        resp = client.patch(f"/admin/articles/{art_id}/urgent",
                            json={"urgent": True}, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["urgent"] is False

    def test_toggle_urgent_nonexistent_returns_404(self, client, admin_headers):
        resp = client.patch(f"/admin/articles/{uuid.uuid4()}/urgent",
                            json={"urgent": True}, headers=admin_headers)
        assert resp.status_code == 404


# ─── Delete article ───────────────────────────────────────────────────────────

class TestDeleteArticle:
    def test_delete_article_requires_admin(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Delete Auth Test",
                                                  "raw_text": "delete auth body"}),
                               headers=worker_headers).json()
        resp = client.delete(f"/admin/articles/{created['id']}")
        assert resp.status_code == 401

    def test_delete_article_succeeds(self, client, admin_headers, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Delete Me Article",
                                                  "raw_text": "delete me body"}),
                               headers=worker_headers).json()
        resp = client.delete(f"/admin/articles/{created['id']}",
                             headers=admin_headers)
        assert resp.status_code == 204

    def test_deleted_article_absent_from_feed(self, client, admin_headers, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Gone Article Unique XYZ",
                                                  "raw_text": "gone body xyz"}),
                               headers=worker_headers).json()
        client.delete(f"/admin/articles/{created['id']}", headers=admin_headers)
        feed = client.get("/feed").json()
        ids = [a["id"] for a in feed]
        assert created["id"] not in ids

    def test_delete_nonexistent_article_returns_404(self, client, admin_headers):
        resp = client.delete(f"/admin/articles/{uuid.uuid4()}",
                             headers=admin_headers)
        assert resp.status_code == 404

    def test_delete_via_wrong_key_returns_401(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Worker Key Delete Test",
                                                  "raw_text": "worker key delete body"}),
                               headers=worker_headers).json()
        # worker key must not grant delete access
        resp = client.delete(f"/admin/articles/{created['id']}",
                             headers={"X-Worker-Key": "test-worker-key"})
        assert resp.status_code == 401


# ─── Rescan (wipe enrichment) ─────────────────────────────────────────────────

class TestRescanArticle:
    def test_rescan_requires_admin(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Rescan Auth Test",
                                                  "raw_text": "rescan auth body"}),
                               headers=worker_headers).json()
        resp = client.patch(f"/admin/articles/{created['id']}/rescan")
        assert resp.status_code == 401

    def test_rescan_returns_reset_status(self, client, admin_headers, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Rescan Return Test",
                                                  "raw_text": "rescan return body"}),
                               headers=worker_headers).json()
        resp = client.patch(f"/admin/articles/{created['id']}/rescan",
                            headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"

    def test_rescan_wipes_enrichment_fields(self, client, admin_headers, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Rescan Wipe Test",
                                                  "raw_text": "rescan wipe body"}),
                               headers=worker_headers).json()
        # Enrich it first
        client.patch(f"/articles/{created['id']}/enrich",
                     json={"summary": "Rich summary.", "actions_now": "Take action."},
                     headers=worker_headers)
        # Rescan should wipe it
        client.patch(f"/admin/articles/{created['id']}/rescan",
                     headers=admin_headers)
        art = client.get(f"/article/{created['id']}").json()
        assert not art.get("actions_now")

    def test_rescan_nonexistent_returns_404(self, client, admin_headers):
        resp = client.patch(f"/admin/articles/{uuid.uuid4()}/rescan",
                            headers=admin_headers)
        assert resp.status_code == 404

    def test_rescan_article_reappears_in_enrichment_queue(self, client, admin_headers, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Rescan Queue Test",
                                                  "raw_text": "rescan queue body"}),
                               headers=worker_headers).json()
        art_id = created["id"]
        # Enrich
        client.patch(f"/articles/{art_id}/enrich",
                     json={"actions_now": "Do this.", "impact": "Big."},
                     headers=worker_headers)
        # Confirm not in queue
        queue_before = [a["id"] for a in
                        client.get("/articles/needs-enrichment",
                                   headers=worker_headers).json()]
        assert art_id not in queue_before
        # Rescan
        client.patch(f"/admin/articles/{art_id}/rescan", headers=admin_headers)
        # Should reappear
        queue_after = [a["id"] for a in
                       client.get("/articles/needs-enrichment",
                                  headers=worker_headers).json()]
        assert art_id in queue_after
