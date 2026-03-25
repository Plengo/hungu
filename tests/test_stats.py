"""
tests/test_stats.py
────────────────────
Tests for:
  - POST /stats/ping                — anonymous visitor ping
  - GET  /stats                     — authenticated platform stats
  - POST /user/{id}/track           — engagement event tracking
  - GET  /insights/trends           — aggregated category trends
  - GET  /worker/active-suburbs     — suburb list for worker
"""

import pytest
from conftest import make_article


# ─── Visitor pings ───────────────────────────────────────────────────────────

class TestStatsPing:
    def test_ping_returns_204(self, client):
        resp = client.post("/stats/ping",
                           json={"visitor_id": "test-device-001", "page": "feed"})
        assert resp.status_code == 204

    def test_ping_ignores_empty_visitor_id(self, client):
        resp = client.post("/stats/ping",
                           json={"visitor_id": "", "page": "visit"})
        assert resp.status_code == 204

    def test_ping_accepts_any_page(self, client):
        resp = client.post("/stats/ping",
                           json={"visitor_id": "dev-123", "page": "detail"})
        assert resp.status_code == 204

    def test_ping_missing_visitor_id_field_returns_422(self, client):
        resp = client.post("/stats/ping", json={"page": "feed"})
        assert resp.status_code == 422


# ─── Platform stats ───────────────────────────────────────────────────────────

class TestStatsEndpoint:
    def test_stats_requires_auth(self, client):
        resp = client.get("/stats")
        assert resp.status_code in (401, 403)

    def test_stats_returns_data_with_valid_token(self, client, device_user, auth_headers):
        client.post("/stats/ping",
                    json={"visitor_id": device_user["user_id"], "page": "visit"})
        resp = client.get("/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_views"     in data
        assert "unique_visitors" in data

    def test_stats_counts_pings(self, client, device_user, auth_headers):
        for i in range(3):
            client.post("/stats/ping",
                        json={"visitor_id": f"stats-visitor-{i}", "page": "feed"})
        resp = client.get("/stats", headers=auth_headers)
        assert resp.json()["total_views"] >= 3

    def test_stats_response_fields(self, client, auth_headers):
        resp = client.get("/stats", headers=auth_headers)
        assert resp.status_code == 200
        for field in ["total_views", "unique_visitors", "active_last_15min",
                      "daily_active", "total_articles_live", "total_bookmarks"]:
            assert field in resp.json(), f"Missing stats field: {field}"


# ─── Engagement tracking ──────────────────────────────────────────────────────

class TestEngagementTracking:
    def test_track_event_returns_204(self, client, device_user, auth_headers, worker_headers):
        from conftest import make_article
        art = client.post("/articles",
                          json=make_article({"title": "Track Event Article",
                                             "raw_text": "track event body"}),
                          headers=worker_headers).json()
        resp = client.post(
            f"/user/{device_user['user_id']}/track",
            json={"article_id": art["id"],
                  "location_tier": "Country", "category": "Politics"},
            headers=auth_headers,
        )
        assert resp.status_code == 204

    def test_track_event_different_categories(self, client, device_user, auth_headers, worker_headers):
        from conftest import make_article
        for cat in ["Economy", "Health", "Crime"]:
            art = client.post("/articles",
                              json=make_article({"title": f"Track Cat {cat}",
                                                 "category": cat,
                                                 "url": f"https://example.com/track-{cat.lower()}",
                                                 "raw_text": f"track {cat} body"}),
                              headers=worker_headers).json()
            resp = client.post(
                f"/user/{device_user['user_id']}/track",
                json={"article_id": art["id"],
                      "location_tier": "Country", "category": cat},
                headers=auth_headers,
            )
            assert resp.status_code == 204

    def test_insights_trends_returns_data(self, client, device_user, auth_headers, worker_headers):
        from conftest import make_article
        art = client.post("/articles",
                          json=make_article({"title": "Trends Data Article",
                                             "category": "Local",
                                             "raw_text": "trends data body"}),
                          headers=worker_headers).json()
        client.post(
            f"/user/{device_user['user_id']}/track",
            json={"article_id": art["id"], "location_tier": "City", "category": "Local"},
            headers=auth_headers,
        )
        resp = client.get("/insights/trends")
        assert resp.status_code == 200
        assert "trends" in resp.json()
        assert isinstance(resp.json()["trends"], list)

    def test_insights_trends_shape(self, client, device_user, auth_headers, worker_headers):
        from conftest import make_article
        art = client.post("/articles",
                          json=make_article({"title": "Trends Shape Article",
                                             "category": "Economy",
                                             "url": "https://example.com/trends-shape",
                                             "raw_text": "trends shape body"}),
                          headers=worker_headers).json()
        client.post(
            f"/user/{device_user['user_id']}/track",
            json={"article_id": art["id"], "location_tier": "Country", "category": "Economy"},
            headers=auth_headers,
        )
        trends = client.get("/insights/trends").json()["trends"]
        if trends:
            for row in trends:
                for field in ["tier", "category", "count"]:
                    assert field in row, f"Missing trends field: {field}"

    def test_insights_trends_count_increments(self, client, device_user, auth_headers, worker_headers):
        from conftest import make_article
        # Track same category twice and confirm count >= 2
        for i in range(2):
            art = client.post("/articles",
                              json=make_article({"title": f"Trend Count {i}",
                                                 "category": "EconomyTrend",
                                                 "url": f"https://example.com/trend-{i}",
                                                 "raw_text": f"trend count body {i}"}),
                              headers=worker_headers).json()
            client.post(
                f"/user/{device_user['user_id']}/track",
                json={"article_id": art["id"],
                      "location_tier": "Country", "category": "EconomyTrend"},
                headers=auth_headers,
            )
        trends = client.get("/insights/trends").json()["trends"]
        economy_rows = [r for r in trends if r["category"] == "EconomyTrend"]
        assert economy_rows and economy_rows[0]["count"] >= 2


# ─── Active suburbs ───────────────────────────────────────────────────────────

class TestActiveSuburbs:
    def test_active_suburbs_requires_worker_key(self, client):
        resp = client.get("/worker/active-suburbs")
        assert resp.status_code == 401

    def test_active_suburbs_returns_list(self, client, worker_headers):
        resp = client.get("/worker/active-suburbs", headers=worker_headers)
        assert resp.status_code == 200
        assert "suburbs" in resp.json()
        assert isinstance(resp.json()["suburbs"], list)
