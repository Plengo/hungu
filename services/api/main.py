"""
HUNGU API v2 — FastAPI service with PostgreSQL backend + JWT device auth.

Public endpoints:
  GET    /health
  GET    /feed
  GET    /article/{id}

Worker endpoints (X-Worker-Key header required):
  POST   /articles                  — submit a processed article
  GET    /articles/hash/{hash}      — dedup pre-check (saves Gemini credits)
  POST   /admin/archive-old         — archive articles older than 30 days

Auth endpoints:
  POST   /auth/device               — create anonymous device user, returns JWT

User endpoints (JWT Bearer required; own data only):
  GET    /user/{user_id}/bookmarks
  POST   /user/{user_id}/bookmark/{article_id}
  DELETE /user/{user_id}/bookmark/{article_id}
  POST   /user/{user_id}/track      — anonymised engagement (no PII stored)

Analytics:
  GET    /insights/trends
"""

import os
import uuid
import datetime
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from jose import JWTError, jwt
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from db import (
    init_db, get_db, make_content_hash, make_url_hash,
    Article as ArticleModel, User as UserModel,
    Bookmark as BookmarkModel, EngagementEvent, Subscription as SubscriptionModel,
    PageView,
)

# ─── Config ───────────────────────────────────────────────────────────────────
JWT_SECRET      = os.getenv("JWT_SECRET", "change-this-secret")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_DAYS = 180
WORKER_API_KEY    = os.getenv("WORKER_API_KEY", "")
ADMIN_SECRET      = os.getenv("ADMIN_SECRET", "")
GOOGLE_CLIENT_ID  = os.getenv("GOOGLE_CLIENT_ID", "")

bearer = HTTPBearer(auto_error=False)

TIER_PRIORITY = {"Suburb": 1, "City": 2, "Province": 3, "Country": 4, "Global": 5}

# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_demo_articles()
    yield

app = FastAPI(
    title="HUNGU API", version="2.0.0",
    description="AI-Powered Hyper-Local News for South Africa",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth helpers ─────────────────────────────────────────────────────────────

def make_token(user_id: str) -> str:
    exp = datetime.datetime.utcnow() + datetime.timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _decode_token(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def require_own_user(
    user_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> str:
    """JWT guard — ensures the caller can only access their own data."""
    current = _decode_token(credentials)
    if current != user_id:
        raise HTTPException(status_code=403, detail="Access denied — you can only access your own data")
    return current

def require_worker_key(request: Request):
    """Shared-secret guard for worker → API calls."""
    if not WORKER_API_KEY:
        return  # key not configured — open in dev mode
    if request.headers.get("X-Worker-Key", "") != WORKER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid worker key")

def require_admin(request: Request):
    """Admin-secret guard for admin dashboard."""
    if not ADMIN_SECRET:
        return  # no secret configured — open in dev mode
    if request.headers.get("X-Admin-Key", "") != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Admin access required")

# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class ArticleIn(BaseModel):
    title: str
    source: str
    category: str
    location_tier: str
    location_name: str
    summary: Optional[str] = ""
    full_context: Optional[str] = ""
    image: Optional[str] = ""
    impact: Optional[str] = ""
    url: Optional[str] = ""
    prophecy: Optional[dict] = None
    urgent: bool = False
    published_at: Optional[str] = None
    raw_text: Optional[str] = ""   # used for content_hash only, not stored
    actions_now:   Optional[str] = ""
    actions_later: Optional[str] = ""
    jw_link:       Optional[str] = ""

class TrackRequest(BaseModel):
    article_id: str
    location_tier: str
    category: str

class ArticleEnrichIn(BaseModel):
    impact:           Optional[str] = None
    actions_now:      Optional[str] = None
    actions_later:    Optional[str] = None
    prophecy_verse:   Optional[str] = None
    prophecy_text:    Optional[str] = None
    prophecy_verse2:  Optional[str] = None
    prophecy_insight: Optional[str] = None
    jw_link:          Optional[str] = None

class SubscriptionIn(BaseModel):
    keywords:       List[str] = []
    categories:     List[str] = []
    location_tiers: List[str] = []
    notify_urgent:  bool = True
    push_token:     Optional[str] = None

class PingIn(BaseModel):
    visitor_id: str
    page: Optional[str] = "feed"

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_out(a: ArticleModel) -> dict:
    return {
        "id":            str(a.id),
        "source":        a.source,
        "sources":       a.sources or [a.source],
        "category":      a.category,
        "location_tier": a.location_tier,
        "location_name": a.location_name,
        "title":         a.title,
        "summary":       a.summary or "",
        "full_context":  a.full_context or "",
        "image":         a.image or "",
        "impact":        a.impact or "",
        "prophecy": {
            "verse":   a.prophecy_verse   or "",
            "text":    a.prophecy_text    or "",
            "verse2":  a.prophecy_verse2  or "",
            "insight": a.prophecy_insight or "",
        },
        "urgent":       bool(a.urgent),
        "status":       a.status or "active",
        "actions_now":   a.actions_now   or "",
        "actions_later": a.actions_later or "",
        "jw_link":       a.jw_link       or "",
        "url":           a.url           or "",
        "created_at":   a.created_at.isoformat()   if a.created_at   else "",
        "updated_at":   a.updated_at.isoformat()   if a.updated_at   else "",
        "published_at": a.published_at.isoformat() if a.published_at else None,
    }

# ─── Routes ─── health ────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.datetime.utcnow().isoformat()}

# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/config")
async def get_config():
    """Return public runtime config (safe to expose — no secrets)."""
    return {"google_client_id": GOOGLE_CLIENT_ID}


class GoogleAuthIn(BaseModel):
    id_token: str


@app.post("/auth/google")
async def google_auth(body: GoogleAuthIn, db: Session = Depends(get_db)):
    """Verify a Google ID token and return a HUNGU JWT."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured — set GOOGLE_CLIENT_ID")
    try:
        idinfo = google_id_token.verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_id  = idinfo["sub"]
    email      = idinfo.get("email", "")
    name       = idinfo.get("name", "")
    avatar     = idinfo.get("picture", "")

    # Find existing user by google_id, else create
    user = db.query(UserModel).filter(UserModel.google_id == google_id).first()
    if not user:
        user = UserModel(google_id=google_id, email=email, display_name=name)
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            user = db.query(UserModel).filter(UserModel.google_id == google_id).first()

    uid = str(user.id)
    return {
        "user_id": uid,
        "token":   make_token(uid),
        "name":    user.display_name or name,
        "email":   email,
        "avatar":  avatar,
    }


@app.post("/auth/device", status_code=201)
async def create_device_user(db: Session = Depends(get_db)):
    """
    Create an anonymous device user. Call once on first app launch.
    Store the returned user_id and token in localStorage — no email required.
    """
    user = UserModel()
    db.add(user)
    db.commit()
    db.refresh(user)
    uid = str(user.id)
    return {"user_id": uid, "token": make_token(uid)}

# ─── Feed (public) ────────────────────────────────────────────────────────────

@app.get("/feed")
async def get_feed(
    category: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    from datetime import timedelta
    week_ago = datetime.datetime.now(datetime.timezone.utc) - timedelta(days=7)
    q = db.query(ArticleModel).filter(
        ArticleModel.status == "active",
        ArticleModel.created_at >= week_ago,
    )
    if category and category.lower() != "all":
        q = q.filter(ArticleModel.category.ilike(category))
    articles = q.order_by(ArticleModel.created_at.desc()).limit(limit).all()
    return [_to_out(a) for a in articles]

@app.get("/article/{article_id}")
async def get_article(article_id: str, db: Session = Depends(get_db)):
    a = db.query(ArticleModel).filter(ArticleModel.id == article_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Article not found")
    return _to_out(a)

# ─── Worker submission ────────────────────────────────────────────────────────

@app.get("/articles/hash/{content_hash_val}")
async def article_exists(content_hash_val: str, request: Request,
                          db: Session = Depends(get_db)):
    """
    Worker calls this BEFORE running Gemini to avoid wasting AI credits on duplicates.
    Returns 200+sources if article already exists, 404 if it does not.
    """
    require_worker_key(request)
    a = db.query(ArticleModel).filter(ArticleModel.content_hash == content_hash_val).first()
    if not a:
        raise HTTPException(status_code=404, detail="Not found")
    return {"id": str(a.id), "sources": a.sources or [a.source]}

@app.get("/articles/needs-enrichment")
async def needs_enrichment(
    request: Request,
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Return articles missing AI-generated fields so the worker can enrich them."""
    require_worker_key(request)
    from sqlalchemy import or_
    articles = (
        db.query(ArticleModel)
          .filter(
              ArticleModel.status == "active",
              ArticleModel.category != "Auctions",
              or_(
                  ArticleModel.actions_now == None,
                  ArticleModel.actions_now == "",
                  ArticleModel.impact == None,
                  ArticleModel.impact == "",
                  ArticleModel.impact == "Impact analysis pending.",
                  ArticleModel.prophecy_verse == None,
                  ArticleModel.prophecy_verse == "",
                  ArticleModel.prophecy_verse2 == None,
                  ArticleModel.prophecy_verse2 == "",
                  ArticleModel.prophecy_insight == None,
                  ArticleModel.prophecy_insight == "",
              )
          )
          .order_by(ArticleModel.created_at.desc())
          .limit(limit)
          .all()
    )
    return [
        {"id": str(a.id), "title": a.title,
         "full_context": a.full_context or "", "summary": a.summary or "",
         "source": a.source, "category": a.category}
        for a in articles
    ]

@app.patch("/articles/{article_id}/enrich", status_code=200)
async def enrich_article(
    article_id: str,
    body: ArticleEnrichIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Worker PATCH to fill missing AI fields on previously stored articles."""
    require_worker_key(request)
    a = db.query(ArticleModel).filter(ArticleModel.id == article_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Article not found")
    if body.impact           is not None: a.impact            = body.impact
    if body.actions_now      is not None: a.actions_now       = body.actions_now
    if body.actions_later    is not None: a.actions_later     = body.actions_later
    if body.prophecy_verse   is not None: a.prophecy_verse    = body.prophecy_verse
    if body.prophecy_text    is not None: a.prophecy_text     = body.prophecy_text
    if body.prophecy_verse2  is not None: a.prophecy_verse2   = body.prophecy_verse2
    if body.prophecy_insight is not None: a.prophecy_insight  = body.prophecy_insight
    if body.jw_link          is not None: a.jw_link           = body.jw_link
    a.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return {"status": "enriched", "id": str(a.id)}

@app.post("/articles", status_code=201)
async def create_article(body: ArticleIn, request: Request,
                          db: Session = Depends(get_db)):
    require_worker_key(request)
    ch = make_content_hash(body.title, body.raw_text or body.full_context or "")

    # Dedup: if exists, just add the source name if it's new
    existing = db.query(ArticleModel).filter(ArticleModel.content_hash == ch).first()
    if existing:
        srcs = list(existing.sources or [existing.source])
        if body.source not in srcs:
            srcs.append(body.source)
            existing.sources = srcs
            existing.updated_at = datetime.datetime.now(datetime.timezone.utc)
            db.commit()
        return {"id": str(existing.id), "status": "duplicate", "sources": srcs}

    p = body.prophecy or {}
    pub_at = None
    if body.published_at:
        try:
            pub_at = datetime.datetime.fromisoformat(body.published_at)
        except ValueError:
            pass

    article = ArticleModel(
        title=body.title,        source=body.source,      sources=[body.source],
        category=body.category,  location_tier=body.location_tier,
        location_name=body.location_name,
        summary=body.summary,    full_context=body.full_context,
        image=body.image,        impact=body.impact,
        url=body.url,            url_hash=make_url_hash(body.url) if body.url else None,
        content_hash=ch,
        prophecy_verse=p.get("verse", ""),
        prophecy_text=p.get("text", ""),
        prophecy_insight=p.get("insight", ""),
        actions_now=body.actions_now,
        actions_later=body.actions_later,
        jw_link=body.jw_link,
        urgent=body.urgent,
        published_at=pub_at,
    )
    try:
        db.add(article)
        db.commit()
        db.refresh(article)
    except IntegrityError:
        db.rollback()
        existing = db.query(ArticleModel).filter(ArticleModel.content_hash == ch).first()
        if existing:
            return {"id": str(existing.id), "status": "duplicate"}
        # Rare: some other unique constraint collision — return a safe error
        raise HTTPException(status_code=409, detail="Article already exists")
    return {"id": str(article.id), "status": "created"}

# ─── Bookmarks / saved posts ──────────────────────────────────────────────────

@app.get("/user/{user_id}/bookmarks")
async def get_bookmarks(
    user_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_own_user),
):
    """Returns the list of saved article references for this user (own data only)."""
    bks = (
        db.query(BookmarkModel)
          .filter(BookmarkModel.user_id == user_id)
          .order_by(BookmarkModel.created_at.desc())
          .all()
    )
    return [{"article_ref": b.article_ref, "saved_at": b.created_at.isoformat()} for b in bks]

@app.post("/user/{user_id}/bookmark/{article_id}", status_code=201)
async def add_bookmark(
    user_id: str, article_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_own_user),
):
    """Save an article. article_id can be a UUID (DB article) or a legacy integer string."""
    # Resolve optional FK to articles table
    art_uuid = None
    try:
        a = db.query(ArticleModel).filter(ArticleModel.id == article_id).first()
        if a:
            art_uuid = a.id
    except Exception:
        pass

    bk = BookmarkModel(user_id=user_id, article_ref=article_id, article_uuid=art_uuid)
    try:
        db.add(bk)
        db.commit()
    except IntegrityError:
        db.rollback()  # already bookmarked — idempotent
    return {"status": "saved", "article_ref": article_id}

@app.delete("/user/{user_id}/bookmark/{article_id}", status_code=200)
async def remove_bookmark(
    user_id: str, article_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_own_user),
):
    db.query(BookmarkModel).filter(
        BookmarkModel.user_id == user_id,
        BookmarkModel.article_ref == article_id,
    ).delete()
    db.commit()
    return {"status": "removed", "article_ref": article_id}

# ─── Engagement tracking (POPIA: no PII) ─────────────────────────────────────

@app.post("/user/{user_id}/track", status_code=204)
async def track_event(user_id: str, body: TrackRequest, db: Session = Depends(get_db)):
    db.add(EngagementEvent(
        location_tier=body.location_tier,
        category=body.category,
        event_type="view",
    ))
    db.commit()

@app.get("/insights/trends")
async def get_trends(db: Session = Depends(get_db)):
    from sqlalchemy import func
    rows = (
        db.query(EngagementEvent.location_tier, EngagementEvent.category,
                 func.count().label("count"))
          .group_by(EngagementEvent.location_tier, EngagementEvent.category)
          .all()
    )
    return {"trends": [{"tier": r[0], "category": r[1], "count": r[2]} for r in rows]}

# ─── Visitor analytics ────────────────────────────────────────────────────────

@app.post("/stats/ping", status_code=204)
async def stats_ping(body: PingIn, db: Session = Depends(get_db)):
    """Record an anonymous page visit. visitor_id is the device UUID — no PII stored."""
    vid = (body.visitor_id or "")[:64].strip()
    if not vid:
        return
    db.add(PageView(visitor_id=vid, page=body.page or "feed"))
    db.commit()

@app.get("/stats")
async def get_platform_stats(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
):
    """Platform-wide aggregate visitor stats. Requires a valid JWT."""
    _decode_token(credentials)
    from sqlalchemy import func, distinct
    cutoff_15m = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    cutoff_24h = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    total_views     = db.query(PageView).count()
    unique_visitors = db.query(func.count(distinct(PageView.visitor_id))).scalar() or 0
    active_now      = db.query(func.count(distinct(PageView.visitor_id))) \
                        .filter(PageView.created_at >= cutoff_15m).scalar() or 0
    daily_active    = db.query(func.count(distinct(PageView.visitor_id))) \
                        .filter(PageView.created_at >= cutoff_24h).scalar() or 0
    total_articles  = db.query(ArticleModel).filter(ArticleModel.status == "active").count()
    total_bookmarks = db.query(BookmarkModel).count()
    return {
        "total_views":         total_views,
        "unique_visitors":     unique_visitors,
        "active_last_15min":   active_now,
        "daily_active":        daily_active,
        "total_articles_live": total_articles,
        "total_bookmarks":     total_bookmarks,
    }

# ─── Admin: archive old posts ─────────────────────────────────────────────────

@app.post("/admin/archive-old")
async def archive_old(request: Request, db: Session = Depends(get_db)):
    require_worker_key(request)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    n = (
        db.query(ArticleModel)
          .filter(ArticleModel.status == "active", ArticleModel.created_at < cutoff)
          .update(
              {"status": "archived",
               "archived_at": datetime.datetime.now(datetime.timezone.utc)},
              synchronize_session="fetch",
          )
    )
    db.commit()
    return {"archived": n}

@app.get("/admin/dashboard")
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    """Full platform stats. Protected by X-Admin-Key header."""
    require_admin(request)
    from sqlalchemy import func, distinct, or_
    cutoff_15m = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    cutoff_24h = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    total_views      = db.query(PageView).count()
    unique_visitors  = db.query(func.count(distinct(PageView.visitor_id))).scalar() or 0
    active_now       = db.query(func.count(distinct(PageView.visitor_id))) \
                         .filter(PageView.created_at >= cutoff_15m).scalar() or 0
    daily_active     = db.query(func.count(distinct(PageView.visitor_id))) \
                         .filter(PageView.created_at >= cutoff_24h).scalar() or 0
    total_articles   = db.query(ArticleModel).filter(ArticleModel.status == "active").count()
    articles_enriched = db.query(ArticleModel).filter(
        ArticleModel.status == "active",
        ArticleModel.actions_now.isnot(None),
        ArticleModel.actions_now != "",
    ).count()
    total_bookmarks  = db.query(BookmarkModel).count()

    # Category breakdown
    cat_rows = (
        db.query(ArticleModel.category, func.count().label("count"))
          .filter(ArticleModel.status == "active")
          .group_by(ArticleModel.category)
          .all()
    )
    by_category = {r[0]: r[1] for r in cat_rows}

    # Recent articles
    recent = (
        db.query(ArticleModel)
          .filter(ArticleModel.status == "active")
          .order_by(ArticleModel.created_at.desc())
          .limit(10)
          .all()
    )

    # Needs enrichment count
    needs_enrich = db.query(ArticleModel).filter(
        ArticleModel.status == "active",
        or_(ArticleModel.actions_now == None, ArticleModel.actions_now == ""),
    ).count()

    return {
        "total_views":          total_views,
        "unique_visitors":      unique_visitors,
        "active_last_15min":    active_now,
        "daily_active":         daily_active,
        "total_articles":       total_articles,
        "articles_enriched":    articles_enriched,
        "articles_pending":     needs_enrich,
        "total_bookmarks":      total_bookmarks,
        "articles_by_category": by_category,
        "recent_articles": [
            {"id": str(a.id), "title": a.title, "category": a.category,
             "source": a.source, "created_at": a.created_at.isoformat(),
             "enriched": bool(a.actions_now)}
            for a in recent
        ],
    }

# ─── Subscriptions ────────────────────────────────────────────────────────────

def _sub_out(s: SubscriptionModel) -> dict:
    return {
        "id":             str(s.id),
        "keywords":       s.keywords       or [],
        "categories":     s.categories     or [],
        "location_tiers": s.location_tiers or [],
        "notify_urgent":  bool(s.notify_urgent),
        "push_token":     s.push_token,
        "active":         bool(s.active),
        "created_at":     s.created_at.isoformat() if s.created_at else "",
        "updated_at":     s.updated_at.isoformat() if s.updated_at else "",
    }

@app.get("/user/{user_id}/subscription")
async def get_subscription(
    user_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_own_user),
):
    """Returns the user's notification subscription (or 404 if not set up)."""
    s = db.query(SubscriptionModel).filter(
        SubscriptionModel.user_id == user_id,
        SubscriptionModel.active == True,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="No subscription found")
    return _sub_out(s)

@app.post("/user/{user_id}/subscription", status_code=201)
async def upsert_subscription(
    user_id: str,
    body: SubscriptionIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_own_user),
):
    """
    Create or update the user's single notification subscription.
    One subscription per user — upserts to avoid duplicates.
    """
    # Sanitise inputs
    keywords       = [k.strip().lower() for k in (body.keywords or []) if k.strip()][:50]
    categories     = [c.strip()         for c in (body.categories or [])  if c.strip()][:20]
    location_tiers = [l.strip()         for l in (body.location_tiers or []) if l.strip()][:10]

    s = db.query(SubscriptionModel).filter(SubscriptionModel.user_id == user_id).first()
    now = datetime.datetime.now(datetime.timezone.utc)
    if s:
        s.keywords       = keywords
        s.categories     = categories
        s.location_tiers = location_tiers
        s.notify_urgent  = body.notify_urgent
        s.push_token     = body.push_token
        s.active         = True
        s.updated_at     = now
        db.commit()
        db.refresh(s)
        return {**_sub_out(s), "status": "updated"}
    else:
        s = SubscriptionModel(
            user_id        = user_id,
            keywords       = keywords,
            categories     = categories,
            location_tiers = location_tiers,
            notify_urgent  = body.notify_urgent,
            push_token     = body.push_token,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return {**_sub_out(s), "status": "created"}

@app.delete("/user/{user_id}/subscription", status_code=200)
async def delete_subscription(
    user_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_own_user),
):
    """Deactivate (soft-delete) the user's subscription. Preserves DB record."""
    s = db.query(SubscriptionModel).filter(SubscriptionModel.user_id == user_id).first()
    if s:
        s.active     = False
        s.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
    return {"status": "unsubscribed"}

# ─── Notification matching (worker → API) ─────────────────────────────────────

class NotifyDispatchIn(BaseModel):
    article_ids: List[str]

@app.post("/internal/notifications/dispatch")
async def dispatch_notifications(
    body: NotifyDispatchIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Worker calls this after submitting new articles.
    Finds all active subscriptions that match any of the articles by:
      - keyword (in title, summary, or impact)
      - category match
      - location_tier match
      - urgent flag when notify_urgent=True
    Returns a list of {user_id, article_id, matched_on} dicts for future push delivery.
    """
    require_worker_key(request)
    if not body.article_ids:
        return {"matches": []}

    # Fetch only the articles just submitted (avoid full table scan)
    articles = (
        db.query(ArticleModel)
          .filter(ArticleModel.id.in_(body.article_ids))
          .all()
    )
    if not articles:
        return {"matches": []}

    # Fetch all active subscriptions
    subscriptions = db.query(SubscriptionModel).filter(SubscriptionModel.active == True).all()
    matches = []

    for art in articles:
        art_text = " ".join(filter(None, [art.title, art.summary, art.impact])).lower()
        for sub in subscriptions:
            matched_on = None

            # 1. Urgent flag
            if art.urgent and sub.notify_urgent:
                matched_on = "urgent"

            # 2. Category match
            if not matched_on and sub.categories:
                if art.category in sub.categories:
                    matched_on = f"category:{art.category}"

            # 3. Location tier match
            if not matched_on and sub.location_tiers:
                if art.location_tier in sub.location_tiers:
                    matched_on = f"location_tier:{art.location_tier}"

            # 4. Keyword match (case-insensitive substring in title/summary/impact)
            if not matched_on and sub.keywords:
                for kw in sub.keywords:
                    if kw.lower() in art_text:
                        matched_on = f"keyword:{kw}"
                        break

            if matched_on:
                matches.append({
                    "user_id":    str(sub.user_id),
                    "article_id": str(art.id),
                    "matched_on": matched_on,
                    "push_token": sub.push_token,
                })

    return {"matches": matches, "article_count": len(articles), "subscription_count": len(subscriptions)}

# ─── Demo seed ────────────────────────────────────────────────────────────────

def _seed_demo_articles():
    """Insert 3 demo articles if the DB is empty — visible immediately on first run."""
    from sqlalchemy.orm import sessionmaker
    from db import engine as _engine
    S = sessionmaker(bind=_engine)
    with S() as db:
        if db.query(ArticleModel).count() > 0:
            return
        from db import make_content_hash as _ch
        demos = [
            ArticleModel(
                title="Menlyn Water Main Maintenance — Saturday Outage",
                source="Government Gazette (GPW)", sources=["Government Gazette (GPW)"],
                category="Local", location_tier="Suburb", location_name="Menlyn",
                summary="Maintenance crews will work on the primary pipeline along Atterbury Road this Saturday.",
                full_context="Tshwane Metro scheduled emergency maintenance on bulk water supply infrastructure in the Menlyn area. Works commence 08:00, complete by 16:00.",
                image="https://images.unsplash.com/photo-1504711434969-e33886168f5c?auto=format&fit=crop&w=800&q=80",
                impact="Your household in Menlyn will have no water from 08:00–16:00 on Saturday. Store at least 20 litres.",
                prophecy_verse="Isaiah 41:17",
                prophecy_text="The afflicted and poor are seeking water, but there is none...",
                prophecy_insight="Infrastructure challenges remind us of the biblical promise where all needs are met.",
                urgent=True,
                content_hash=_ch("Menlyn Water Main Maintenance — Saturday Outage"),
            ),
            ArticleModel(
                title="New Provincial Vehicle Licensing Fee Adjustments",
                source="Gauteng Provincial Gazette", sources=["Gauteng Provincial Gazette"],
                category="Economy", location_tier="Province", location_name="Gauteng",
                summary="Gauteng government announced a 5% increase in vehicle licensing fees effective next month.",
                full_context="Following a review of operational costs, the Gauteng Department of Roads and Transport gazetted a 5% increase across all vehicle license renewal fees.",
                image="https://images.unsplash.com/photo-1554224155-1696413565d3?auto=format&fit=crop&w=800&q=80",
                impact="Your annual car registration will increase by approximately R75 for an average sedan.",
                prophecy_verse="James 5:4",
                prophecy_text="Look! The wages you kept back cry out...",
                prophecy_insight="Economic pressures highlight the ongoing need for justice in society.",
                urgent=False,
                content_hash=_ch("New Provincial Vehicle Licensing Fee Adjustments"),
            ),
            ArticleModel(
                title="Tshwane Council Passes Load-Shedding Mitigation Budget",
                source="Pretoria City News", sources=["Pretoria City News"],
                category="Politics", location_tier="City", location_name="Pretoria",
                summary="City council approved R2.3 billion for solar and battery backup at critical facilities.",
                full_context="The Tshwane Metropolitan Council approved an emergency budget of R2.3 billion for solar PV and battery storage at hospitals, pumping stations, and traffic centres.",
                image="https://images.unsplash.com/photo-1508514177221-188b1cf16e9d?auto=format&fit=crop&w=800&q=80",
                impact="Hospitals and key infrastructure in Pretoria will be load-shedding free within 18 months.",
                prophecy_verse="Proverbs 21:5",
                prophecy_text="The plans of the diligent lead to profit...",
                prophecy_insight="Prudent planning for community resilience echoes timeless principles of wise stewardship.",
                urgent=False,
                content_hash=_ch("Tshwane Council Passes Load-Shedding Mitigation Budget"),
            ),
        ]
        db.add_all(demos)
        db.commit()

