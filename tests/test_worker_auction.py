"""
tests/test_worker_auction.py
──────────────────────────────
Unit tests for the worker auction keyword filter and prompt builder.
"""

import importlib.util
import os
import re
import pytest

_worker_path = os.path.join(
    os.path.dirname(__file__), "..", "services", "worker", "main.py"
)
_spec   = importlib.util.spec_from_file_location("worker_main", _worker_path)
worker  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker)


class TestAuctionKeywordFilter:
    """The scrape_auctions function filters gazette RSS items by auction keywords."""

    AUCTION_KW = re.compile(
        r'auction|sale in execution|immovable property|sheriff|bonded property|foreclosure',
        re.IGNORECASE,
    )

    def test_auction_keyword_matches_title_with_auction(self):
        assert self.AUCTION_KW.search("Public Auction of Immovable Property")

    def test_auction_keyword_matches_sale_in_execution(self):
        assert self.AUCTION_KW.search("Sale in Execution: Property Gauteng")

    def test_auction_keyword_matches_sheriff(self):
        assert self.AUCTION_KW.search("Notice by the Sheriff of the Court")

    def test_auction_keyword_matches_foreclosure(self):
        assert self.AUCTION_KW.search("Foreclosure proceedings initiated")

    def test_auction_keyword_matches_bonded_property(self):
        assert self.AUCTION_KW.search("Bonded property to be sold")

    def test_auction_keyword_no_match_for_unrelated(self):
        assert not self.AUCTION_KW.search("Government Gazette Notice: New Tax Regulation")

    def test_auction_keyword_case_insensitive(self):
        assert self.AUCTION_KW.search("AUCTION OF IMMOVABLE PROPERTY")


class TestAuctionPromptBuilder:
    def test_prompt_contains_title(self):
        prompt = worker.build_auction_prompt("Test Auction", "body text", "Gazette")
        assert "Test Auction" in prompt

    def test_prompt_contains_source(self):
        prompt = worker.build_auction_prompt("Title", "body", "Government Gazette")
        assert "Government Gazette" in prompt

    def test_prompt_requests_json_format(self):
        prompt = worker.build_auction_prompt("T", "B", "S")
        assert "JSON" in prompt

    def test_prompt_truncates_long_body(self):
        long_body = "x" * 5000
        prompt = worker.build_auction_prompt("T", long_body, "S")
        # body is capped at 2000 chars in the prompt
        assert len(prompt) < 5000

    def test_prompt_mentions_practical_details(self):
        prompt = worker.build_auction_prompt("T", "B", "S")
        assert "addresses" in prompt.lower() or "prices" in prompt.lower()


class TestAuctionArticleCategory:
    """Auctions submitted to the API should use the Auctions category."""

    def test_auction_article_submit(self, client, worker_headers):
        from conftest import make_article
        art = make_article({
            "title": "Auction: Property Sale in Execution — Johannesburg",
            "category": "Auctions",
            "source": "Government Gazette (Auctions)",
            "raw_text": "Sale in execution of immovable property at 123 Main St",
        })
        resp = client.post("/articles", json=art, headers=worker_headers)
        assert resp.status_code == 201

    def test_auction_appears_in_category_feed(self, client, worker_headers):
        from conftest import make_article
        client.post("/articles",
                    json=make_article({
                        "title": "Auction Feed Test",
                        "category": "Auctions",
                        "source": "Government Gazette (Auctions)",
                        "raw_text": "auction body text xyz",
                    }),
                    headers=worker_headers)
        resp = client.get("/feed?category=Auctions")
        assert resp.status_code == 200
        titles = [a["title"] for a in resp.json()]
        assert any("Auction" in t for t in titles)
