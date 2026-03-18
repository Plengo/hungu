"""
services/api/db.py
SQLAlchemy models + connection.

Tables
──────
  articles         — scraped & AI-processed items with dedup fields and ETL indexes
  users            — anonymous device users (UUID-only, no email/password, POPIA-safe)
  bookmarks        — user-saved article references (article_ref supports UUID or legacy int)
  engagement_events — POPIA-compliant aggregated analytics (no PII)
  subscriptions    — user notification subscriptions (keywords, categories, push token)
"""
import os, uuid, hashlib
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, Integer,
    ForeignKey, UniqueConstraint, Index, create_engine, types as sqla_types,
)
from sqlalchemy import JSON
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DB_URL = os.getenv("DB_URL", "postgresql://hungu:hungu_secret@db:5432/hungu")
_is_sqlite = DB_URL.startswith("sqlite")

# ── Dialect-aware custom types ─────────────────────────────────────────────────
# These wrappers let the same model code work in both PostgreSQL (production)
# and SQLite (tests). In PostgreSQL they delegate to native UUID/JSONB.

if _is_sqlite:
    # SQLite stores UUIDs as text, JSON as native JSON
    class _UUID(sqla_types.TypeDecorator):
        impl     = Text
        cache_ok = True

        def process_bind_param(self, value, dialect):
            return str(value) if value is not None else None

        def process_result_value(self, value, dialect):
            try:
                return uuid.UUID(value) if value is not None else None
            except (ValueError, AttributeError):
                return value

    class _JSONB(sqla_types.TypeDecorator):
        impl     = JSON
        cache_ok = True
else:
    # Native PostgreSQL types for production
    from sqlalchemy.dialects.postgresql import UUID as _UUID, JSONB as _JSONB

# Aliases used throughout the models
UUIDType  = _UUID(as_uuid=True) if not _is_sqlite else _UUID()
JSONBType = _JSONB()

# SQLite doesn't support pool_size / max_overflow
_pg_kwargs = {} if _is_sqlite else {"pool_size": 5, "max_overflow": 10}
engine = create_engine(DB_URL, pool_pre_ping=True, **_pg_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def make_content_hash(title: str, body: str = "") -> str:
    """SHA-256 of normalised title + body prefix — cross-source deduplication key."""
    blob = (title.lower().strip() + (body or "")[:200].lower().strip()).encode()
    return hashlib.sha256(blob).hexdigest()


def make_url_hash(url: str) -> str:
    return hashlib.sha256(url.lower().strip().encode()).hexdigest()


class Article(Base):
    __tablename__ = "articles"

    # ── Primary key ────────────────────────────────────────────────────────────
    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)

    # ── Content ────────────────────────────────────────────────────────────────
    title         = Column(Text,         nullable=False)
    source        = Column(String(255),  nullable=False)
    sources       = Column(JSONBType,    default=list)   # list of all source names
    category      = Column(String(100),  nullable=False)
    location_tier = Column(String(50),   nullable=False)
    location_name = Column(String(255),  nullable=False)
    summary       = Column(Text)
    full_context  = Column(Text)
    image         = Column(Text)
    impact        = Column(Text)
    url           = Column(Text)

    # ── Deduplication keys ─────────────────────────────────────────────────────
    url_hash      = Column(String(64), nullable=True)                    # first URL seen (indexed, not unique — URL may appear in multiple articles)
    content_hash  = Column(String(64), unique=True, nullable=False)      # title+body hash — THE dedup key

    # ── Scriptural / prophecy fields ──────────────────────────────────────────
    prophecy_verse   = Column(String(100))  # verse reference e.g. "Matthew 24:7"
    prophecy_text    = Column(Text)          # NWT / JW New World Translation text
    prophecy_verse2  = Column(Text)          # NIV (New International Version) text of same verse
    prophecy_insight = Column(Text)

    # ── Reader action fields ──────────────────────────────────────────────────
    actions_now   = Column(Text)   # AI-generated immediate actions
    actions_later = Column(Text)   # AI-generated future actions
    jw_link       = Column(Text)   # JW.org search URL for related Bible topic

    # ── Status flags ───────────────────────────────────────────────────────────
    urgent = Column(Boolean, default=False)
    status = Column(String(20), default="active")  # active | archived

    # ── Timestamps (ETL/analytics-friendly, always timezone-aware) ─────────────
    created_at   = Column(DateTime(timezone=True), nullable=False,
                          default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime(timezone=True), nullable=False,
                          default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))
    published_at = Column(DateTime(timezone=True), nullable=True)   # original pub date
    archived_at  = Column(DateTime(timezone=True), nullable=True)

    bookmarks = relationship("Bookmark", back_populates="article",
                             cascade="all, delete-orphan",
                             foreign_keys="Bookmark.article_uuid")

    # ── Composite indexes for ETL / analytics ─────────────────────────────────
    __table_args__ = (
        Index("ix_art_category_created",  "category",      "created_at"),
        Index("ix_art_tier_created",      "location_tier", "created_at"),
        Index("ix_art_status_created",    "status",        "created_at"),
        Index("ix_art_urgent_created",    "urgent",        "created_at"),
        Index("ix_art_source",            "source"),
        Index("ix_art_published_at",      "published_at"),
    )


class User(Base):
    __tablename__ = "users"

    # ── Primary key ────────────────────────────────────────────────────────────
    # Device-auth: UUID is the identity. No email/password stored. POPIA-safe.
    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)

    # ── Optional profile (user-supplied; all nullable) ─────────────────────────
    display_name = Column(String(100))
    suburb       = Column(String(100))
    city         = Column(String(100))
    province     = Column(String(100))
    country      = Column(String(100), default="South Africa")

    # ── Google OAuth (nullable — device-only users have no Google account) ─────
    google_id = Column(String(255), unique=True, nullable=True)
    email     = Column(String(255), nullable=True)

    # ── Timestamps ─────────────────────────────────────────────────────────────
    created_at   = Column(DateTime(timezone=True), nullable=False,
                          default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime(timezone=True), nullable=False,
                          default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime(timezone=True))

    bookmarks = relationship("Bookmark", back_populates="user",
                             cascade="all, delete-orphan")


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)

    # ── References ─────────────────────────────────────────────────────────────
    user_id = Column(UUIDType,
                     ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # article_ref stores whatever the client sends (UUID string or legacy "1","2"…)
    article_ref  = Column(String(100), nullable=False)

    # article_uuid is set when the article exists in the articles table
    article_uuid = Column(UUIDType,
                          ForeignKey("articles.id", ondelete="SET NULL"),
                          nullable=True)

    # ── Timestamps ─────────────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    user    = relationship("User",    back_populates="bookmarks")
    article = relationship("Article", back_populates="bookmarks",
                           foreign_keys=[article_uuid])

    __table_args__ = (
        UniqueConstraint("user_id", "article_ref", name="uq_bookmark_user_article"),
        Index("ix_bookmarks_user_created", "user_id", "created_at"),
    )


class EngagementEvent(Base):
    """Aggregated analytics row — no user PII. POPIA-compliant."""
    __tablename__ = "engagement_events"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    location_tier = Column(String(50),  nullable=False)
    category      = Column(String(100), nullable=False)
    event_type    = Column(String(50),  default="view")
    created_at    = Column(DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_eng_tier_cat_created", "location_tier", "category", "created_at"),
    )


class Subscription(Base):
    """
    User notification subscription.
    A user can subscribe to any combination of:
      - categories  (e.g. ["Politics", "Health"])
      - keywords    (e.g. ["load shedding", "NHI", "Eskom"])
      - location_tiers (e.g. ["Suburb", "City"])
    push_token: web push subscription JSON (stringified) or FCM token.
    """
    __tablename__ = "subscriptions"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)

    user_id = Column(UUIDType,
                     ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Notification channel
    push_token = Column(Text, nullable=True)   # Web Push JSON or FCM device token

    # What to notify about (stored as JSON arrays)
    categories     = Column(JSONBType, default=list)   # e.g. ["Politics", "Health"]
    keywords       = Column(JSONBType, default=list)   # e.g. ["load shedding", "Eskom"]
    location_tiers = Column(JSONBType, default=list)   # e.g. ["Suburb", "City"]
    notify_urgent  = Column(Boolean, default=True) # always notify on urgent=True

    active     = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_subscription_user"),  # one sub per user
        Index("ix_sub_active", "active"),
    )


class PageView(Base):
    """Anonymous page visit tracker — no PII stored (only device UUID + timestamp)."""
    __tablename__ = "page_views"

    id         = Column(Integer,     primary_key=True, autoincrement=True)
    visitor_id = Column(String(64),  nullable=False, index=True)  # device UUID from localStorage
    page       = Column(String(50),  default="feed")
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_pv_visitor_created", "visitor_id", "created_at"),
    )


def init_db():
    """Create all tables if they don't exist. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine)
