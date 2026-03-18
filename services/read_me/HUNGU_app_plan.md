# HUNGU: AI-Powered Actionable News & Gazette Intelligence

**HUNGU** (meaning "News" or "Information") is a high-impact news application designed to bridge the gap between "what happened" and "what it means for me." It moves beyond simple aggregation into actionable intelligence by parsing official sources and providing spiritual context.

---

## 🚀 Core Product Vision

HUNGU is built for the "lazy reader" who wants verifiable, high-stakes news without the noise of celebrity gossip or social media rumors.

### 1. Hyper-Local Prioritization

The news feed follows a strict descending order of proximity:

```
Suburb → City → Province → Country → Global
```

> **Example:** A water outage in your specific suburb (e.g., Menlyn) will appear above a national political story.

### 2. The "Impact" Engine *(So What?)*

Every article features an AI-generated section titled **"What this means for us."**

- **Contextual Analysis:** AI explains how a global event (e.g., Iran oil prices) affects a local user (e.g., petrol prices in Pretoria).
- **Hidden Intelligence:** Specifically scrapes Government Gazettes to find "hidden" legislative changes, municipal bylaws, and policy shifts that typical news outlets miss.

### 3. Scriptural & Prophetic Perspective

A mandatory feature for every article (including Jobs, Food, and Exercise):

- **Bible Verses:** AI pairs the news with a relevant scripture (e.g., Wars → Matthew 24; Jobs → Ecclesiastes).
- **Prophecy Context:** Compares current events to JW teachings and Bible prophecy, explaining why these events are happening within the "Sign of the End" framework.

### 4. Audio-First "Lazy" Experience

- **Daily Pulse:** A landing page summary that can be read aloud with one tap.
- **Article Narration:** Every news thumbnail and deep-dive page includes a "Read for Me" option using natural AI voices.

### 5. Categorized Intelligence

Focuses only on high-impact categories:

- **Hard News:** Wars, Politics, Global Conflict, Economy, Health
- **Lifestyle & Utility:** Jobs/Careers, Food/Nutrition, Exercise/Health, Government Gazettes

---

## 🛠️ Microservices Architecture (MVC)

Built for hosting on **Huawei Cloud (South Africa Region)** using a containerized approach:

| Service | Technology | Role |
|---------|------------|------|
| **Web** (View) | React / PWA | Mobile-optimized "Save to Home Screen" app experience |
| **API** (Controller/Model) | FastAPI | Handles persistence, history, and location priority logic |
| **Worker** (Scraper) | Python | Parses GPW (gov.za), job boards, and global news |
| **Database** | PostgreSQL | User history, bookmarks, and cached AI summaries |

---

## 🤖 AI Integration & Persistence

- **LLM:** Gemini 2.5 Flash (utilizing the free tier for caching)
- **BYOK (Bring Your Own Key):** Users can integrate their own AI subscriptions (OpenAI / Gemini Pro) for unlimited, deep-context Q&A
- **History:** Users retain a "Recently Read" list and "Bookmarks" synced across devices

---

## 🛡️ Security & POPIA Compliance

- **Network Isolation:** DB and Scrapers are hidden in an internal Docker network
- **Auth:** Multi-provider signup (Google, Apple/iCloud, Facebook)
- **Data Privacy:** Monetization data is strictly anonymized and aggregated at the suburb/city level

---

## 💰 Monetization Strategy

| Channel | Description |
|---------|-------------|
| **Contextual Ads** | Google AdSense units placed strictly at the bottom of articles |
| **Data Insights** | Selling aggregated trend reports to businesses (e.g., "Sentiment on new tax laws in Gauteng") |
| **Lead Generation** | Connecting users to local service providers (e.g., Solar installers) based on relevant news |

---

## 🏗️ Commands (Makefile)

```bash
make up      # Start all Docker services
make down    # Stop all services
make logs    # Monitor the Scraper and AI Agent in real-time
```
