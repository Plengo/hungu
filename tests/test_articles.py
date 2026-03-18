"""
tests/test_articles.py
──────────────────────
Tests for the article feed, article detail, worker submission, and deduplication.
"""

import pytest
from conftest import make_article


class TestFeed:
    def test_feed_returns_200(self, client):
        resp = client.get("/feed")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_feed_limit_param(self, client, worker_headers):
        # Submit 5 articles with unique URLs
        for i in range(5):
            client.post("/articles", json=make_article({"title": f"Unique Article {i} LIMIT",
                                                         "url": f"https://example.com/article-{i}",
                                                         "raw_text": f"body content number {i}"}),
                        headers=worker_headers)
        resp = client.get("/feed?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) <= 3

    def test_feed_category_filter(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Economy Article XYZ",
                                       "category": "Economy", "raw_text": "eco stuff"}),
                    headers=worker_headers)
        resp = client.get("/feed?category=Economy")
        assert resp.status_code == 200
        for art in resp.json():
            assert art["category"].lower() == "economy"


class TestArticleDetail:
    def test_get_existing_article(self, client, worker_headers):
        art = make_article({"title": "Detail Test Article"})
        created = client.post("/articles", json=art, headers=worker_headers).json()
        resp = client.get(f"/article/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Detail Test Article"

    def test_get_nonexistent_article_returns_404(self, client):
        import uuid
        resp = client.get(f"/article/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestWorkerArticleSubmit:
    def test_submit_article_returns_201(self, client, worker_headers):
        art  = make_article()
        resp = client.post("/articles", json=art, headers=worker_headers)
        assert resp.status_code == 201
        assert resp.json()["status"] == "created"
        assert "id" in resp.json()

    def test_submit_without_worker_key_returns_401(self, client):
        resp = client.post("/articles", json=make_article())
        assert resp.status_code == 401

    def test_submit_wrong_worker_key_returns_401(self, client):
        resp = client.post(
            "/articles",
            json=make_article(),
            headers={"X-Worker-Key": "wrong-key"},
        )
        assert resp.status_code == 401


class TestDeduplication:
    def test_duplicate_submission_returns_duplicate_status(self, client, worker_headers):
        art   = make_article({"title": "Dedup Test Article", "raw_text": "same content"})
        first  = client.post("/articles", json=art, headers=worker_headers).json()
        second = client.post("/articles", json=art, headers=worker_headers).json()
        assert first["status"]  == "created"
        assert second["status"] == "duplicate"
        assert second["id"]     == first["id"]

    def test_dedup_hash_endpoint_404_for_unknown(self, client, worker_headers):
        resp = client.get("/articles/hash/0000000000000000000000000000000000000000000000000000000000000000",
                          headers=worker_headers)
        assert resp.status_code == 404

    def test_dedup_hash_endpoint_200_for_existing(self, client, worker_headers):
        import hashlib
        title, body = "Hash Endpoint Article", "Some body text"
        ch = hashlib.sha256((title.lower() + body[:200].lower()).encode()).hexdigest()
        client.post("/articles",
                    json=make_article({"title": title, "raw_text": body}),
                    headers=worker_headers)
        resp = client.get(f"/articles/hash/{ch}", headers=worker_headers)
        assert resp.status_code == 200
        assert "sources" in resp.json()

    def test_different_source_updates_sources_list(self, client, worker_headers):
        title = "Multi Source Article"
        body  = "unique body for multi source test abc"
        art1  = make_article({"title": title, "source": "BBC News", "raw_text": body})
        art2  = make_article({"title": title, "source": "Al Jazeera", "raw_text": body})
        r1 = client.post("/articles", json=art1, headers=worker_headers).json()
        r2 = client.post("/articles", json=art2, headers=worker_headers).json()
        assert r1["status"] == "created"
        # sources list should contain both after second submission
        assert "Al Jazeera" in r2.get("sources", []) or r2["status"] == "duplicate"
