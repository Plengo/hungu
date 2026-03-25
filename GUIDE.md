# HUNGU: Development Guide
Refer to this for Copilot prompts.
- **Web**: React-based mobile-first UI.
- **API**: FastAPI handling prioritization logic.
- **Worker**: Scraper and Gemini AI integration.

---

## Test Suite — v1.0.0 (189 tests, 100% passing)

Run locally:
```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

### File coverage map

| File | What it tests |
|---|---|
| `tests/conftest.py` | Shared fixtures: in-memory SQLite DB, `TestClient`, `device_user`, `auth_headers`, `worker_headers`, `admin_headers`, `article_in_db`, `make_article()` factory |
| `tests/test_auth.py` | `POST /auth/device` — device user creation, JWT token validity, unique IDs, cross-user 403 |
| `tests/test_articles.py` | `GET /feed`, `GET /search`, `GET /article/{id}`, `POST /articles/{id}/view`, `POST /articles/{id}/react`, `POST /articles` (worker submit), `GET /articles/hash/{hash}` (dedup), `GET /articles/needs-enrichment`, `PATCH /articles/{id}/enrich` |
| `tests/test_admin.py` | `GET /admin/dashboard`, `POST /admin/archive-old`, `PATCH /admin/articles/{id}/urgent`, `DELETE /admin/articles/{id}`, `PATCH /admin/articles/{id}/rescan` |
| `tests/test_bookmarks.py` | `GET /user/{id}/bookmarks`, `POST /user/{id}/bookmark/{art}`, `DELETE /user/{id}/bookmark/{art}` — including idempotency and cross-user 403 |
| `tests/test_subscriptions.py` | `GET/POST/DELETE /user/{id}/subscription` — full CRUD, keyword sanitisation, cross-user 403 |
| `tests/test_notifications.py` | `POST /internal/notifications/dispatch` — keyword match, category match, urgent match, no-match, auth |
| `tests/test_stats.py` | `POST /stats/ping`, `GET /stats`, `POST /user/{id}/track`, `GET /insights/trends`, `GET /worker/active-suburbs` |
| `tests/test_custom_sources.py` | `POST/GET/DELETE /admin/scrape-sources`, `GET /worker/scrape-sources`, `POST/GET /admin/story-queue`, `GET /worker/story-queue`, `PATCH /worker/story-queue/{id}/done` |
| `tests/test_security.py` | JWT expiry, tampered tokens, missing Bearer prefix, cross-user bookmark/subscription access, worker key enforcement on all protected routes |
| `tests/test_worker_auction.py` | Worker unit tests: auction keyword regex, `build_auction_prompt()`, auction article category submission |
| `tests/test_worker_dedup.py` | Worker unit tests: `content_hash()`, `_parse_rss()`, `_clean_title()` (HTML entity decoding, URL stripping, length cap), `_strip_html()` |
