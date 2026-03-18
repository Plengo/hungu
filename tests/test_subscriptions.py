"""
tests/test_subscriptions.py
────────────────────────────
Tests for the notification subscription CRUD.
"""

import pytest


def _sub_payload(**kwargs) -> dict:
    base = {
        "keywords":       ["load shedding", "eskom"],
        "categories":     ["Politics", "Economy"],
        "location_tiers": ["Country"],
        "notify_urgent":  True,
    }
    base.update(kwargs)
    return base


class TestSubscriptions:
    def test_get_subscription_404_when_none(self, client, device_user, auth_headers):
        resp = client.get(f"/user/{device_user['user_id']}/subscription",
                          headers=auth_headers)
        assert resp.status_code == 404

    def test_create_subscription(self, client, device_user, auth_headers):
        resp = client.post(
            f"/user/{device_user['user_id']}/subscription",
            json=_sub_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"]    == "created"
        assert "load shedding"   in data["keywords"]
        assert "Politics"        in data["categories"]
        assert data["notify_urgent"] is True

    def test_get_subscription_after_create(self, client, device_user, auth_headers):
        client.post(f"/user/{device_user['user_id']}/subscription",
                    json=_sub_payload(), headers=auth_headers)
        resp = client.get(f"/user/{device_user['user_id']}/subscription",
                          headers=auth_headers)
        assert resp.status_code == 200
        assert "eskom" in resp.json()["keywords"]

    def test_update_subscription(self, client, device_user, auth_headers):
        client.post(f"/user/{device_user['user_id']}/subscription",
                    json=_sub_payload(), headers=auth_headers)
        updated = client.post(
            f"/user/{device_user['user_id']}/subscription",
            json=_sub_payload(keywords=["loadshedding", "water"], categories=["Health"]),
            headers=auth_headers,
        )
        assert updated.status_code == 201
        data = updated.json()
        assert data["status"] == "updated"
        assert "water"   in data["keywords"]
        assert "Health"  in data["categories"]
        assert "eskom"   not in data["keywords"]

    def test_delete_subscription(self, client, device_user, auth_headers):
        client.post(f"/user/{device_user['user_id']}/subscription",
                    json=_sub_payload(), headers=auth_headers)
        resp = client.delete(f"/user/{device_user['user_id']}/subscription",
                             headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "unsubscribed"
        # Subscription should now return 404
        get_resp = client.get(f"/user/{device_user['user_id']}/subscription",
                              headers=auth_headers)
        assert get_resp.status_code == 404

    def test_subscription_access_denied_for_other_user(self, client):
        user_a = client.post("/auth/device").json()
        user_b = client.post("/auth/device").json()
        headers_a = {"Authorization": f"Bearer {user_a['token']}"}
        resp = client.get(f"/user/{user_b['user_id']}/subscription", headers=headers_a)
        assert resp.status_code == 403

    def test_keywords_sanitised_lowercase(self, client, device_user, auth_headers):
        resp = client.post(
            f"/user/{device_user['user_id']}/subscription",
            json=_sub_payload(keywords=["ESKOM", "  Load Shedding  "]),
            headers=auth_headers,
        )
        kws = resp.json()["keywords"]
        assert "eskom"        in kws
        assert "load shedding" in kws
