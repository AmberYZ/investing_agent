from __future__ import annotations

import datetime as dt
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    source_type: Mapped[str] = mapped_column(String(32), default="pdf", index=True)
    source_name: Mapped[str] = mapped_column(String(256), default="wechat")
    source_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    filename: Mapped[str] = mapped_column(Text)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), index=True)
    modified_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)  # document date (e.g. file mtime); used as timestamp for grouping

    gcs_raw_uri: Mapped[str] = mapped_column(Text)
    gcs_text_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    num_pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    jobs: Mapped[list["IngestJob"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)  # queued|processing|done|error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), index=True)
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="jobs")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    # MVP: store embeddings as JSON for sqlite compatibility.
    # Phase 2: migrate to pgvector on Postgres for faster similarity search.
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
        Index("ix_chunks_document_id_chunk_index", "document_id", "chunk_index"),
    )


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_label: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))
    # system = auto-extracted or admin-created; user = created via "Create theme" in app
    created_by: Mapped[str] = mapped_column(String(32), default="system", index=True)
    # User-editable notes for this theme (single note per theme in MVP).
    user_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Embedding of canonical_label for semantic similarity (theme deduplication).
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)

    narratives: Mapped[list["Narrative"]] = relationship(back_populates="theme", cascade="all, delete-orphan")
    aliases: Mapped[list["ThemeAlias"]] = relationship(back_populates="theme", cascade="all, delete-orphan")
    instruments: Mapped[list["ThemeInstrument"]] = relationship(back_populates="theme", cascade="all, delete-orphan")


class ThemeAlias(Base):
    __tablename__ = "theme_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(256), index=True)
    created_by: Mapped[str] = mapped_column(String(32), default="system")  # system|user
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    theme: Mapped["Theme"] = relationship(back_populates="aliases")

    __table_args__ = (UniqueConstraint("theme_id", "alias", name="uq_theme_aliases_theme_alias"),)


class ThemeInstrument(Base):
    """Stock/ETF ticker associated with a theme. source: manual | from_documents | llm_suggested."""
    __tablename__ = "theme_instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    type: Mapped[str] = mapped_column(String(16), default="stock")  # stock | etf | other
    source: Mapped[str] = mapped_column(String(24), default="manual", index=True)  # manual | from_documents | llm_suggested
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    theme: Mapped["Theme"] = relationship(back_populates="instruments")

    __table_args__ = (UniqueConstraint("theme_id", "symbol", name="uq_theme_instruments_theme_symbol"),)


class Narrative(Base):
    __tablename__ = "narratives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    relation_to_prevailing: Mapped[str] = mapped_column(String(24), default="unlabeled", index=True)  # consensus|contrarian|refinement|new_angle
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), index=True)
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), index=True)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), index=True)
    sub_theme: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    narrative_stance: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)  # bullish|bearish|mixed|neutral from LLM
    confidence_level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # fact|opinion from LLM

    theme: Mapped["Theme"] = relationship(back_populates="narratives")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="narrative", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("theme_id", "statement", name="uq_narratives_theme_statement"),)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    narrative_id: Mapped[int] = mapped_column(ForeignKey("narratives.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    quote: Mapped[str] = mapped_column(Text)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    narrative: Mapped["Narrative"] = relationship(back_populates="evidence")


class ThemeMentionsDaily(Base):
    __tablename__ = "theme_mentions_daily"

    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    share_of_voice: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class ThemeRelationDaily(Base):
    __tablename__ = "theme_relation_daily"

    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    consensus_count: Mapped[int] = mapped_column(Integer, default=0)
    contrarian_count: Mapped[int] = mapped_column(Integer, default=0)
    refinement_count: Mapped[int] = mapped_column(Integer, default=0)
    new_angle_count: Mapped[int] = mapped_column(Integer, default=0)


class ThemeMergeReinforcement(Base):
    """
    When user merges theme A into theme B, we store A's label (and optional embedding)
    so future extraction can resolve similar labels to B (user's chosen canonical theme).
    """
    __tablename__ = "theme_merge_reinforcement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_label: Mapped[str] = mapped_column(String(512), index=True)
    source_embedding: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)
    target_theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), index=True)


class NarrativeMentionsDaily(Base):
    __tablename__ = "narrative_mentions_daily"

    narrative_id: Mapped[int] = mapped_column(ForeignKey("narratives.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    burst_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    novelty_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    accel_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class ThemeSubThemeMetrics(Base):
    """Computed sub-theme-level attributes: novelty_type and narrative_stage (from statistics, not LLM)."""
    __tablename__ = "theme_sub_theme_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), index=True)
    sub_theme: Mapped[str] = mapped_column(String(128), index=True)
    novelty_type: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)  # new|evolving|reversal
    narrative_stage: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)  # early|mainstream|late|contested
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    __table_args__ = (UniqueConstraint("theme_id", "sub_theme", name="uq_theme_sub_theme_metrics_theme_sub_theme"),)


class ThemeSubThemeMentionsDaily(Base):
    """Daily mention counts per (theme_id, sub_theme) for stacked share-of-voice and time-series."""
    __tablename__ = "theme_sub_theme_mentions_daily"

    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), primary_key=True)
    sub_theme: Mapped[str] = mapped_column(String(128), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)


class ThemeNarrativeSummaryCache(Base):
    """Pre-computed LLM narrative summary for a theme (generated daily, not on page load)."""
    __tablename__ = "theme_narrative_summary_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(16), default="30d")  # 30d
    summary: Mapped[str] = mapped_column(Text)
    trending_sub_themes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    inflection_alert: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    __table_args__ = (UniqueConstraint("theme_id", "period", name="uq_theme_summary_cache_theme_period"),)

