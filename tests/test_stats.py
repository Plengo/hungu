"""
tests/test_stats.py
────────────────────
Tests for visitor analytics: ping tracking and stats endpoint.
"""

import pytest


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


class TestStatsEndpoint:
    def test_stats_requires_auth(self, client):
        resp = client.get("/stats")
        assert resp.status_code in (401, 403)

    def test_stats_returns_data_with_valid_token(self, client, device_user, auth_headers):
        # Record a ping first
        client.post("/stats/ping",
                    json={"visitor_id": device_user["user_id"], "page": "visit"})
        resp = client.get("/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_views" in data
        assert "unique_visitors" in data

    def test_stats_counts_pings(self, client, device_user, auth_headers):
        for i in range(3):
            client.post("/stats/ping",
                        json={"visitor_id": f"visitor-{i}", "page": "feed"})
        resp = client.get("/stats", headers=auth_headers)
        assert resp.json()["total_views"] >= 3
