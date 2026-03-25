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

import os, time, logging, json, re, hashlib, random
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("hungu-worker")

GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")
MISTRAL_API_KEY  = os.getenv("MISTRAL_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "")
KIMI_API_KEY     = os.getenv("KIMI_API_KEY", "")
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
# (name, function_name, interval_seconds, fast_mode)
# fast_mode=True  → fast_submit(): store raw article immediately, no AI during scrape.
#                   AI enrichment handled by the 3-min enrich_old cycle.
# fast_mode=False → process_and_submit(): full AI inline (used only for auctions).
SCHEDULE = [
    ("enrich_old",        "enrich_old_articles",   180, False),  #  3 min  — parallel AI enrichment (FIRST)
    ("breaking_world",    "scrape_bbc_world",        60, True),   #  1 min  — fast (BBC + Al Jazeera)
    ("breaking_sa",       "scrape_sa_breaking",      60, True),   #  1 min  — fast (Daily Maverick + News24)
    ("local_gov_news",    "scrape_gov_news",          60, True),   #  1 min  — fast (gov.za)
    ("sa_local_news",     "scrape_sa_local",          60, True),   #  1 min  — fast (TimesLIVE + M&G)
    ("sa_extra_news",     "scrape_sa_extra",          60, True),   #  1 min  — fast (The SA + eNCA + MyBroadband + EWN + IOL + SABC)
    ("sa_x_accounts",     "scrape_sa_x",              60, True),   #  1 min  — fast (Nitter/X — govt + media)
    ("community_news",    "scrape_community",      300, True),   #  5 min  — fast (GroundUp + community journalism)
    ("suburb_community",  "scrape_suburb_community", 1800, True), # 30 min  — suburb-specific FB/local pages per active suburb
    ("gazette_gpw",       "scrape_gazette",         3600, True),   # 60 min  — govt gazette
    ("policy_parliament", "scrape_parliament",      3600, True),   # 60 min  — parliament
    ("jobs_dpsa",         "scrape_jobs",           86400, True),   # 24 hours — DPSA vacancies
    ("auctions",          "scrape_auctions",        3600, False),  # 60 min  — special AI prompt
    ("archive_cleanup",   "archive_old_posts",     86400, False),  # 24 hours
    ("custom_sources",    "scrape_custom_sources",   300, True),   #  5 min  — admin-submitted RSS/feeds
    ("story_queue",       "process_story_queue",      60, True),   #  1 min  — admin-submitted article links
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
    """Extract JSON from AI response text (handles ```json wrappers and control characters)."""
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    raw = m.group(1) if m else text
    # Remove control characters that break JSON parsing (except \t \n \r)
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
    return json.loads(raw)


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
        "User-Agent": "HUNGU-Worker/2.0",
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
    Randomly pick an AI provider, then fall back through the rest on failure.
    Spreads load across providers to avoid burning one quota.
    On 429 (rate limit), skip immediately to the next provider (no waiting).
    """
    providers = []

    # Gemini (separate group — uses different API format)
    gemini_providers = []
    if GEMINI_API_KEY:
        gemini_providers.append(("Gemini-2.0-Flash", lambda p: _call_gemini_model(p, "gemini-2.0-flash", GEMINI_API_KEY)))
        gemini_providers.append(("Gemini-2.0-Flash-Lite", lambda p: _call_gemini_model(p, "gemini-2.0-flash-lite", GEMINI_API_KEY)))

    # OpenAI-compatible providers
    oai_providers = []
    if GROQ_API_KEY:
        oai_providers.append(("Groq-Llama3.3", lambda p: _call_openai_compatible(p, GROQ_API_KEY, "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")))
    if MISTRAL_API_KEY:
        oai_providers.append(("Mistral", lambda p: _call_openai_compatible(p, MISTRAL_API_KEY, "https://api.mistral.ai/v1", "mistral-small-latest")))
    if OPENROUTER_API_KEY:
        oai_providers.append(("OpenRouter-Llama3.3", lambda p: _call_openai_compatible(p, OPENROUTER_API_KEY, "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free")))
    if CEREBRAS_API_KEY:
        oai_providers.append(("Cerebras-Qwen3", lambda p: _call_openai_compatible(p, CEREBRAS_API_KEY, "https://api.cerebras.ai/v1", "qwen-3-235b-a22b-instruct-2507")))
    if SAMBANOVA_API_KEY:
        oai_providers.append(("SambaNova-Llama3.3", lambda p: _call_openai_compatible(p, SAMBANOVA_API_KEY, "https://api.sambanova.ai/v1", "Meta-Llama-3.3-70B-Instruct")))
    if DEEPSEEK_API_KEY:
        oai_providers.append(("DeepSeek", lambda p: _call_openai_compatible(p, DEEPSEEK_API_KEY, "https://api.deepseek.com", "deepseek-chat")))

    # Shuffle each group, then combine: Gemini first (free, highest quality), then shuffled others
    random.shuffle(gemini_providers)
    random.shuffle(oai_providers)
    providers = gemini_providers + oai_providers

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
                log.warning("%s rate-limited (429) — skipping to next provider", name)
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

{{
  "category": "Choose the most appropriate: Wars, Politics, Economy, Health, Jobs, Local, Crime, Auctions, Entertainment, Exciting, Funny, Wonderful, Rare. Use the 'Story' categories (Entertainment, Exciting, Funny, Wonderful, Rare) if the article is lighthearted, inspiring, unusual, or community-focused.",
  "summary": "A very short, punchy 1-2 sentence hook summarizing ONLY what is explicitly stated in the article.",
  "comprehensive_summary": "A full, detailed summary (3-5 sentences). You MUST rely STRICTLY on the facts, dates, names, and scores provided in the article text. DO NOT invent information or pull from historical training data to fill in gaps.",
  "impact": "2-3 sentences explaining what this means for an ordinary South African citizen today. Keep it real. Look at history, present, and make advantages and disadvantages. Do NOT just support anything blindly.",
  "actions_now": "• Practical things the reader can do RIGHT NOW. If NO immediate action is needed, DO NOT exaggerate — just say 'There is no need for your action currently' and give simple advice.",
  "actions_later": "• Things to do in the coming days/weeks. If NO action is needed, just say 'There is no need for your action currently' and maybe advise something simple to be aware of.",
  "verse": "ONLY include if the article touches on themes like death, war, suffering, injustice, natural disaster, morality, greed, corruption, or faith. Otherwise leave as empty string.",
  "verse_text": "If verse is set: the NWT (New World Translation) text of that verse — quote it accurately. Otherwise empty string.",
  "verse_niv": "If verse is set: the same verse quoted in the NIV (New International Version) translation. Otherwise empty string.",
  "insight": "If verse is set: 1-2 sentences connecting this news event to biblical prophecy or spiritual principles. Otherwise empty string.",
  "jw_topic": "If verse is set: 3-5 keywords for a JW.org Bible topic search. Otherwise empty string.",
  "urgent": true or false
}}

RULES:
1. The summary MUST be very short (1-2 sentences max). DO NOT HALLUCINATE ANY FACTS.
2. The comprehensive_summary MUST be detailed but strictly bounded by the provided article text. NEVER guess dates, scores, or names not provided.
3. The impact MUST be practical, realistic, state advantages and disadvantages, and be specific to South Africans.
4. actions_now and actions_later MUST NOT exaggerate danger. If there's nothing to do, literally say 'There is no need for your action currently.' Do NOT instruct the reader to protest, boycott, petition, or take political sides.
5. Spiritual fields (verse, verse_text, verse_niv, insight, jw_topic) are OPTIONAL. Only include them if the article genuinely connects to deep human themes — death, war, suffering, injustice, disasters, morality, corruption. Do NOT force a verse onto political party elections, sports results, property listings, or routine economic news.
6. If you do include a verse, it MUST be real and directly relevant. verse_text must be NWT; verse_niv must be the same verse in NIV.
7. Return ONLY the JSON object. No extra text before or after.

NEUTRALITY RULES — mandatory for every field:
8. Use the official name of every government, organisation, and country at all times. NEVER substitute with subjective labels — do NOT write "regime", "terrorist group", "radical", "extremist", "illegal government", "freedom fighters", "occupation force", or "controversial" unless you are directly quoting a named person from the article.
9. When a law, policy, cultural rule, or political outcome is contested (e.g. dress-code laws, election results, protest crackdowns, religious requirements in sport), describe ONLY the verifiable facts — what was decided, by whom, and what the stated effect is. Do NOT endorse or condemn either side.
10. Do NOT characterise any leader, political party, or institution as good or bad. Stick strictly to what the article states happened — not what any party claims, implies, or alleges unless clearly attributed.
11. The impact and actions fields must reflect objective, practical consequences for ordinary South Africans — not editorial opinion or moral judgment.

Source: {source}
Category: {category}
Title: {title}
Article text:
{raw_text[:3000]}
"""

def _jw_link_for(category: str, jw_topic: str) -> str:
    """Return a JW.org search URL for end-times Bible prophecy relevant to the topic."""
    query = urllib.parse.quote_plus(f"end times bible prophecies {jw_topic}".strip())
    return f"https://www.jw.org/en/search/?q={query}"

# ─── Deduplication check ──────────────────────────────────────────────────────

def article_exists(ch: str, url: str = "") -> Optional[dict]:
    """
    Check API before calling Gemini. Returns existing article info or None.
    Checks by content_hash first, then by url_hash as fallback (catches same-source
    re-scrapes where title/body changed slightly).
    """
    try:
        endpoint = f"{API_BASE_URL}/articles/hash/{ch}"
        if url:
            endpoint += f"?url={urllib.parse.quote(url, safe='')}"
        req = urllib.request.Request(endpoint, headers=_worker_headers())
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

def _strip_html(text: str) -> str:
    """Remove all HTML tags and decode common entities."""
    if not text:
        return text
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    return re.sub(r'\s{2,}', ' ', text).strip()

def _clean_rawtext(text: str) -> str:
    if not text:
        return text
    text = _strip_html(text)
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

def scrape_sa_extra() -> list:
    """
    Extra SA news outlets: The South African, eNCA, Eyewitness News (EWN),
    MyBroadband, IOL, and SABC News.
    """
    log.info("Scraping extra SA outlets (The South African, eNCA, EWN, MyBroadband, IOL, SABC)...")
    results = []

    # The South African — broad lifestyle/general SA coverage
    body = http_get("https://www.thesouthafrican.com/feed/")
    if body:
        items = _parse_rss(body, limit=6)
        results += [{**i, "source": "The South African", "category": "Local",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    # eNCA — DStv 403 TV channel breaking news
    body = http_get("https://www.enca.com/rss.xml")
    if body:
        items = _parse_rss(body, limit=6)
        results += [{**i, "source": "eNCA", "category": "Politics",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    # Eyewitness News (EWN) — 702/CapeTalk digital newsroom
    body = http_get("https://ewn.co.za/RSS")
    if body:
        items = _parse_rss(body, limit=6)
        results += [{**i, "source": "Eyewitness News", "category": "Politics",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    # MyBroadband — SA tech, telecoms, economy
    body = http_get("https://mybroadband.co.za/news/feed")
    if body:
        items = _parse_rss(body, limit=5)
        results += [{**i, "source": "MyBroadband", "category": "Economy",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    # IOL (Independent Online) — national SA news
    body = http_get("https://www.iol.co.za/rss")
    if body:
        items = _parse_rss(body, limit=5)
        results += [{**i, "source": "IOL", "category": "Local",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    # SABC News — public broadcaster
    body = http_get("https://www.sabcnews.com/sabcnews/feed/")
    if body:
        items = _parse_rss(body, limit=5)
        results += [{**i, "source": "SABC News", "category": "Politics",
                     "location_tier": "Country", "location_name": "South Africa"} for i in items]

    return results

def scrape_community() -> list:
    """
    Community & grassroots journalism sources:
    GroundUp (SA community journalism), OFM (Free State community radio),
    702/CapeTalk news feeds, and Carling Jazz community posts.
    These often break stories before mainstream media.
    Articles are stored with category='Community', location_tier='Suburb'|'City'.
    """
    log.info("Scraping community / grassroots news sources...")
    results = []

    # GroundUp — award-winning SA community journalism (townships, education, housing)
    body = http_get("https://groundup.org.za/feed/")
    if body:
        items = _parse_rss(body, limit=6)
        results += [{**i, "source": "GroundUp", "category": "Community",
                     "location_tier": "Suburb", "location_name": "South Africa"} for i in items]

    # OFM — Central SA community radio (Bloemfontein / Free State area)
    body = http_get("https://www.ofm.co.za/category/news/feed/")
    if body:
        items = _parse_rss(body, limit=4)
        results += [{**i, "source": "OFM News", "category": "Community",
                     "location_tier": "City", "location_name": "Free State"} for i in items]

    # 702 — Joburg talk radio (community/local Gauteng news)
    body = http_get("https://www.702.co.za/feed/articles")
    if body:
        items = _parse_rss(body, limit=4)
        results += [{**i, "source": "Radio 702", "category": "Community",
                     "location_tier": "City", "location_name": "Johannesburg"} for i in items]

    # CapeTalk — Cape Town community radio
    body = http_get("https://www.capetalk.co.za/feed/articles")
    if body:
        items = _parse_rss(body, limit=4)
        results += [{**i, "source": "CapeTalk", "category": "Community",
                     "location_tier": "City", "location_name": "Cape Town"} for i in items]

    return results

# ── Suburb-aware community scraper ────────────────────────────────────────────

# Known SA suburb/neighbourhood community pages — slug mappings.
# Add more as they are discovered. Slug = Facebook page name used in mbasic URL.
_SUBURB_FB_PAGES: dict[str, list[str]] = {
    "acornhoek":       ["AcornhoekNews", "acornhoeknews"],
    "pheli":           ["PheliNews", "soshanguvenews"],
    "lotus gardens":   ["LotusgardensNews", "lotusgardenspretoria"],
    "pretoria west":   ["PretoriaWestNews", "pretoriawestcommunity"],
    "atteridgeville":  ["AtteridgevilleNews"],
    "mamelodi":        ["MamalodiCommunityNews", "mamalodinews"],
    "soweto":          ["SowetoNews", "mysowetonews"],
    "alexandra":       ["AlexandraCommunity", "alexnews"],
    "mitchells plain": ["MitchellsPlainNews", "mitchellsplaincommunity"],
    "khayelitsha":     ["KhayelitshaNews", "khayelitshacommunity"],
    "sandton":         ["SandtonCommunityNews"],
    "menlyn":          ["MenlynNews"],
    "centurion":       ["CenturionCommunityNews", "centurioncommunity"],
    "midrand":         ["MidrandCommunity"],
    "roodepoort":      ["RoodepoortNews"],
    "krugersdorp":     ["KrugersdorpNews"],
    "vanderbijlpark":  ["VdbnewsVanderbijlpark"],
    "vereeniging":     ["VereenigingNews"],
    "polokwane":       ["PolokwaneNews", "limpopocommunity"],
    "nelspruit":       ["NelspruitNews"],
    "mbombela":        ["MbombelaCommunity"],
    "witbank":         ["WithankCommunity", "eMalahleniNews"],
    "emalahleni":      ["eMalahleniNews"],
    "rustenburg":      ["RustenburgCommunityNews"],
    "klerksdorp":      ["KlerksdorpNews"],
    "bloemfontein":    ["BloemfonteinNews"],
    "east london":     ["EastLondonCommunity"],
    "george":          ["GeorgeCommunityNews"],
    "paarl":           ["PaarlCommunity"],
    "stellenbosch":    ["StellenboschCommunity"],
    "tembisa":         ["TembisaCommunityNews", "tembisamagazine"],
    "thembisa":        ["TembisaCommunityNews"],
    "diepsloot":       ["DiepslootCommunityNews"],
    "ivory park":      ["IvoryParkCommunity"],
    "orange farm":     ["OrangeFarmCommunity"],
    "vosloorus":       ["VosloorusCommunity"],
    "springs":         ["SpringsCommunityNews"],
    "benoni":          ["BenoniCommunity"],
    "boksburg":        ["BoksburgNews"],
    "brakpan":         ["BrakpanCommunity"],
    "germiston":       ["GermistonCommunity"],
    "kempton park":    ["KemptonParkCommunity"],
    "edenvale":        ["EdenvaleCommunity"],
    "bedfordview":     ["BedfordviewCommunity"],
}

def _scrape_mbasic_fb_page(slug: str, suburb: str) -> list:
    """
    Scrape a public Facebook page's posts via mbasic.facebook.com.
    mbasic is the stripped-down mobile version — accessible without login for public pages.
    Returns list of article dicts.
    """
    url = f"https://mbasic.facebook.com/{slug}"
    body = http_get(url, timeout=15)
    if not body:
        return []

    results = []
    # Extract post titles/links from mbasic HTML
    # mbasic wraps posts in <div id="m_story_permalink_..."> or <article> tags
    # We look for <strong> inside story containers or <h3>
    seen = set()

    # Find story containers
    story_blocks = re.findall(
        r'<div[^>]*data-ft[^>]*>(.*?)</div>\s*</div>',
        body, re.DOTALL
    )
    # Fallback: find any <h3> or <strong> with meaningful text
    titles = re.findall(r'<(?:h3|strong)[^>]*>\s*([^<]{20,200})\s*</(?:h3|strong)>', body)
    # Also grab text near hrefs that look like post permalinks
    link_texts = re.findall(
        r'href="[^"]*permalink[^"]*"[^>]*>\s*([^<]{20,200})\s*</a>',
        body
    )

    for raw in (titles + link_texts):
        text = re.sub(r'\s+', ' ', raw).strip()
        if len(text) < 20 or text in seen:
            continue
        seen.add(text)
        results.append({
            "title":         text,
            "summary":       text,
            "full_context":  text,
            "source":        f"Facebook / {slug}",
            "url":           url,
            "image":         "",
            "category":      "Community",
            "location_tier": "Suburb",
            "location_name": suburb,
        })
        if len(results) >= 5:
            break

    if results:
        log.info("FB mbasic %s → %d posts for suburb '%s'", slug, len(results), suburb)
    return results


def _search_suburb_news_ddg(suburb: str) -> list:
    """
    DuckDuckGo HTML search for '{suburb} news site:facebook.com OR -site:facebook.com community news'.
    Extracts headline snippets from search results as community story stubs.
    Returns up to 5 article dicts.
    """
    query = f"{suburb} community news South Africa"
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    body = http_get(url, timeout=12)
    if not body:
        return []

    results = []
    seen = set()
    # DDG HTML: result titles in <a class="result__a"> tags
    matches = re.findall(
        r'<a[^>]+class="result__a"[^>]*>\s*(.*?)\s*</a>',
        body, re.DOTALL
    )
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>\s*(.*?)\s*</a>',
        body, re.DOTALL
    )
    urls = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"',
        body
    )

    for i, title_html in enumerate(matches[:5]):
        title = re.sub(r'<[^>]+>', '', title_html).strip()
        title = re.sub(r'\s+', ' ', title)
        if not title or len(title) < 15 or title in seen:
            continue
        seen.add(title)
        snippet = re.sub(r'<[^>]+>', '', snippets[i] if i < len(snippets) else '').strip()
        link = urls[i] if i < len(urls) else ''
        if link.startswith('//duckduckgo.com') or 'duckduckgo' in link:
            link = ''
        results.append({
            "title":         f"{suburb}: {title}",
            "summary":       snippet or title,
            "full_context":  snippet or title,
            "source":        f"Community Report / {suburb}",
            "url":           link,
            "image":         "",
            "category":      "Community",
            "location_tier": "Suburb",
            "location_name": suburb,
        })

    return results


def scrape_suburb_community() -> list:
    """
    Suburb-aware community scraper.
    1. Fetches the list of active user suburbs from the API.
    2. For each suburb, tries known Facebook page slugs (via mbasic) first.
    3. Falls back to a DuckDuckGo search for community news about that suburb.
    Articles are tagged with location_tier='Suburb' and location_name=<suburb>.
    """
    # Fetch active suburbs from API
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/worker/active-suburbs",
            headers=_worker_headers()
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        suburbs = data.get("suburbs", [])
    except Exception as exc:
        log.warning("active-suburbs fetch failed: %s", exc)
        suburbs = []

    if not suburbs:
        log.info("No active suburbs registered yet — skipping suburb community scrape")
        return []

    log.info("Scraping community news for %d active suburb(s): %s", len(suburbs), suburbs[:10])
    results = []

    for suburb in suburbs[:20]:  # cap at 20 suburbs per cycle
        suburb_lower = suburb.lower().strip()
        found = False

        # Try known FB page slugs first
        for known_suburb, slugs in _SUBURB_FB_PAGES.items():
            if known_suburb in suburb_lower or suburb_lower in known_suburb:
                for slug in slugs:
                    items = _scrape_mbasic_fb_page(slug, suburb)
                    if items:
                        results += items
                        found = True
                        break
                if found:
                    break

        # Fall back: DDG search for community news
        if not found:
            items = _search_suburb_news_ddg(suburb)
            results += items
            if items:
                log.info("DDG fallback for '%s' → %d results", suburb, len(items))

        time.sleep(1)  # polite delay between suburbs

    return results



# Verified South African official/public interest accounts worth monitoring.
# Nitter provides RSS feeds of Twitter/X timelines without needing API keys.
# Multiple Nitter instances for resilience.
_SA_ACCOUNTS = [
    # ── Government & official ──────────────────────────────────────────────────
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
    # ── SA news outlets — catch breaking posts before RSS updates ─────────────
    ("eNCA",           "Politics",  "Country",  "South Africa"),
    ("TheSAnews",      "Local",     "Country",  "South Africa"),
    ("mybroadband",    "Economy",   "Country",  "South Africa"),
    ("EWN_Reporter",   "Politics",  "Country",  "South Africa"),
    ("IOL",            "Local",     "Country",  "South Africa"),
    ("SABCNews",       "Politics",  "Country",  "South Africa"),
    ("dailymaverick",  "Politics",  "Country",  "South Africa"),
    ("TimesLIVE",      "Local",     "Country",  "South Africa"),
]

# Public Nitter instances — try in order until one works
_NITTER_INSTANCES = [
    "nitter.poast.org",
    "nitter.net",
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
  "summary": "A very short, punchy 1-2 sentence hook summarizing ONLY what is explicitly stated in the notice.",
  "comprehensive_summary": "A full, detailed summary (3-5 sentences) including: property type, location/address, estimated price or reserve price if mentioned, auction date, and how to get more info or register to bid. NEVER hallucinate dates or prices not in the text.",
  "actions_now": "2-3 bullet points of what someone interested should do RIGHT NOW (e.g. contact sheriff, view property, get pre-approval).",
  "actions_later": "2-3 bullet points for preparation (e.g. arrange financing, attend auction, do due diligence).",
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

def _enrich_single(art: dict) -> tuple[str, bool]:
    """Process one article with AI and PATCH the result back to the API."""
    prompt = build_prompt(art["title"], art.get("full_context", ""), art["source"], art["category"])
    ai = call_ai(prompt)
    if not ai:
        return (art["id"], False)
    
    # Allow AI to recategorize
    new_cat = ai.get("category", art["category"])
    jw_link = _jw_link_for(new_cat, ai.get("jw_topic", ""))
    
    payload = json.dumps({
        "category":         new_cat,
        "summary":          ai.get("summary", ""),
        "full_context":     ai.get("comprehensive_summary", ""),
        "impact":           ai.get("impact", ""),
        "actions_now":      ai.get("actions_now", ""),
        "actions_later":    ai.get("actions_later", ""),
        "prophecy_verse":   ai.get("verse", ""),
        "prophecy_text":    ai.get("verse_text", ""),
        "prophecy_verse2":  ai.get("verse_niv", ""),
        "prophecy_insight": ai.get("insight", ""),
        "jw_link":          jw_link,
    }).encode()
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/articles/{art['id']}/enrich",
            data=payload, method="PATCH",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            json.loads(resp.read())
            log.info("✓ Enriched: '%s'", art["title"][:60])
            return (art["id"], True)
    except Exception as exc:
        log.error("Enrich PATCH failed %s: %s", art["id"], exc)
        return (art["id"], False)


def enrich_old_articles() -> None:
    """Retroactively enrich articles in parallel using all available AI providers."""
    log.info("Checking for articles needing enrichment...")
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/articles/needs-enrichment?limit=20",
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
    log.info("Enriching %d articles in parallel (up to 5 threads)...", len(articles))
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_enrich_single, art): art
            for art in articles
        }
        success = sum(1 for f in as_completed(futures) if f.result()[1])
    log.info("Enriched %d/%d articles", success, len(articles))


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

        # Pre-check: skip if already in DB (content_hash + URL dedup)
        existing = article_exists(ch, raw.get("url", ""))
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
            # Allow AI to recategorize (except for Auctions which has a strict prompt)
            if raw.get("category") != "Auctions":
                raw["category"] = ai.get("category", raw["category"])

            is_auction = raw.get("category") == "Auctions"
            if is_auction:
                raw.update({
                    "summary":       ai.get("summary", raw.get("raw_text", "")[:120]),
                    "full_context":  ai.get("comprehensive_summary", raw.get("raw_text", "")),
                    "impact":        "",
                    "actions_now":   ai.get("actions_now", ""),
                    "actions_later": ai.get("actions_later", ""),
                    "prophecy":      {"verse": "", "text": "", "insight": ""},
                    "jw_link":       "",
                    "urgent":        ai.get("urgent", False),
                })
            else:
                jw_link = _jw_link_for(raw.get("category", ""), ai.get("jw_topic", ""))
                raw.update({
                    "summary":      ai.get("summary",      raw.get("raw_text", "")[:120]),
                    "full_context": ai.get("comprehensive_summary", raw.get("raw_text", "")),
                    "impact":       ai.get("impact",       "Impact analysis pending."),
                    "actions_now":  ai.get("actions_now",  ""),
                    "actions_later": ai.get("actions_later", ""),
                    "prophecy":    {"verse":   ai.get("verse", ""),
                                    "text":    ai.get("verse_text", ""),
                                    "verse2":  ai.get("verse_niv", ""),
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


def fast_submit(raw_articles: list) -> list:
    """
    Fast submission path: deduplicate + immediately store raw articles WITHOUT calling AI.
    Enrichment (summary, impact, actions, verse) is handled by enrich_old_articles()
    on the 3-minute schedule using all available AI providers in parallel.
    Multi-outlet: if the same story is reported by more than one outlet, the new
    source is added to the existing article's sources[] list — it is NOT a duplicate.
    Returns list of new article IDs.
    """
    new_ids = []
    now = datetime.now(timezone.utc)
    for raw in raw_articles:
        # Skip articles older than 7 days
        pub = raw.get("published_at")
        if pub:
            try:
                pub_dt = datetime.fromisoformat(pub)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if (now - pub_dt).total_seconds() / 86400 > 7:
                    log.debug("SKIP (old) '%s'", raw["title"][:50])
                    continue
            except Exception:
                pass

        ch = content_hash(raw["title"], raw.get("raw_text", ""))
        existing = article_exists(ch, raw.get("url", ""))
        if existing:
            # Multi-outlet coverage: add new source to sources[] — not a duplicate
            if raw["source"] not in (existing.get("sources") or []):
                log.info("SOURCE+ '%s' → '%s'", raw["source"], raw["title"][:50])
                post_article({**raw, "content_hash": ch})
            else:
                log.debug("SKIP (same source dup) '%s'", raw["title"][:50])
            continue

        # Preserve full raw text as full_context so the enrichment queue has context
        raw["full_context"] = raw.get("raw_text", "")
        raw["raw_text"]     = raw.get("raw_text", "")[:200]

        # Image fallback chain
        if not raw.get("image"):
            raw["image"] = fetch_og_image(raw.get("url", ""))
        if not raw.get("image"):
            raw["image"] = CATEGORY_IMAGES.get(raw.get("category", ""), CATEGORY_IMAGES["default"])

        # AI fields intentionally empty — enrichment queue fills them
        raw.setdefault("summary",      "")
        raw.setdefault("impact",       "")
        raw.setdefault("actions_now",  "")
        raw.setdefault("actions_later","")
        raw.setdefault("prophecy",     {"verse": "", "text": "", "insight": ""})
        raw.setdefault("jw_link",      "")
        raw.setdefault("urgent",       False)

        result = post_article(raw)
        if result.get("status") == "created":
            new_ids.append(result["id"])
            log.info("FAST+ '%s'", raw["title"][:60])
    return new_ids

# ─── Custom scrape sources (admin-submitted RSS/feed URLs) ───────────────────

def scrape_custom_sources() -> list[dict]:
    """Scrape RSS feeds submitted via the admin Scrape Sources tab."""
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/worker/scrape-sources",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            sources = json.loads(resp.read())
    except Exception as exc:
        log.warning("scrape-sources fetch failed: %s", exc)
        return []
    articles = []
    for src in sources:
        url   = src.get("url", "")
        label = src.get("label", url)
        if not url:
            continue
        raw = http_get(url)
        if not raw:
            continue
        # Try RSS/Atom parse first
        rss_items = _parse_rss(raw, limit=10)
        if rss_items:
            for item in rss_items:
                articles.append({
                    "title":         item["title"],
                    "summary":       item.get("raw_text", "")[:500],
                    "source":        label,
                    "category":      "General",
                    "location_tier": "Country",
                    "location_name": "South Africa",
                    "url":           item.get("url", url),
                    "image":         item.get("image", ""),
                    "urgent":        False,
                })
        else:
            html_art = _scrape_html_article(url, source=label)
            if html_art:
                articles.append(html_art)
    return articles


def _scrape_html_article(url: str, source: str = "") -> Optional[dict]:
    """Best-effort extraction of title + body from an arbitrary HTML page."""
    raw = http_get(url)
    if not raw:
        return None
    from html.parser import HTMLParser

    class _TitleParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.title = ""
            self._in_title = False
        def handle_starttag(self, tag, attrs):
            if tag == "title":
                self._in_title = True
        def handle_endtag(self, tag):
            if tag == "title":
                self._in_title = False
        def handle_data(self, data):
            if self._in_title and not self.title:
                self.title = data.strip()

    p = _TitleParser()
    p.feed(raw)
    title = p.title or url
    # strip all tags for a basic summary
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"\s+", " ", clean).strip()[:500]
    return {
        "title":         title,
        "summary":       clean,
        "source":        source or url,
        "category":      "General",
        "location_tier": "Country",
        "location_name": "South Africa",
        "url":           url,
        "image":         "",
        "urgent":        False,
    }


def process_story_queue() -> list[dict]:
    """Fetch and publish one-off article links submitted via the admin Story Links tab."""
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL}/worker/story-queue",
            headers=_worker_headers(),
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            items = json.loads(resp.read())
    except Exception as exc:
        log.warning("story-queue fetch failed: %s", exc)
        return []
    articles = []
    for item in items:
        item_id = item["id"]
        url     = item["url"]
        label   = item.get("label", "")
        art = _scrape_html_article(url, source=label or url)
        status = "failed"
        if art:
            result = post_article(art)
            if result.get("status") in ("created", "duplicate"):
                status = "done"
                articles.append(art)
        # mark done/failed regardless
        try:
            req2 = urllib.request.Request(
                f"{API_BASE_URL}/worker/story-queue/{item_id}/done",
                data=json.dumps({"status": status}).encode(),
                method="PATCH",
                headers=_worker_headers(),
            )
            with urllib.request.urlopen(req2, timeout=10):
                pass
        except Exception as exc2:
            log.warning("story-queue mark-done failed %s: %s", item_id, exc2)
    return articles


# ─── Scheduler ────────────────────────────────────────────────────────────────


SCRAPER_FNS = {
    "scrape_bbc_world":    scrape_bbc_world,
    "scrape_sa_breaking":  scrape_sa_breaking,
    "scrape_gov_news":     scrape_gov_news,
    "scrape_sa_local":     scrape_sa_local,
    "scrape_sa_extra":     scrape_sa_extra,
    "scrape_community":    scrape_community,
    "scrape_suburb_community": scrape_suburb_community,
    "scrape_sa_x":         scrape_sa_x,
    "scrape_gazette":      scrape_gazette,
    "scrape_parliament":   scrape_parliament,
    "scrape_jobs":         scrape_jobs,
    "scrape_auctions":     scrape_auctions,
    "archive_old_posts":   archive_old_posts,
    "enrich_old_articles": enrich_old_articles,
    "scrape_custom_sources": scrape_custom_sources,
    "process_story_queue": process_story_queue,
}

def run_scheduler():
    log.info("HUNGU Worker starting — fast scrapers every 60 s, parallel AI enrichment every 3 min")
    while True:
        for name, fn_name, interval, fast_mode in SCHEDULE:
            if _should_run(name, interval):
                is_scraper = fn_name not in ("archive_old_posts", "enrich_old_articles")
                fn = SCRAPER_FNS[fn_name]
                log.info("▶ Running: %s", name)
                try:
                    if not is_scraper:
                        # archive / enrich — run directly
                        fn()
                    elif fast_mode:
                        # Fast scrape: store raw immediately, AI enrichment handles the rest
                        articles = fn()
                        if articles:
                            new_ids = fast_submit(articles)
                            log.info("✓ %s — %d new articles", name, len(new_ids))
                            if new_ids:
                                dispatch_notifications(new_ids)
                        else:
                            log.info("✓ %s — no new items", name)
                    else:
                        # Full AI inline (auctions only — special prompt)
                        articles = fn()
                        if articles:
                            new_ids = process_and_submit(articles)
                            log.info("✓ %s — %d new articles", name, len(new_ids))
                            if new_ids:
                                dispatch_notifications(new_ids)
                        else:
                            log.info("✓ %s — no items", name)
                    _mark_run(name)
                except Exception as exc:
                    log.error("✗ %s failed: %s", name, exc)
        time.sleep(30)  # check every 30 s for fast 60-s scrapers to stay responsive

if __name__ == "__main__":
    run_scheduler()


