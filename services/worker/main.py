"""
HUNGU Worker — Scraper & AI Processing Agent

Tiered scraping schedule (hourly for all news, saves Gemini credits)
────────────────────────
  breaking_world   (BBC World + Al Jazeera)    :  every 60 min   — Wars, Politics (International)
  breaking_sa      (Daily Maverick + News24)   :  every 60 min   — SA Breaking news
  local_politics   (gov.za news)               :  every 60 min   — Politics, Economy
  sa_local_news    (TimesLIVE + Mail&Guardian) :  every 60 min   — SA local/general
  sa_x_accounts    (Nitter RSS of verified SA) :  every 60 min   — SA official statements
  gazette          (GPW gov gazettes)          :  every 6 hours  — Local, Economy, Health
  policy           (Parliament/StatsSA)        :  every 6 hours  — Politics, Economy
  jobs             (DPSA vacancies)            :  every 24 hours — Jobs
  archive_old      (cleanup job)               :  every 24 hours — marks old articles archived

Enrichment-first strategy
─────────────────────────
  Before scraping new articles, the worker checks for unenriched backlog.
  If any articles are missing AI fields (summary, impact, actions, prophecy),
  those are enriched FIRST. New scrapes only happen once the backlog is clear.
  This ensures every article in the feed is fully populated.

Deduplication
─────────────
  Worker calculates content_hash (SHA-256 of title + body) and checks
  GET /articles/hash/{hash} BEFORE calling Gemini. This prevents wasting
  free-tier AI credits on articles already in the DB.
  If the same story appears in multiple sources, the sources[] list is updated.

Rate limits
───────────
  Gemini 2.0 Flash free tier: 15 req/min → 4 s sleep between calls.
  High-priority categories (Wars, Politics, Economy) are processed first.
"""

import os, time, logging, json, re, hashlib
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("hungu-worker")

GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")
API_BASE_URL     = os.getenv("API_BASE_URL", "http://api:8000")
WORKER_API_KEY   = os.getenv("WORKER_API_KEY", "")
AI_DELAY         = 4                  # seconds between AI calls

HIGH_PRIORITY = {"Wars", "Politics", "Economy", "Health"}

# ─── Category fallback images (Unsplash) ───────────────────────────────────────────
CATEGORY_IMAGES = {
    "Wars":     "https://images.unsplash.com/photo-1579684453423-f84349ef60b0?w=800&q=60",
    "Politics": "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?w=800&q=60",
    "Economy":  "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800&q=60",
    "Health":   "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=800&q=60",
    "Jobs":     "https://images.unsplash.com/photo-1521791136064-7986c2920216?w=800&q=60",
    "Local":    "https://images.unsplash.com/photo-1486325212027-8081e485255e?w=800&q=60",
    "Crime":    "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=800&q=60",
    "Auctions": "https://images.unsplash.com/photo-1560518883-ce09059eeffa?w=800&q=60",
    "default":  "https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=800&q=60",
}

# ─── Tiered scraping schedule ─────────────────────────────────────────────────
# (name, function_name, interval_seconds)
SCHEDULE = [
    ("enrich_old",       "enrich_old_articles",  180),    #  3 min  — retroactive AI enrichment (FIRST)
    ("breaking_world",   "scrape_bbc_world",    3600),    # 60 min  — BBC World + Al Jazeera
    ("breaking_sa",      "scrape_sa_breaking",  3600),    # 60 min  — Daily Maverick + News24
    ("local_gov_news",   "scrape_gov_news",     3600),    # 60 min
    ("sa_local_news",    "scrape_sa_local",     3600),    # 60 min  — TimesLIVE + M&G
    ("sa_x_accounts",    "scrape_sa_x",         3600),    # 60 min  — Nitter/X verified SA
    ("gazette_gpw",      "scrape_gazette",     21600),    # 6 hours
    ("policy_parliament","scrape_parliament",  21600),    # 6 hours
    ("jobs_dpsa",        "scrape_jobs",        86400),    # 24 hours
    ("auctions",         "scrape_auctions",    21600),    # 6 hours — property auctions
    ("archive_cleanup",  "archive_old_posts",  86400),    # 24 hours
]

_last_run: dict[str, float] = {}

def _should_run(name: str, interval: int) -> bool:
    return (time.time() - _last_run.get(name, 0)) >= interval

def _mark_run(name: str):
    _last_run[name] = time.time()

# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def http_get(url: str, timeout: int = 15) -> Optional[str]:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "HUNGU-Scraper/2.0 (news aggregator)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("GET failed %s: %s", url, exc)
        return None

def _worker_headers() -> dict:
    h = {"Content-Type": "application/json"}
    if WORKER_API_KEY:
        h["X-Worker-Key"] = WORKER_API_KEY
    return h

def content_hash(title: str, body: str = "") -> str:
    blob = (title.lower().strip() + (body or "")[:200].lower().strip()).encode()
    return hashlib.sha256(blob).hexdigest()

# ─── Multi-provider AI cascade ────────────────────────────────────────────────
# Priority: Gemini 2.0 Flash → Gemini 1.5 Flash → DeepSeek → Groq
# On 429 (rate limit), retry once after backoff, then fall through to next provider.

def _parse_ai_json(text: str) -> Optional[dict]:
    """Extract JSON from AI response text (handles ```json wrappers)."""
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    return json.loads(m.group(1) if m else text)


def _call_gemini_model(prompt: str, model: str, api_key: str) -> Optional[dict]:
    """Call a specific Gemini model. Returns parsed dict or None."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1024},
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_ai_json(text)


def _call_openai_compatible(prompt: str, api_key: str, base_url: str, model: str) -> Optional[dict]:
    """Call an OpenAI-compatible API (DeepSeek, Groq, etc). Returns parsed dict or None."""
    url = f"{base_url}/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 1024,
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    text = data["choices"][0]["message"]["content"]
    return _parse_ai_json(text)


def _is_rate_limited(exc: Exception) -> bool:
    """Check if an exception is a 429 rate-limit error."""
    return "429" in str(exc)


def call_ai(prompt: str) -> Optional[dict]:
    """
    Try each AI provider in order. On 429, wait 60s and retry once,
    then move to the next provider. Returns parsed JSON dict or None.
    """
    providers = []

    # 1. Gemini 2.0 Flash
    if GEMINI_API_KEY:
        providers.append(("Gemini-2.0-Flash", lambda p: _call_gemini_model(p, "gemini-2.0-flash", GEMINI_API_KEY)))
        # 2. Gemini 1.5 Flash (same key, separate rate limit)
        providers.append(("Gemini-1.5-Flash", lambda p: _call_gemini_model(p, "gemini-1.5-flash", GEMINI_API_KEY)))

    # 3. DeepSeek
    if DEEPSEEK_API_KEY:
        providers.append(("DeepSeek", lambda p: _call_openai_compatible(p, DEEPSEEK_API_KEY, "https://api.deepseek.com/v1", "deepseek-chat")))

    # 4. Groq
    if GROQ_API_KEY:
        providers.append(("Groq-Llama3.3", lambda p: _call_openai_compatible(p, GROQ_API_KEY, "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")))

    if not providers:
        log.warning("No AI API keys configured — skipping enrichment")
        return None

    for name, call_fn in providers:
        try:
            result = call_fn(prompt)
            if result:
                log.info("AI success via %s", name)
                return result
        except Exception as exc:
            if _is_rate_limited(exc):
                log.warning("%s rate-limited (429) — waiting 60s then retrying...", name)
                time.sleep(60)
                try:
                    result = call_fn(prompt)
                    if result:
                        log.info("AI success via %s (retry)", name)
                        return result
                except Exception as retry_exc:
                    log.warning("%s retry failed: %s — trying next provider", name, retry_exc)
            else:
                log.warning("%s error: %s — trying next provider", name, exc)

    log.error("All AI providers exhausted — enrichment failed for this article")
    return None


# Keep backward-compatible alias
def call_gemini(prompt: str, api_key: str = "") -> Optional[dict]:
    return call_ai(prompt)

def build_prompt(title: str, raw_text: str, source: str, category: str) -> str:
    return f"""You are the HUNGU AI engine — a South African Christian news analyser.
Analyse this article and respond ONLY with valid JSON (no markdown, no ```json wrapper).
Every field below is REQUIRED — do NOT leave any field empty or null.

{{
  "summary": "A comprehensive 3-5 sentence summary. Go BEYOND the headline: include key details, numbers, dates, people involved, context, and implications. If the article text is short, expand with relevant background a South African reader needs.",
  "impact": "2-3 sentences explaining what this means for an ordinary South African citizen today. Be specific: mention how it affects their wallet, safety, rights, community, or daily life. Never say 'coming soon' or 'pending'.",
  "actions_now": "• Action 1: something the reader can do RIGHT NOW\n• Action 2: another immediate step\n• Action 3: a practical thing to check or prepare today",
  "actions_later": "• Action 1: something to do in the coming days or weeks\n• Action 2: a longer-term preparation step\n• Action 3: how to stay informed or get involved",
  "verse": "A relevant Bible verse reference, e.g. Matthew 24:7",
  "verse_text": "The actual text of that verse (short quote)",
  "insight": "1-2 sentences connecting this news event to biblical prophecy or spiritual principles. How does God's Word help us understand what is happening?",
  "jw_topic": "3-5 keywords for a JW.org Bible topic search (e.g. 'end times economic hardship God's kingdom')",
  "urgent": true or false
}}

RULES:
1. The summary MUST be 3-5 sentences minimum with genuinely useful detail.
2. The impact MUST be practical and specific to South Africans — never generic.
3. actions_now and actions_later MUST each have 2-3 bullet points starting with •
4. The verse MUST be a real Bible verse relevant to the article topic.
5. The insight MUST connect the news to scripture — be thoughtful, not generic.
6. Return ONLY the JSON object. No extra text before or after.

Source: {source}
Category: {category}
Title: {title}
Article text:
{raw_text[:3000]}
"""

# ─── Deduplication check ──────────────────────────────────────────────────────

def article_exists(ch: str) -> Optional[dict]:
    """
    Check API before calling Gemini. Returns existing article info or None.
    Saves ~4 Gemini credits per duplicate across all scrapers.
    """
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/articles/hash/{ch}",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        log.warning("Dedup check error: %s", e)
        return None
    except Exception as exc:
        log.warning("Dedup check failed: %s", exc)
        return None

# ─── POST article to API ──────────────────────────────────────────────────────

def post_article(article: dict) -> dict:
    try:
        data = json.dumps(article).encode()
        req = urllib.request.Request(
            f"{API_BASE_URL}/articles", data=data, method="POST",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            log.info("POST /articles → %s  [%s]", result.get("status"), article.get("title", "")[:50])
            return result
    except Exception as exc:
        log.error("Failed to post article: %s", exc)
        return {}

# ─── Notification dispatch ────────────────────────────────────────────────────

def dispatch_notifications(article_ids: list) -> None:
    """Notify the API of new article IDs so it can match subscriptions."""
    if not article_ids:
        return
    try:
        data = json.dumps({"article_ids": article_ids}).encode()
        req  = urllib.request.Request(
            f"{API_BASE_URL}/internal/notifications/dispatch",
            data=data, method="POST",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            log.info("Dispatched notifications — %d matches", len(result.get("matches", [])))
    except Exception as exc:
        log.warning("dispatch_notifications failed: %s", exc)

# ─── Text-cleaning helpers ────────────────────────────────────────────────────
_URL_RE       = re.compile(r'https?://\S+')
_READMORE_RE  = re.compile(r'(Read more|See|Check it out|Click here|Full story|More info|Find out more)\s*:?\s*https?://\S*', re.IGNORECASE)
_HASHTAG_TAIL = re.compile(r'(\s+#\w+)+\s*$')

def _clean_title(text: str) -> str:
    if not text:
        return text
    text = _READMORE_RE.sub('', text).strip()
    text = _URL_RE.sub('', text).strip()
    text = _HASHTAG_TAIL.sub('', text).strip()
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > 200:
        text = text[:197].rsplit(' ', 1)[0] + '…'
    return text

def _clean_rawtext(text: str) -> str:
    if not text:
        return text
    text = _READMORE_RE.sub('', text)
    lines = [l for l in text.splitlines() if not re.fullmatch(r'\s*https?://\S+\s*', l)]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()

# ─── Scrapers ─────────────────────────────────────────────────────────────────

def _parse_rss(body: str, limit: int = 10) -> list:
    """Generic RSS parser — returns list of {title, link, description, image, published_at} dicts."""
    items = re.findall(r"<item>(.*?)</item>", body, re.DOTALL)
    results = []
    for item_raw in items[:limit]:
        def _tag(tag, _item=item_raw):
            m = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", _item, re.DOTALL)
            return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""
        title = _clean_title(_tag("title"))
        # Extract published date from <pubDate> or <dc:date>
        pub_date_str = _tag("pubDate") or _tag("dc:date")
        published_at = _parse_pub_date(pub_date_str) if pub_date_str else None
        if title:
            results.append({
                "title":        title,
                "url":          _tag("link"),
                "raw_text":     _clean_rawtext(_tag("description")),
                "image":        _extract_rss_image(item_raw),
                "published_at": published_at,
            })
    return results


def _parse_pub_date(date_str: str) -> Optional[str]:
    """Parse RSS pubDate string into ISO format. Returns None on failure."""
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.isoformat()
    except Exception:
        pass
    # Try ISO format directly
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.isoformat()
    except Exception:
        pass
    return None


def _extract_rss_image(item_raw: str) -> str:
    """Extract image URL from an RSS <item> block."""
    # media:content
    m = re.search(r'<media:content[^>]+url=["\'](https?://[^"\']+)["\']', item_raw)
    if m:
        return m.group(1)
    # media:thumbnail
    m = re.search(r'<media:thumbnail[^>]+url=["\'](https?://[^"\']+)["\']', item_raw)
    if m:
        return m.group(1)
    # enclosure with image type
    m = re.search(r'<enclosure[^>]+type=["\']image/[^>]+url=["\'](https?://[^"\']+)["\']', item_raw, re.IGNORECASE)
    if not m:
        m = re.search(r'<enclosure[^>]+url=["\'](https?://[^"\']+)["\'][^>]+type=["\']image/', item_raw, re.IGNORECASE)
    if m:
        return m.group(1)
    # <img> inside description CDATA
    m = re.search(r'<img[^>]+src=["\']( https?://[^"\']+)["\']', item_raw, re.IGNORECASE)
    if not m:
        m = re.search(r'<img[^>]+src=["\']( ?https?://[^"\']+)["\']', item_raw, re.IGNORECASE)
    if m and m.group(1).strip().startswith('http'):
        return m.group(1).strip()
    return ""


def fetch_og_image(url: str) -> str:
    """Fetch article page and extract og:image meta tag."""
    if not url:
        return ""
    try:
        body = http_get(url, timeout=8)
        if not body:
            return ""
        m = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            body, re.IGNORECASE)
        if not m:
            m = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                body, re.IGNORECASE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""

# ── International / World news ─────────────────────────────────────────────────

def scrape_bbc_world() -> list:
    """BBC World News RSS — true international news (not Africa-specific)."""
    log.info("Scraping BBC World News RSS...")
    results = []

    # BBC Top Stories (global)
    body = http_get("http://feeds.bbci.co.uk/news/rss.xml")
    if body:
        items = _parse_rss(body, limit=6)
        results += [{**i, "source": "BBC News", "category": "Wars",
                     "location_tier": "Global", "location_name": "Global"} for i in items]

    # Al Jazeera English
    body = http_get("https://www.aljazeera.com/xml/rss/all.xml")
    if body:
        items = _parse_rss(body, limit=6)
        results += [{**i, "source": "Al Jazeera", "category": "Wars",
                     "location_tier": "Global", "location_name": "Global"} for i in items]

    return results

# ── SA Breaking news ───────────────────────────────────────────────────────────

def scrape_sa_breaking() -> list:
    """Daily Maverick + News24 — SA breaking news (15-min interval)."""
    log.info("Scraping SA breaking news (Daily Maverick + News24)...")
    results = []

    # Daily Maverick
    body = http_get("https://www.dailymaverick.co.za/feed/")
    if body:
        items = _parse_rss(body, limit=6)
        results += [{**i, "source": "Daily Maverick", "category": "Politics",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    # News24
    body = http_get("https://feeds.news24.com/articles/news24/TopStories/rss")
    if body:
        items = _parse_rss(body, limit=6)
        results += [{**i, "source": "News24", "category": "Politics",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    return results

def scrape_sa_local() -> list:
    """TimesLIVE + Mail & Guardian — SA general news (30-min interval)."""
    log.info("Scraping SA local news (TimesLIVE + Mail & Guardian)...")
    results = []

    # TimesLIVE
    body = http_get("https://www.timeslive.co.za/rss/")
    if body:
        items = _parse_rss(body, limit=5)
        results += [{**i, "source": "TimesLIVE", "category": "Local",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    # Mail & Guardian
    body = http_get("https://mg.co.za/feed/")
    if body:
        items = _parse_rss(body, limit=5)
        results += [{**i, "source": "Mail & Guardian", "category": "Politics",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    return results

# ── X / Nitter (verified SA accounts) ─────────────────────────────────────────

# Verified South African official/public interest accounts worth monitoring.
# Nitter provides RSS feeds of Twitter/X timelines without needing API keys.
# Multiple Nitter instances for resilience.
_SA_ACCOUNTS = [
    ("PresidencyZA",   "Politics",  "Country",  "South Africa"),
    ("SAPoliceService","Crime",     "Country",  "South Africa"),
    ("GovernmentZA",   "Politics",  "Country",  "South Africa"),
    ("CityofCT",       "Local",     "City",     "Cape Town"),
    ("CityofJoburgZA", "Local",     "City",     "Johannesburg"),
    ("eThekwiniM",     "Local",     "City",     "Durban"),
    ("SANDFinfo",      "Wars",      "Country",  "South Africa"),
    ("TreasuryRSA",    "Economy",   "Country",  "South Africa"),
    ("HealthZA",       "Health",    "Country",  "South Africa"),
    ("DIRCO_ZA",       "Politics",  "Country",  "South Africa"),
]

# Public Nitter instances — try in order until one works
_NITTER_INSTANCES = [
    "nitter.privacydev.net",
    "nitter.poast.org",
]

def _nitter_to_x_url(nitter_url: str) -> str:
    """Convert a Nitter URL to a real X.com URL.
    e.g. https://nitter.privacydev.net/user/status/123#m → https://x.com/user/status/123
    """
    if not nitter_url:
        return nitter_url
    for instance in _NITTER_INSTANCES + ["nitter.net"]:
        prefix = f"https://{instance}/"
        if nitter_url.startswith(prefix):
            path = nitter_url[len(prefix):].split('#')[0]  # strip fragment
            return f"https://x.com/{path}"
    return nitter_url

def _nitter_rss(username: str) -> Optional[str]:
    for instance in _NITTER_INSTANCES:
        url  = f"https://{instance}/{username}/rss"
        body = http_get(url, timeout=10)
        if body and "<item>" in body:
            return body
    return None

def scrape_sa_x() -> list:
    """
    Scrape verified SA official accounts via Nitter RSS feeds.
    Nitter mirrors Twitter timelines as RSS without requiring API auth.
    """
    log.info("Scraping SA verified X accounts via Nitter...")
    results = []
    for username, category, tier, location in _SA_ACCOUNTS:
        body = _nitter_rss(username)
        if not body:
            log.debug("Nitter unavailable for @%s", username)
            continue
        items = _parse_rss(body, limit=3)
        for item in items:
            if not item.get("title") or item["title"].startswith("RT "):
                continue  # skip retweets
            # Convert nitter link to real X.com link
            item["url"] = _nitter_to_x_url(item.get("url", ""))
            results.append({
                **item,
                "source":        f"@{username} (X)",
                "category":      category,
                "location_tier": tier,
                "location_name": location,
            })
    return results

# ── SA Government sources ──────────────────────────────────────────────────────

def scrape_gov_news() -> list:
    """South African Government News RSS — policy and service delivery updates."""
    log.info("Scraping gov.za news RSS...")
    body = http_get("https://www.gov.za/rss.xml")
    if not body:
        return []
    items = _parse_rss(body, limit=8)
    return [{**i, "source": "SA Government News", "category": "Politics",
             "location_tier": "Country", "location_name": "South Africa"} for i in items]

def scrape_gazette() -> list:
    log.info("Scraping Government Gazette (GPW)...")
    body = http_get("https://www.gpwonline.co.za/Gazettes/Gazettes/Pages/rss.aspx")
    if not body:
        return []
    items = _parse_rss(body, limit=8)
    return [{**i, "source": "Government Gazette (GPW)", "category": "Local",
             "location_tier": "Country", "location_name": "South Africa"} for i in items]

def scrape_parliament() -> list:
    """Parliamentary monitoring RSS — bills, committee reports, policy changes."""
    log.info("Scraping PMG / Parliament RSS...")
    body = http_get("https://pmg.org.za/rss/")
    if not body:
        return []
    items = _parse_rss(body, limit=6)
    return [{**i, "source": "Parliamentary Monitoring Group", "category": "Politics",
             "location_tier": "Country", "location_name": "South Africa"} for i in items]

def scrape_jobs() -> list:
    log.info("Scraping DPSA job vacancies...")
    body = http_get("https://www.dpsa.gov.za/dpsa2g/vacancies.asp?rss=1")
    if not body:
        return []
    items = _parse_rss(body, limit=6)
    return [{**i, "source": "DPSA Vacancies", "category": "Jobs",
             "location_tier": "Country", "location_name": "South Africa"} for i in items]

# ── House Auctions (Sheriff / Gazette) ─────────────────────────────────────────

def scrape_auctions() -> list:
    """Scrape property auction notices from the Government Gazette only."""
    log.info("Scraping Government Gazette auction notices...")
    results = []

    # SA Government Gazette — filter for property/auction keywords
    body = http_get("https://www.gpwonline.co.za/Gazettes/Gazettes/Pages/rss.aspx")
    if body:
        items = _parse_rss(body, limit=20)
        auction_kw = re.compile(r'auction|sale in execution|immovable property|sheriff|bonded property|foreclosure', re.IGNORECASE)
        for item in items:
            text = (item.get("title", "") + " " + item.get("raw_text", ""))
            if auction_kw.search(text):
                results.append({**item, "source": "Government Gazette (Auctions)",
                                "category": "Auctions", "location_tier": "Country",
                                "location_name": "South Africa"})

    log.info("Found %d gazette auction notices", len(results))
    return results


def build_auction_prompt(title: str, raw_text: str, source: str) -> str:
    """Special prompt for auction listings — no spiritual context needed."""
    return f"""You are the HUNGU AI engine. Analyse this South African property auction notice and respond ONLY with valid JSON (no markdown wrapper) matching this schema exactly:

{{
  "summary": "A comprehensive 3-4 sentence summary including: property type, location/address, estimated price or reserve price if mentioned, auction date, and how to get more info or register to bid.",
  "actions_now": "2-3 bullet points of what someone interested should do RIGHT NOW (e.g. contact sheriff, view property, get pre-approval)",
  "actions_later": "2-3 bullet points for preparation (e.g. arrange financing, attend auction, do due diligence)",
  "urgent": true or false
}}

IMPORTANT: Extract all practical details — addresses, prices, dates, contact info, case numbers. This helps people access hidden property opportunities.

Source: {source}
Title: {title}
Notice text:
{raw_text[:2000]}
"""

def archive_old_posts() -> None:
    """Tell the API to archive articles older than 30 days."""
    log.info("Running archive-old-posts cleanup...")
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/admin/archive-old", method="POST",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            log.info("Archived %d old articles.", data.get("archived", 0))
    except Exception as exc:
        log.error("archive_old_posts failed: %s", exc)

def enrich_old_articles() -> None:
    """Retroactively enrich articles missing AI-generated fields (summary, impact, actions, prophecy)."""
    log.info("Checking for articles needing enrichment...")
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/articles/needs-enrichment?limit=10",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            articles = json.loads(resp.read())
    except Exception as exc:
        log.warning("needs-enrichment fetch failed: %s", exc)
        return
    if not articles:
        log.info("All articles fully enriched.")
        return
    log.info("Enriching %d articles with missing AI fields...", len(articles))
    for art in articles:
        prompt = build_prompt(
            art["title"],
            art.get("full_context") or art.get("summary", ""),
            art["source"], art["category"]
        )
        ai = call_gemini(prompt)
        time.sleep(AI_DELAY)
        if not ai:
            continue
        jw_topic = ai.get("jw_topic", "end times prophecy")
        jw_link  = f"https://www.jw.org/en/search/?q={urllib.parse.quote_plus(jw_topic)}"
        payload  = json.dumps({
            "impact":           ai.get("impact", ""),
            "actions_now":      ai.get("actions_now", ""),
            "actions_later":    ai.get("actions_later", ""),
            "prophecy_verse":   ai.get("verse", ""),
            "prophecy_text":    ai.get("verse_text", ""),
            "prophecy_insight": ai.get("insight", ""),
            "jw_link":          jw_link,
        }).encode()
        try:
            req2 = urllib.request.Request(
                f"{API_BASE_URL}/articles/{art['id']}/enrich",
                data=payload, method="PATCH",
                headers=_worker_headers(),
            )
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                json.loads(resp2.read())
                log.info("Enriched: '%s'", art["title"][:60])
        except Exception as exc2:
            log.error("Enrich PATCH failed %s: %s", art["id"], exc2)


def _has_enrichment_backlog() -> bool:
    """Check if there are unenriched articles waiting. Used to delay new scrapes."""
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/articles/needs-enrichment?limit=1",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            articles = json.loads(resp.read())
            return len(articles) > 0
    except Exception:
        return False


# ─── AI Processing pipeline ───────────────────────────────────────────────────

def process_and_submit(raw_articles: list) -> list:
    """
    For each raw article:
      1. Skip articles older than 7 days
      2. Calculate content_hash
      3. Check API — skip if already exists (saves Gemini credits)
      4. Call Gemini on new articles (high-priority first, rate-limited)
      5. POST to API
    Returns list of new article IDs submitted.
    """
    # Sort: high-priority categories first
    raw_articles.sort(key=lambda a: (0 if a.get("category") in HIGH_PRIORITY else 1))

    req_count = 0
    minute_start = time.time()
    new_ids = []
    now = datetime.now(timezone.utc)

    for raw in raw_articles:
        # Skip articles older than 7 days (current week only)
        pub = raw.get("published_at")
        if pub:
            try:
                pub_dt = datetime.fromisoformat(pub)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                age_days = (now - pub_dt).total_seconds() / 86400
                if age_days > 7:
                    log.debug("SKIP (old: %.0fd) '%s'", age_days, raw["title"][:50])
                    continue
            except Exception:
                pass

        ch = content_hash(raw["title"], raw.get("raw_text", ""))

        # Pre-check: skip if already in DB
        existing = article_exists(ch)
        if existing:
            log.info("SKIP (dup) '%s' — sources: %s", raw["title"][:50], existing.get("sources"))
            # If new source, the API /articles POST will update sources list
            if raw["source"] not in (existing.get("sources") or []):
                raw["content_hash"] = ch
                post_article({**raw, "raw_text": raw.get("raw_text", "")})
            continue

        # Rate-limit is handled inside call_ai cascade — just add delay
        prompt = (build_auction_prompt(raw["title"], raw.get("raw_text", ""), raw["source"])
                  if raw.get("category") == "Auctions"
                  else build_prompt(raw["title"], raw.get("raw_text", ""), raw["source"], raw["category"]))
        ai = call_ai(prompt)
        time.sleep(AI_DELAY)

        if ai:
            is_auction = raw.get("category") == "Auctions"
            if is_auction:
                raw.update({
                    "summary":       ai.get("summary", raw.get("raw_text", "")[:120]),
                    "impact":        "",
                    "actions_now":   ai.get("actions_now", ""),
                    "actions_later": ai.get("actions_later", ""),
                    "prophecy":      {"verse": "", "text": "", "insight": ""},
                    "jw_link":       "",
                    "urgent":        ai.get("urgent", False),
                })
            else:
                jw_topic = ai.get("jw_topic", "end times prophecy")
                jw_link  = f"https://www.jw.org/en/search/?q={urllib.parse.quote_plus(jw_topic)}"
                raw.update({
                    "summary":      ai.get("summary",      raw.get("raw_text", "")[:120]),
                    "impact":       ai.get("impact",       "Impact analysis pending."),
                    "actions_now":  ai.get("actions_now",  ""),
                    "actions_later": ai.get("actions_later", ""),
                    "prophecy":    {"verse":   ai.get("verse", ""),
                                    "text":    ai.get("verse_text", ""),
                                    "insight": ai.get("insight", "")},
                    "jw_link":      jw_link,
                    "urgent":      ai.get("urgent", False),
                })
        else:
            # Gemini failed — save with empty fields so the enrichment queue picks them up
            raw.setdefault("summary",  raw.get("raw_text", "")[:120])
            raw.setdefault("impact",   "")
            raw.setdefault("actions_now",  "")
            raw.setdefault("actions_later", "")
            raw.setdefault("prophecy", {"verse": "", "text": "", "insight": ""})
            raw.setdefault("jw_link",  "https://www.jw.org/en/search/?q=end+times+prophecy")
            raw.setdefault("urgent",   False)

        # Image: try RSS-scraped, then OG tag from URL, then category fallback
        if not raw.get("image"):
            raw["image"] = fetch_og_image(raw.get("url", ""))
        if not raw.get("image"):
            raw["image"] = CATEGORY_IMAGES.get(raw.get("category", ""), CATEGORY_IMAGES["default"])

        raw["raw_text"] = raw.get("raw_text", "")[:200]   # trim before sending
        result = post_article(raw)
        if result.get("status") == "created":
            new_ids.append(result["id"])
        log.info("Processed: %s", raw["title"][:60])

    return new_ids

# ─── Scheduler ────────────────────────────────────────────────────────────────

_SCRAPER_FNS = {
    "scrape_bbc_world":   scrape_bbc_world,
    "scrape_sa_breaking": scrape_sa_breaking,
    "scrape_gov_news":    scrape_gov_news,
    "scrape_sa_local":    scrape_sa_local,
    "scrape_sa_x":        scrape_sa_x,
    "scrape_gazette":     scrape_gazette,
    "scrape_parliament":  scrape_parliament,
    "scrape_jobs":        scrape_jobs,
    "scrape_auctions":    scrape_auctions,
    "archive_old_posts":  archive_old_posts,
    "enrich_old_articles": enrich_old_articles,
}

def run_scheduler():
    log.info("HUNGU Worker starting — enrichment-first strategy, checking every 60 s")
    while True:
        for name, fn_name, interval in SCHEDULE:
            if _should_run(name, interval):
                # Enrichment-first: skip new scrapes if backlog exists
                is_scraper = fn_name not in ("archive_old_posts", "enrich_old_articles")
                if is_scraper and _has_enrichment_backlog():
                    log.info("⏸ Skipping %s — enrichment backlog exists, enriching first", name)
                    continue

                fn = _SCRAPER_FNS[fn_name]
                log.info("▶ Running: %s", name)
                try:
                    if not is_scraper:
                        fn()
                    else:
                        articles = fn()
                        if articles:
                            new_ids = process_and_submit(articles)
                            log.info("✓ %s — %d new articles", name, len(new_ids))
                            if new_ids:
                                dispatch_notifications(new_ids)
                        else:
                            log.info("✓ %s — no items scraped", name)
                    _mark_run(name)
                except Exception as exc:
                    log.error("✗ %s failed: %s", name, exc)
        time.sleep(60)  # check schedule every minute

if __name__ == "__main__":
    run_scheduler()


