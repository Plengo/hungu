# HUNGU Scalability & High-Availability Plan

As HUNGU transitions from a prototype to a high-traffic production application, the following architectural upgrades ensure the system can handle thousands of concurrent users and high-frequency data scraping.

---

## 1. Infrastructure Scaling (Huawei Cloud)

### Cloud Container Engine (CCE)

Currently Docker Compose is used. For production, move to **Huawei Cloud CCE (Kubernetes)**.

- **Horizontal Pod Autoscaling (HPA):** Automatically increase the number of `web` and `api` containers based on CPU and memory usage.
- **Multi-AZ Deployment:** Deploy containers across multiple Availability Zones in the Johannesburg region to ensure uptime even if one data center fails.

### Elastic Load Balance (ELB)

- Place a Huawei ELB in front of the `web` and `api` services.
- The ELB distributes incoming traffic across all running container instances, preventing any single instance from becoming a bottleneck.

---

## 2. Database & Data Optimization

### Read Replicas (GaussDB / RDS)

News applications are **"Read-Heavy"** — users read far more than they write.

- **Primary Node:** Handles all writes (new articles from the scraper, user bookmarks).
- **Read Replicas:** Use 2–3 replicas strictly for `GET /feed` requests, offloading ~90% of the pressure from the primary database.

### Distributed Caching (Redis)

Use **Huawei Cloud DCS (Redis)** to cache popular news feeds and AI summaries.

- **Feed Caching:** Store the "Pretoria Suburb Feed" in Redis for 5 minutes. The API serves results instantly from memory instead of hitting the database for every request.

---

## 3. Asynchronous AI & Scraping

### Message Queuing

As the number of articles to scrape increases, the worker service may lag.

- **Decoupling:** Use a Message Queue (RabbitMQ or Redis Streams).
- **Workflow:**
  1. The Scraper finds a new link and adds it to the "To Process" queue.
  2. Multiple worker instances pull from the queue, call the Gemini API, and save results.
  3. This prevents the API from waiting on slow scrapers or AI rate limits.

### AI Rate Limit Management

**Gemini API Throttling** — the free tier allows 15 requests/minute.

- **Tiered Processing:** Prioritize "Hard News" and "Wars" for immediate AI processing. "Lifestyle" and "Jobs" are queued and processed once quotas reset.
- **BYOK Offloading:** Encourage "Pro" users to supply their own API keys, removing the rate-limit burden from HUNGU servers entirely.

---

## 4. Content Delivery Network (CDN)

### Global Edge Caching

Use **Huawei Cloud CDN** to cache thumbnails and static frontend assets.

- Users in Cape Town or Durban fetch images from a local edge server rather than the main Johannesburg server, significantly reducing load times and bandwidth costs.

---

## 5. Monitoring & Alerts

- **Cloud Eye:** Configure alerts for 80% CPU usage or elevated database latency.
- **Error Tracking:** Implement Sentry (or similar) to detect and surface bugs before they affect a large percentage of users.
