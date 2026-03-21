"""
tests/test_notifications.py
────────────────────────────
Tests for the notification dispatch endpoint.
"""

import pytest
from conftest import make_article


def _sub_payload(**kwargs) -> dict:
    base = {
        "keywords":       ["eskom"],
        "categories":     ["Economy"],
        "location_tiers": [],
        "notify_urgent":  True,
    }
    base.update(kwargs)
    return base


class TestNotificationDispatch:
    def test_dispatch_no_articles_returns_empty(self, client, worker_headers):
        resp = client.post(
            "/internal/notifications/dispatch",
            json={"article_ids": []},
            headers=worker_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["matches"] == []

    def test_dispatch_requires_worker_key(self, client):
        resp = client.post(
            "/internal/notifications/dispatch",
            json={"article_ids": []},
        )
        assert resp.status_code == 401

    def test_dispatch_keyword_match(self, client, device_user, auth_headers, worker_headers):
        # Subscribe to keyword "eskom"
        client.post(f"/user/{device_user['user_id']}/subscription",
                    json=_sub_payload(keywords=["eskom"]), headers=auth_headers)
        # Create article with "eskom" in title
        art = client.post("/articles",
                          json=make_article({"title": "Eskom announces loadshedding",
                                             "raw_text": "eskom body text"}),
                          headers=worker_headers).json()
        resp = client.post(
            "/internal/notifications/dispatch",
            json={"article_ids": [art["id"]]},
            headers=worker_headers,
        )
        data = resp.json()
        assert resp.status_code == 200
        # At least one match for our user
        user_matches = [m for m in data["matches"] if m["user_id"] == device_user["user_id"]]
        assert len(user_matches) >= 1
        assert user_matches[0]["article_id"] == art["id"]
        assert "keyword:eskom" in user_matches[0]["matched_on"]

    def test_dispatch_category_match(self, client, device_user, auth_headers, worker_headers):
        client.post(f"/user/{device_user['user_id']}/subscription",
                    json=_sub_payload(keywords=[], categories=["Economy"], location_tiers=[]),
                    headers=auth_headers)
        art = client.post("/articles",
                          json=make_article({"title": "Budget 2025 announced",
                                             "category": "Economy",
                                             "raw_text": "budget text"}),
                          headers=worker_headers).json()
        resp = client.post(
            "/internal/notifications/dispatch",
            json={"article_ids": [art["id"]]},
            headers=worker_headers,
        )
        user_matches = [m for m in resp.json()["matches"]
                        if m["user_id"] == device_user["user_id"]]
        assert any("category:Economy" in m["matched_on"] for m in user_matches)

    def test_dispatch_urgent_match(self, client, device_user, auth_headers, worker_headers, admin_headers):
        client.post(f"/user/{device_user['user_id']}/subscription",
                    json=_sub_payload(keywords=[], categories=[], notify_urgent=True, location_tiers=[]),
                    headers=auth_headers)
        art = client.post("/articles",
                          json=make_article({"title": "Urgent breaking news",
                                             "urgent": True,
                                             "raw_text": "urgent content"}),
                          headers=worker_headers).json()
        
        # Mark as urgent via admin endpoint, since worker POST ignores the urgent flag
        client.patch(f"/admin/articles/{art['id']}/urgent",
                     json={"urgent": True},
                     headers=admin_headers)

        resp = client.post(
            "/internal/notifications/dispatch",
            json={"article_ids": [art["id"]]},
            headers=worker_headers,
        )
        user_matches = [m for m in resp.json()["matches"]
                        if m["user_id"] == device_user["user_id"]]
        assert any(m["matched_on"] == "urgent" for m in user_matches)

    def test_dispatch_no_match_for_unrelated_article(self, client, device_user,
                                                      auth_headers, worker_headers):
        client.post(f"/user/{device_user['user_id']}/subscription",
                    json=_sub_payload(keywords=["eskom"], categories=[], notify_urgent=False,
                                      location_tiers=[]),
                    headers=auth_headers)
        # Article that has nothing to do with Eskom
        art = client.post("/articles",
                          json=make_article({"title": "Sports team wins cup",
                                             "category": "Sports",
                                             "raw_text": "sports content here",
                                             "urgent": False}),
                          headers=worker_headers).json()
        resp = client.post(
            "/internal/notifications/dispatch",
            json={"article_ids": [art["id"]]},
            headers=worker_headers,
        )
        user_matches = [m for m in resp.json()["matches"]
                        if m["user_id"] == device_user["user_id"]]
        assert user_matches == []
