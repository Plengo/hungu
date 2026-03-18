"""
tests/test_worker_dedup.py
───────────────────────────
Unit tests for the worker's deduplication helpers (no network/DB needed).
"""

import hashlib
import importlib.util
import os
import pytest

# Load worker/main.py under a distinct name to avoid conflict with api/main.py
_worker_path = os.path.join(
    os.path.dirname(__file__), "..", "services", "worker", "main.py"
)
_spec   = importlib.util.spec_from_file_location("worker_main", _worker_path)
worker  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker)


class TestContentHash:
    def test_same_title_body_same_hash(self):
        h1 = worker.content_hash("Load Shedding Update", "Eskom announces stage 4")
        h2 = worker.content_hash("Load Shedding Update", "Eskom announces stage 4")
        assert h1 == h2

    def test_lowercase_insensitive(self):
        h1 = worker.content_hash("Load SHEDDING Update", "ESKOM")
        h2 = worker.content_hash("load shedding update", "eskom")
        assert h1 == h2

    def test_title_whitespace_stripped(self):
        h1 = worker.content_hash("  Title  ", "body")
        h2 = worker.content_hash("Title",     "body")
        assert h1 == h2

    def test_different_titles_different_hash(self):
        h1 = worker.content_hash("Title A", "same body")
        h2 = worker.content_hash("Title B", "same body")
        assert h1 != h2

    def test_body_capped_at_200_chars(self):
        """Only first 200 chars of body contribute to hash."""
        long_body  = "x" * 500
        short_body = "x" * 200
        h1 = worker.content_hash("Title", long_body)
        h2 = worker.content_hash("Title", short_body)
        assert h1 == h2

    def test_hash_is_sha256_hex(self):
        h = worker.content_hash("Title", "body")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_body_ok(self):
        h = worker.content_hash("Title Only")
        assert len(h) == 64


class TestRSSParser:
    RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title><![CDATA[Test Article One]]></title>
      <link>https://example.com/1</link>
      <description><![CDATA[First article description]]></description>
    </item>
    <item>
      <title>Test Article Two</title>
      <link>https://example.com/2</link>
      <description>Second article description</description>
    </item>
    <item>
      <title></title>
      <link>https://example.com/3</link>
      <description>No title item</description>
    </item>
  </channel>
</rss>"""

    def test_parse_returns_items(self):
        items = worker._parse_rss(self.RSS_SAMPLE)
        assert len(items) == 2   # empty-title item skipped

    def test_parse_cdata_title(self):
        items = worker._parse_rss(self.RSS_SAMPLE)
        assert items[0]["title"] == "Test Article One"

    def test_parse_plain_title(self):
        items = worker._parse_rss(self.RSS_SAMPLE)
        assert items[1]["title"] == "Test Article Two"

    def test_parse_respects_limit(self):
        items = worker._parse_rss(self.RSS_SAMPLE, limit=1)
        assert len(items) == 1

    def test_parse_extracts_url(self):
        items = worker._parse_rss(self.RSS_SAMPLE)
        assert "example.com" in items[0]["url"]

    def test_parse_empty_body_returns_empty(self):
        items = worker._parse_rss("")
        assert items == []
