"""
tests/test_articles.py
──────────────────────
Tests for:
  - GET  /feed                         — public article feed with filters
  - GET  /search                       — full-text search
  - GET  /article/{id}                 — article detail
  - POST /articles/{id}/view           — view count tracking
  - POST /articles/{id}/react          — like / dislike reactions
  - POST /articles                     — worker article submission
  - GET  /articles/hash/{hash}         — content-hash dedup check
  - GET  /articles/needs-enrichment    — worker enrichment queue
  - PATCH /articles/{id}/enrich        — worker AI enrichment write-back
"""

import uuid
import hashlib
import pytest
from conftest import make_article


# ─── Feed ────────────────────────────────────────────────────────────────────

class TestFeed:
    def test_feed_returns_200(self, client):
        resp = client.get("/feed")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_feed_limit_param(self, client, worker_headers):
        for i in range(5):
            client.post("/articles",
                        json=make_article({"title": f"Limit Test {i}",
                                           "url": f"https://example.com/limit-{i}",
                                           "raw_text": f"body content {i}"}),
                        headers=worker_headers)
        resp = client.get("/feed?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) <= 3

    def test_feed_category_filter(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Economy Filter Article",
                                       "category": "Economy",
                                       "raw_text": "eco stuff filter test"}),
                    headers=worker_headers)
        resp = client.get("/feed?category=Economy")
        assert resp.status_code == 200
        for art in resp.json():
            assert art["category"].lower() == "economy"

    def test_feed_article_has_required_fields(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Fields Test Article",
                                       "raw_text": "fields body"}),
                    headers=worker_headers)
        feed = client.get("/feed?limit=1").json()
        assert len(feed) >= 1
        art = feed[0]
        for field in ["id", "title", "source", "category", "summary", "impact",
                      "location_tier", "location_name", "urgent"]:
            assert field in art, f"Missing field: {field}"

    def test_feed_location_tier_filter(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "City Article Cape Town",
                                       "location_tier": "City",
                                       "location_name": "Cape Town",
                                       "raw_text": "city tier body"}),
                    headers=worker_headers)
        resp = client.get("/feed?location_tier=City")
        assert resp.status_code == 200
        for art in resp.json():
            assert art["location_tier"].lower() == "city"


# ─── Search ──────────────────────────────────────────────────────────────────

class TestSearch:
    def test_search_by_title_keyword(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Eskom Announces Stage Six",
                                       "raw_text": "eskom loadshedding body"}),
                    headers=worker_headers)
        resp = client.get("/search?q=Stage+Six")
        assert resp.status_code == 200
        titles = [a["title"] for a in resp.json()["articles"]]
        assert any("Stage Six" in t for t in titles)

    def test_search_empty_query_returns_empty(self, client):
        resp = client.get("/search?q=")
        assert resp.status_code == 200
        assert resp.json() == {"articles": []}

    def test_search_no_match_returns_empty(self, client):
        resp = client.get("/search?q=xyznosucharticle99999")
        assert resp.status_code == 200
        assert resp.json()["articles"] == []

    def test_search_by_summary(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Water Outage Notice",
                                       "summary": "Tshwane water disruption scheduled",
                                       "raw_text": "water tap off sunday"}),
                    headers=worker_headers)
        resp = client.get("/search?q=Tshwane+water")
        assert resp.status_code == 200
        assert len(resp.json()["articles"]) >= 1

    def test_search_limit_param(self, client, worker_headers):
        for i in range(4):
            client.post("/articles",
                        json=make_article({"title": f"Searchable Budget Article {i}",
                                           "url": f"https://example.com/budget-{i}",
                                           "raw_text": f"budget body {i}"}),
                        headers=worker_headers)
        resp = client.get("/search?q=Searchable+Budget&limit=2")
        assert resp.status_code == 200
        assert len(resp.json()["articles"]) <= 2


# ─── Article detail ───────────────────────────────────────────────────────────

class TestArticleDetail:
    def test_get_existing_article(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Detail Test Article"}),
                               headers=worker_headers).json()
        resp = client.get(f"/article/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Detail Test Article"

    def test_get_nonexistent_article_returns_404(self, client):
        resp = client.get(f"/article/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_article_detail_contains_all_fields(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Full Fields Article",
                                                  "raw_text": "full fields body"}),
                               headers=worker_headers).json()
        art = client.get(f"/article/{created['id']}").json()
        for field in ["id", "title", "source", "category", "summary", "impact",
                      "location_tier", "location_name", "url", "created_at"]:
            assert field in art, f"Missing field: {field}"


# ─── View count ───────────────────────────────────────────────────────────────

class TestViewCount:
    def test_view_increments_counter(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "View Count Article",
                                                  "raw_text": "view body"}),
                               headers=worker_headers).json()
        art_id = created["id"]
        before = client.get(f"/article/{art_id}").json().get("views", 0)
        client.post(f"/articles/{art_id}/view")
        after = client.get(f"/article/{art_id}").json().get("views", 0)
        assert after == before + 1

    def test_view_accumulates_multiple(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Multi View Article",
                                                  "raw_text": "multi view body"}),
                               headers=worker_headers).json()
        art_id = created["id"]
        for _ in range(3):
            client.post(f"/articles/{art_id}/view")
        views = client.get(f"/article/{art_id}").json().get("views", 0)
        assert views >= 3

    def test_view_nonexistent_returns_204(self, client):
        # Silently ignores missing articles
        resp = client.post(f"/articles/{uuid.uuid4()}/view")
        assert resp.status_code == 204


# ─── Reactions ────────────────────────────────────────────────────────────────

class TestReactions:
    def test_like_increments_likes(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Like Article",
                                                  "raw_text": "like body"}),
                               headers=worker_headers).json()
        resp = client.post(f"/articles/{created['id']}/react?reaction=like")
        assert resp.status_code == 200
        assert resp.json()["likes"] >= 1

    def test_dislike_increments_dislikes(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Dislike Article",
                                                  "raw_text": "dislike body"}),
                               headers=worker_headers).json()
        resp = client.post(f"/articles/{created['id']}/react?reaction=dislike")
        assert resp.status_code == 200
        assert resp.json()["dislikes"] >= 1

    def test_multiple_likes_accumulate(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Accumulate Likes",
                                                  "raw_text": "accumulate body"}),
                               headers=worker_headers).json()
        art_id = created["id"]
        client.post(f"/articles/{art_id}/react?reaction=like")
        client.post(f"/articles/{art_id}/react?reaction=like")
        resp = client.post(f"/articles/{art_id}/react?reaction=like")
        assert resp.json()["likes"] == 3

    def test_invalid_reaction_returns_422(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "React Validation",
                                                  "raw_text": "validation body"}),
                               headers=worker_headers).json()
        resp = client.post(f"/articles/{created['id']}/react?reaction=love")
        assert resp.status_code == 422

    def test_react_nonexistent_article_returns_404(self, client):
        resp = client.post(f"/articles/{uuid.uuid4()}/react?reaction=like")
        assert resp.status_code == 404


# ─── Worker submission ────────────────────────────────────────────────────────

class TestWorkerArticleSubmit:
    def test_submit_article_returns_201(self, client, worker_headers):
        resp = client.post("/articles", json=make_article(), headers=worker_headers)
        assert resp.status_code == 201
        assert resp.json()["status"] == "created"
        assert "id" in resp.json()

    def test_submit_without_worker_key_returns_401(self, client):
        resp = client.post("/articles", json=make_article())
        assert resp.status_code == 401

    def test_submit_wrong_worker_key_returns_401(self, client):
        resp = client.post("/articles", json=make_article(),
                           headers={"X-Worker-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_submitted_article_appears_in_feed(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Feed Appearance Test",
                                       "raw_text": "feed appearance body"}),
                    headers=worker_headers)
        feed = client.get("/feed").json()
        titles = [a["title"] for a in feed]
        assert any("Feed Appearance Test" in t for t in titles)


# ─── Content-hash deduplication ──────────────────────────────────────────────

class TestDeduplication:
    def test_duplicate_submission_returns_duplicate_status(self, client, worker_headers):
        art    = make_article({"title": "Dedup Test Article", "raw_text": "same content"})
        first  = client.post("/articles", json=art, headers=worker_headers).json()
        second = client.post("/articles", json=art, headers=worker_headers).json()
        assert first["status"]  == "created"
        assert second["status"] == "duplicate"
        assert second["id"]     == first["id"]

    def test_dedup_hash_endpoint_404_for_unknown(self, client, worker_headers):
        resp = client.get(
            "/articles/hash/0000000000000000000000000000000000000000000000000000000000000000",
            headers=worker_headers,
        )
        assert resp.status_code == 404

    def test_dedup_hash_endpoint_200_for_existing(self, client, worker_headers):
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
        r1 = client.post("/articles",
                         json=make_article({"title": title, "source": "BBC News",
                                            "raw_text": body}),
                         headers=worker_headers).json()
        r2 = client.post("/articles",
                         json=make_article({"title": title, "source": "Al Jazeera",
                                            "raw_text": body}),
                         headers=worker_headers).json()
        assert r1["status"] == "created"
        assert "Al Jazeera" in r2.get("sources", []) or r2["status"] == "duplicate"

    def test_hash_check_by_url_fallback(self, client, worker_headers):
        """Hash check with ?url= param — falls back to url_hash when content hash misses."""
        client.post("/articles",
                    json=make_article({"title": "URL Hash Fallback Article",
                                       "url": "https://example.com/url-hash-test",
                                       "raw_text": "url hash fallback body"}),
                    headers=worker_headers)
        # Use a non-matching content hash but pass the matching URL
        resp = client.get(
            "/articles/hash/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "?url=https://example.com/url-hash-test",
            headers=worker_headers,
        )
        assert resp.status_code == 200


# ─── Enrichment queue ─────────────────────────────────────────────────────────

class TestEnrichmentQueue:
    def test_needs_enrichment_requires_worker_key(self, client):
        resp = client.get("/articles/needs-enrichment")
        assert resp.status_code == 401

    def test_needs_enrichment_returns_unenriched_articles(self, client, worker_headers):
        # Article with no actions_now — should appear in queue
        client.post("/articles",
                    json=make_article({"title": "Unenriched Article Queue",
                                       "raw_text": "unenriched queue body"}),
                    headers=worker_headers)
        resp = client.get("/articles/needs-enrichment", headers=worker_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        titles = [a["title"] for a in resp.json()]
        assert any("Unenriched" in t for t in titles)

    def test_needs_enrichment_excludes_auctions(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Auction Should Be Excluded",
                                       "category": "Auctions",
                                       "raw_text": "auction exclude body"}),
                    headers=worker_headers)
        resp = client.get("/articles/needs-enrichment", headers=worker_headers)
        titles = [a["title"] for a in resp.json()]
        assert "Auction Should Be Excluded" not in titles

    def test_needs_enrichment_excludes_already_enriched(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Already Enriched Article",
                                                  "raw_text": "enriched body"}),
                               headers=worker_headers).json()
        # Enrich it
        client.patch(f"/articles/{created['id']}/enrich",
                     json={"actions_now": "Do something.", "impact": "Big impact."},
                     headers=worker_headers)
        resp = client.get("/articles/needs-enrichment", headers=worker_headers)
        titles = [a["title"] for a in resp.json()]
        assert "Already Enriched Article" not in titles

    def test_needs_enrichment_limit_param(self, client, worker_headers):
        for i in range(5):
            client.post("/articles",
                        json=make_article({"title": f"Enrich Limit Test {i}",
                                           "url": f"https://example.com/enrich-{i}",
                                           "raw_text": f"enrich limit body {i}"}),
                        headers=worker_headers)
        resp = client.get("/articles/needs-enrichment?limit=2", headers=worker_headers)
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    def test_needs_enrichment_response_shape(self, client, worker_headers):
        client.post("/articles",
                    json=make_article({"title": "Shape Check Article",
                                       "raw_text": "shape body"}),
                    headers=worker_headers)
        items = client.get("/articles/needs-enrichment", headers=worker_headers).json()
        assert len(items) >= 1
        item = items[0]
        for field in ["id", "title", "full_context", "summary", "source", "category"]:
            assert field in item, f"Missing enrichment queue field: {field}"


# ─── Enrich write-back ────────────────────────────────────────────────────────

class TestEnrichArticle:
    def test_enrich_updates_ai_fields(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Enrich Target Article",
                                                  "raw_text": "enrich target body"}),
                               headers=worker_headers).json()
        resp = client.patch(
            f"/articles/{created['id']}/enrich",
            json={
                "summary":      "Updated summary via AI.",
                "impact":       "High impact on daily life.",
                "actions_now":  "Stay informed.",
                "actions_later": "Review follow-up.",
            },
            headers=worker_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "enriched"

    def test_enrich_fields_persisted(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Persist Enrich Article",
                                                  "raw_text": "persist enrich body"}),
                               headers=worker_headers).json()
        client.patch(
            f"/articles/{created['id']}/enrich",
            json={"summary": "Persisted summary.", "actions_now": "Persisted action."},
            headers=worker_headers,
        )
        art = client.get(f"/article/{created['id']}").json()
        assert art["summary"] == "Persisted summary."

    def test_enrich_requires_worker_key(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Enrich Auth Article",
                                                  "raw_text": "auth body"}),
                               headers=worker_headers).json()
        resp = client.patch(f"/articles/{created['id']}/enrich",
                            json={"summary": "No key"})
        assert resp.status_code == 401

    def test_enrich_nonexistent_article_returns_404(self, client, worker_headers):
        resp = client.patch(f"/articles/{uuid.uuid4()}/enrich",
                            json={"summary": "ghost"},
                            headers=worker_headers)
        assert resp.status_code == 404

    def test_enrich_partial_update_leaves_other_fields(self, client, worker_headers):
        created = client.post("/articles",
                               json=make_article({"title": "Partial Enrich Article",
                                                  "summary": "Original summary.",
                                                  "raw_text": "partial body"}),
                               headers=worker_headers).json()
        client.patch(f"/articles/{created['id']}/enrich",
                     json={"impact": "New impact only."},
                     headers=worker_headers)
        art = client.get(f"/article/{created['id']}").json()
        # summary should still be the original value
        assert art["summary"] == "Original summary."
