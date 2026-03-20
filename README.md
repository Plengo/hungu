# HUNGU — AI-Powered Actionable News & Gazette Intelligence 🇿🇦

HUNGU is a microservices-based news platform that delivers hyper-local South African intelligence — from your **suburb** to the **world** — enriched with AI-generated summaries, impact analysis, action steps, and scriptural perspective.

Live at **[hungu.co.za](https://hungu.co.za)**

---

## Architecture

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌────────────┐
│  Web (nginx) │──▶│  API (FastAPI)│──▶│  PostgreSQL  │◀──│   Worker   │
│  Port 80/443 │   │  Port 8000   │   │  (internal)  │   │ (scheduler)│
└─────────────┘   └──────────────┘   └──────────────┘   └────────────┘
```

| Service | Tech | Role |
|---------|------|------|
| **Web** | Nginx + Tailwind CSS (single-page) | Mobile-first PWA frontend |
| **API** | FastAPI + SQLAlchemy + JWT | REST API, auth, feed, dedup, admin |
| **Worker** | Python (stdlib) + scheduler | Scraping, AI enrichment, notifications |
| **DB** | PostgreSQL 15 | Articles, users, bookmarks, analytics |

---

## Features

### News Aggregation
- **14+ South African sources** — BBC Africa, Al Jazeera, Daily Maverick, News24, TimesLIVE, Mail & Guardian, The South African, eNCA, EWN, MyBroadband, IOL, SABC News, GroundUp, OFM, 702, CapeTalk
- **Government sources** — gov.za media, Government Gazette (GPW), Parliament bills, DPSA job vacancies
- **Social media / X (Twitter)** — 18+ SA accounts via Nitter (PresidencyZA, SAPoliceService, GovernmentZA, CityofCT, CityofJoburgZA, eThekwiniM, SANDF, Treasury, etc.)
- **Community / suburb-specific** — Facebook group scraping per active user suburb (40+ suburb→page mappings)
- **Auction listings** — Parsed and categorised with special AI prompt

### AI Enrichment (Multi-Provider Cascade)
When one provider hits rate limits, the system automatically falls through:

**Gemini 2.0 Flash → Gemini 1.5 Flash → Groq → Mistral → OpenRouter → Cerebras → SambaNova → DeepSeek**

Each article gets:
- **Summary** — concise AI-generated overview
- **Impact analysis** — how this affects you
- **Actions Now** — immediate steps to take
- **Actions Later** — longer-term actions
- **Spiritual Perspective** — Bible verse from NWT + NIV with prophetic insight
- **JW.org link** — relevant Bible prophecy search

### Fast Scrape + Deferred Enrichment
- Articles are stored **immediately** when scraped (raw)
- AI enrichment runs on a **3-minute parallel queue** — no scrape delay
- Parallel enrichment across all available AI providers

### 5-Tier Location Priority
Articles sorted closest-first: **Suburb → City → Province → Country → Global**

### Deduplication (Content Hash + URL Hash)
- **Content-based** — SHA-256 of `title + body[:200]` prevents duplicate articles
- **URL-based** — Same URL from same source is never re-posted, even if page text changed
- **Multi-outlet** — Same story from different sources merges into one article with multiple `sources[]`

### Breaking News
- Red ticker bar at top of feed for urgent/breaking articles
- Admin can mark any article as urgent via dashboard
- "Listen" button plays top 10 breaking headlines via TTS

### Community Stories Strip
- Instagram/Facebook-style stories carousel at top of feed
- **Strictly social media / unverified content** — Facebook groups, WhatsApp tips, community reports
- Amber ring + ⚠ badge for unverified sources
- Full-screen story viewer with swipe navigation and auto-progress

### Engagement
- **Like / Dislike / Views** counters on every card and article detail
- **Bookmarks** — save articles for later (per user)
- **TTS / Listen** — "Read for Me" audio narration of articles

### Authentication
- **Anonymous device auth** — auto-creates JWT on first visit (no sign-up required)
- **Google OAuth** — optional sign-in for cross-device sync
- **POPIA compliant** — no PII stored, engagement tracking is anonymised

### Onboarding
- **Google Places autocomplete** — suburb picker with accurate location matching
- Province + city auto-filled from suburb selection
- Smart location tier assignment

### Admin Dashboard
- Article stats, visitor counts, engagement metrics
- Archive old articles (30-day auto-cleanup)
- Mark articles as urgent/breaking

### Notifications
- Subscription-based push notifications for new articles matching user location
- Worker dispatches notifications after each scrape cycle

---

## News Categories

| Category | Sources |
|----------|---------|
| Politics | PresidencyZA, GovernmentZA, DIRCO, eNCA, EWN, Daily Maverick, SABC |
| Crime | SAPoliceService |
| Economy | TreasuryRSA, MyBroadband |
| Health | HealthZA |
| Wars | SANDFinfo |
| Local | CityofCT, CityofJoburgZA, eThekwiniM, TimesLIVE, IOL, TheSAnews |
| Community | GroundUp, suburb Facebook pages, community reports |
| Gazette | Government Gazette (GPW) |
| Parliament | Parliamentary bills & committee reports |
| Jobs | DPSA vacancies |
| Auctions | Government & municipal auctions |

---

## Scraping Schedule

| Scraper | Interval | Mode |
|---------|----------|------|
| BBC World + Al Jazeera | 60s | Fast |
| SA Breaking (DM + News24) | 60s | Fast |
| Gov.za media | 60s | Fast |
| SA Local (TimesLIVE + M&G) | 60s | Fast |
| SA Extra (6 outlets) | 60s | Fast |
| SA X/Twitter (18 accounts) | 60s | Fast |
| Community journalism | 5 min | Fast |
| Suburb community (FB pages) | 30 min | Fast |
| Government Gazette | 60 min | Fast |
| Parliament | 60 min | Fast |
| Auctions | 60 min | Full AI |
| DPSA Jobs | 24 hours | Fast |
| AI Enrichment queue | 3 min | Parallel |
| Archive cleanup | 24 hours | — |

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- API keys for at least one AI provider (Gemini recommended)

### 1. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start all services
```bash
make up
# or: docker-compose up -d --build
```

### 3. Access
- **Web app**: http://localhost:3000
- **API**: http://localhost:8000
- **Health check**: http://localhost:8000/health

---

## Production Deployment

```bash
# On the server:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Production differences:
- Web serves on ports **80** and **443** (HTTPS via Let's Encrypt)
- SSL certs mounted from `/etc/letsencrypt`
- All services set to `restart: always`

---

## Environment Variables

```
# AI providers (cascade order)
GEMINI_API_KEY=          # Primary — Gemini 2.0 Flash + 1.5 Flash
GROQ_API_KEY=            # Fallback 1
MISTRAL_API_KEY=         # Fallback 2
OPENROUTER_API_KEY=      # Fallback 3
CEREBRAS_API_KEY=        # Fallback 4
SAMBANOVA_API_KEY=       # Fallback 5
DEEPSEEK_API_KEY=        # Fallback 6

# Database
DB_URL=postgresql://hungu:hungu_secret@db/hungu
DB_PASSWORD=hungu_secret

# Security
JWT_SECRET=              # openssl rand -hex 32
WORKER_API_KEY=          # openssl rand -hex 16
ADMIN_SECRET=            # Admin dashboard access

# App
DOMAIN=hungu.co.za
SCRAPE_INTERVAL_SECS=3600
```

---

## API Endpoints

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/feed` | Paginated news feed with filters |
| GET | `/article/{id}` | Single article detail |
| GET | `/insights/trends` | Category/location trend analytics |
| GET | `/config` | Client configuration |

### Auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/device` | Anonymous device auth → JWT |
| POST | `/auth/google` | Google OAuth sign-in |

### User (JWT required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/user/{id}/bookmarks` | List saved articles |
| POST | `/user/{id}/bookmark/{article_id}` | Save article |
| DELETE | `/user/{id}/bookmark/{article_id}` | Remove saved article |
| POST | `/user/{id}/track` | Anonymised engagement event |
| POST | `/user/{id}/subscription` | Notification subscription |

### Engagement
| Method | Path | Description |
|--------|------|-------------|
| POST | `/articles/{id}/view` | Record article view |
| POST | `/articles/{id}/react` | Like or dislike |

### Worker (X-Worker-Key required)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/articles` | Submit scraped article |
| GET | `/articles/hash/{hash}` | Content + URL dedup pre-check |
| GET | `/articles/needs-enrichment` | Queue of articles needing AI |
| PATCH | `/articles/{id}/enrich` | Submit AI enrichment results |
| GET | `/worker/active-suburbs` | Suburbs with active users |

### Admin (ADMIN_SECRET required)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/archive-old` | Archive articles > 30 days |
| PATCH | `/admin/articles/{id}/urgent` | Toggle breaking/urgent flag |
| GET | `/admin/dashboard` | Stats & metrics |

---

## Project Structure

```
hungu/
├── docker-compose.yml          # Dev compose
├── docker-compose.prod.yml     # Prod override (HTTPS, restart)
├── .env.example                # Environment template
├── Makefile                    # make up / down / logs
├── services/
│   ├── web/                    # Nginx + single-page frontend
│   │   └── index.html          # Full app (Tailwind CSS, vanilla JS)
│   ├── api/                    # FastAPI backend
│   │   ├── main.py             # All endpoints
│   │   └── db.py               # SQLAlchemy models + helpers
│   └── worker/                 # Scraper + AI enrichment
│       └── main.py             # Scheduler, scrapers, AI cascade
└── tests/                      # Test suite
```

---

## Design Principles

- **Suburb-first** — news prioritised by proximity to the user
- **AI-neutral** — multi-provider cascade ensures no single-vendor lock-in
- **Fast ingest** — articles stored raw in seconds, AI enrichment deferred
- **Multi-outlet dedup** — same story from N sources = 1 article with N sources listed
- **No PII** — POPIA-compliant anonymous engagement tracking
- **Mobile-first** — designed for South African mobile users on constrained connections
- **Scriptural lens** — every article paired with Bible perspective (NWT + NIV)

---

*Created by Ntsako Ngobeni — info@hungu.co.za — © 2025 HUNGU. All Rights Reserved.*
