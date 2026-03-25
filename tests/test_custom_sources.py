"""
tests/test_custom_sources.py
──────────────────────────────
Tests for:
  - POST   /admin/scrape-sources          — admin adds a custom RSS source
  - GET    /admin/scrape-sources          — admin lists all sources
  - DELETE /admin/scrape-sources/{id}     — admin removes a source
  - GET    /worker/scrape-sources         — worker fetches active sources
  - POST   /admin/story-queue             — admin queues story links for worker
  - GET    /admin/story-queue             — admin views story queue
  - GET    /worker/story-queue            — worker fetches pending stories
  - PATCH  /worker/story-queue/{id}/done  — worker marks story processed
"""

import pytest


# ─── Scrape sources ───────────────────────────────────────────────────────────

class TestScrapeSources:
    def test_add_source_requires_admin(self, client):
        resp = client.post("/admin/scrape-sources",
                           json={"url": "https://example.com/feed", "label": "Test"})
        assert resp.status_code == 401

    def test_add_source_creates_entry(self, client, admin_headers):
        resp = client.post("/admin/scrape-sources",
                           json={"url": "https://test-feed.example.com/rss",
                                 "label": "Test Feed"},
                           headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"]   == "https://test-feed.example.com/rss"
        assert data["label"] == "Test Feed"
        assert "id" in data

    def test_add_source_without_url_returns_422(self, client, admin_headers):
        resp = client.post("/admin/scrape-sources",
                           json={"label": "No URL here"},
                           headers=admin_headers)
        assert resp.status_code == 422

    def test_add_source_label_defaults_to_url(self, client, admin_headers):
        url = "https://nolabel.example.com/rss"
        resp = client.post("/admin/scrape-sources",
                           json={"url": url},
                           headers=admin_headers)
        assert resp.status_code == 201
        assert resp.json()["label"] == url

    def test_list_sources_requires_admin(self, client):
        resp = client.get("/admin/scrape-sources")
        assert resp.status_code == 401

    def test_list_sources_returns_added(self, client, admin_headers):
        client.post("/admin/scrape-sources",
                    json={"url": "https://list-test.example.com/rss",
                          "label": "List Test Feed"},
                    headers=admin_headers)
        resp = client.get("/admin/scrape-sources", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        urls = [s["url"] for s in resp.json()]
        assert "https://list-test.example.com/rss" in urls

    def test_list_sources_shape(self, client, admin_headers):
        client.post("/admin/scrape-sources",
                    json={"url": "https://shape-test.example.com/rss"},
                    headers=admin_headers)
        sources = client.get("/admin/scrape-sources", headers=admin_headers).json()
        assert len(sources) >= 1
        for field in ["id", "url", "label", "active"]:
            assert field in sources[0], f"Missing source field: {field}"

    def test_add_duplicate_source_reactivates(self, client, admin_headers):
        url = "https://dedup-source.example.com/rss"
        client.post("/admin/scrape-sources", json={"url": url}, headers=admin_headers)
        resp = client.post("/admin/scrape-sources", json={"url": url},
                           headers=admin_headers)
        assert resp.status_code == 201
        assert resp.json()["active"] is True

    def test_delete_source_requires_admin(self, client, admin_headers):
        created = client.post("/admin/scrape-sources",
                               json={"url": "https://delete-auth.example.com/rss"},
                               headers=admin_headers).json()
        resp = client.delete(f"/admin/scrape-sources/{created['id']}")
        assert resp.status_code == 401

    def test_delete_source_succeeds(self, client, admin_headers):
        created = client.post("/admin/scrape-sources",
                               json={"url": "https://delete-me.example.com/rss"},
                               headers=admin_headers).json()
        resp = client.delete(f"/admin/scrape-sources/{created['id']}",
                             headers=admin_headers)
        assert resp.status_code == 204

    def test_delete_nonexistent_source_returns_404(self, client, admin_headers):
        import uuid
        resp = client.delete(f"/admin/scrape-sources/{uuid.uuid4()}",
                             headers=admin_headers)
        assert resp.status_code == 404

    def test_worker_scrape_sources_requires_worker_key(self, client):
        resp = client.get("/worker/scrape-sources")
        assert resp.status_code == 401

    def test_worker_scrape_sources_returns_active(self, client, admin_headers, worker_headers):
        client.post("/admin/scrape-sources",
                    json={"url": "https://worker-active.example.com/rss",
                          "label": "Worker Active Feed"},
                    headers=admin_headers)
        resp = client.get("/worker/scrape-sources", headers=worker_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        urls = [s["url"] for s in resp.json()]
        assert "https://worker-active.example.com/rss" in urls


# ─── Story queue ──────────────────────────────────────────────────────────────

class TestStoryQueue:
    def test_add_story_link_requires_admin(self, client):
        resp = client.post("/admin/story-queue",
                           json={"urls": ["https://story.example.com/1"]})
        assert resp.status_code == 401

    def test_add_story_links_creates_entries(self, client, admin_headers):
        resp = client.post("/admin/story-queue",
                           json={"urls": ["https://story.example.com/a",
                                          "https://story.example.com/b"],
                                 "label": "Test stories"},
                           headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["queued"] == 2
        assert len(data["urls"]) == 2

    def test_add_story_single_url_string(self, client, admin_headers):
        resp = client.post("/admin/story-queue",
                           json={"urls": "https://story.example.com/single",
                                 "label": "Single story"},
                           headers=admin_headers)
        assert resp.status_code == 201
        assert resp.json()["queued"] >= 1

    def test_list_story_queue_requires_admin(self, client):
        resp = client.get("/admin/story-queue")
        assert resp.status_code == 401

    def test_list_story_queue_shows_added(self, client, admin_headers):
        client.post("/admin/story-queue",
                    json={"urls": ["https://list-story.example.com/1"],
                          "label": "Listed Story"},
                    headers=admin_headers)
        resp = client.get("/admin/story-queue", headers=admin_headers)
        assert resp.status_code == 200
        urls = [i["url"] for i in resp.json()]
        assert "https://list-story.example.com/1" in urls

    def test_list_story_queue_shape(self, client, admin_headers):
        client.post("/admin/story-queue",
                    json={"urls": ["https://shape-story.example.com/1"]},
                    headers=admin_headers)
        items = client.get("/admin/story-queue", headers=admin_headers).json()
        assert len(items) >= 1
        for field in ["id", "url", "label", "status", "added_at"]:
            assert field in items[0], f"Missing story queue field: {field}"

    def test_new_story_has_pending_status(self, client, admin_headers):
        client.post("/admin/story-queue",
                    json={"urls": ["https://pending-story.example.com/1"]},
                    headers=admin_headers)
        items = client.get("/admin/story-queue", headers=admin_headers).json()
        pending = [i for i in items if i["url"] == "https://pending-story.example.com/1"]
        assert pending and pending[0]["status"] == "pending"

    def test_worker_story_queue_requires_worker_key(self, client):
        resp = client.get("/worker/story-queue")
        assert resp.status_code == 401

    def test_worker_story_queue_returns_pending(self, client, admin_headers, worker_headers):
        client.post("/admin/story-queue",
                    json={"urls": ["https://worker-story.example.com/1"]},
                    headers=admin_headers)
        resp = client.get("/worker/story-queue", headers=worker_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        urls = [i["url"] for i in resp.json()]
        assert "https://worker-story.example.com/1" in urls

    def test_mark_story_done_requires_worker_key(self, client, admin_headers):
        client.post("/admin/story-queue",
                    json={"urls": ["https://done-auth.example.com/1"]},
                    headers=admin_headers)
        items = client.get("/admin/story-queue", headers=admin_headers).json()
        item_id = next(i["id"] for i in items
                       if i["url"] == "https://done-auth.example.com/1")
        resp = client.patch(f"/worker/story-queue/{item_id}/done",
                            json={"status": "done"})
        assert resp.status_code == 401

    def test_mark_story_done_updates_status(self, client, admin_headers, worker_headers):
        client.post("/admin/story-queue",
                    json={"urls": ["https://mark-done.example.com/1"]},
                    headers=admin_headers)
        items = client.get("/admin/story-queue", headers=admin_headers).json()
        item_id = next(i["id"] for i in items
                       if i["url"] == "https://mark-done.example.com/1")
        resp = client.patch(f"/worker/story-queue/{item_id}/done",
                            json={"status": "done"},
                            headers=worker_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    def test_mark_story_done_removes_from_worker_queue(self, client, admin_headers, worker_headers):
        client.post("/admin/story-queue",
                    json={"urls": ["https://remove-from-queue.example.com/1"]},
                    headers=admin_headers)
        items = client.get("/admin/story-queue", headers=admin_headers).json()
        item_id = next(i["id"] for i in items
                       if i["url"] == "https://remove-from-queue.example.com/1")
        client.patch(f"/worker/story-queue/{item_id}/done",
                     json={"status": "done"},
                     headers=worker_headers)
        # Worker queue only shows pending items — the done item should be absent
        worker_items = client.get("/worker/story-queue", headers=worker_headers).json()
        worker_ids = [i["id"] for i in worker_items]
        assert item_id not in worker_ids

    def test_mark_story_done_nonexistent_returns_404(self, client, worker_headers):
        import uuid
        resp = client.patch(f"/worker/story-queue/{uuid.uuid4()}/done",
                            json={"status": "done"},
                            headers=worker_headers)
        assert resp.status_code == 404
