# HUNGU: Development & GitHub Copilot Guide

This document explains the project structure and provides specific instructions for using GitHub Copilot to build out the HUNGU microservices.

---

## 📁 File Structure & Responsibilities

### 1. Root Directory

- **`Makefile`**: The "Remote Control." Use this for high-level commands (`make up`, `make logs`).
- **`docker-compose.yml`**: The "Orchestrator." Defines how the Web, API, Worker, and Database talk to each other securely.
- **`.env`**: The "Vault." Stores your Gemini API keys and Firebase credentials. **Never commit this to GitHub.**

### 2. `services/web/` (The View)

- **Technology:** React (Next.js) + Tailwind CSS
- **Role:** The user interface. Handles the Instagram-style scroll, the "Read for Me" audio player, and Bottom-Ad placements.
- **Key Logic:** Must check `localStorage` for a user's "Bring Your Own Key" (BYOK) settings.

### 3. `services/api/` (The Controller)

- **Technology:** Python (FastAPI)
- **Role:** The bridge. It talks to the Database and validates User Auth.
- **Key Logic:** Implements the Prioritization Algorithm (`Suburb → City → Province → Country`) when serving the news feed.

### 4. `services/worker/` (The Brain/Scraper)

- **Technology:** Python (BeautifulSoup/Playwright) + Gemini AI
- **Role:** The background worker. It scrapes gov.za, global news, and job boards.
- **Key Logic:** The "Prophecy Engine." Sends news to Gemini to generate the "So What?" impact and the relevant Bible Verse mapping.

---

## 🤖 How to Use GitHub Copilot with this Project

When working in a specific file, "feed" Copilot the context of the `README.md` and this `GUIDE.md`.

### To Build the Scraper (Worker)

Open `services/worker/scraper.py` and tell Copilot:

> Based on the HUNGU README.md, write a Python scraper using Playwright that monitors the South African Government Gazette (gov.za). It should extract the text, send it to Gemini 2.5 Flash to generate a 'What this means for us' impact summary for a user in `{{suburb}}`, and find a matching Bible verse based on the category.

### To Build the Feed Logic (API)

Open `services/api/main.py` and tell Copilot:

> Create a FastAPI endpoint `/feed` that takes a `user_id`. It should fetch articles from PostgreSQL and sort them by the HUNGU priority logic: Suburb match first, then City, then Province, then Country. Ensure anonymized tracking of which articles the user clicks for monetization sentiment reports.

### To Build the UI (Web)

Open `services/web/Feed.jsx` and tell Copilot:

> Build a mobile-first news feed component for HUNGU. Use an Instagram-style vertical scroll. Each card should have a high-quality thumbnail, the news source name, an 'Impact' tag, and a 'Read for Me' audio button. Add a placeholder at the very bottom of the detail view for a Google AdSense unit.

---

## 🛡️ Security Check

Whenever Copilot generates code for the API or Database, remind it:

> Ensure this code follows the HUNGU security policy: No ports exposed except for the Web service, use JWT for authentication, and ensure all data collection for monetization is anonymized per POPIA regulations.
