from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    sha256: str
    filename: str
    gcs_raw_uri: str
    received_at: Optional[dt.datetime] = None
    modified_at: Optional[dt.datetime] = None  # document date (e.g. file mtime); used as timestamp for grouping
    source_type: str = "pdf"
    source_name: str = "wechat"
    source_uri: Optional[str] = None
    source_metadata: Optional[dict] = None
    content_type: str = "application/pdf"


class IngestTextRequest(BaseModel):
    """Request body for POST /ingest-text (e.g. Substack email body or RSS article)."""

    content: str
    content_type: Literal["text/html", "text/plain"] = "text/html"
    title: str
    source_uri: Optional[str] = None
    published_at: Optional[str] = None  # ISO8601
    source_name: str = "Substack"
    source_type: str = "substack"  # e.g. "substack" or "gmail"


class IngestResponse(BaseModel):
    document_id: int
    job_id: int
    status: str


class DocumentExcerptOut(BaseModel):
    quote: str
    page: Optional[int] = None


class DocumentExcerptsOut(BaseModel):
    excerpts: list[DocumentExcerptOut] = Field(default_factory=list)


class DocumentOut(BaseModel):
    id: int
    filename: str
    summary: Optional[str] = None
    num_pages: Optional[int] = None
    source_type: str
    source_name: str
    source_uri: Optional[str] = None
    received_at: dt.datetime
    modified_at: Optional[dt.datetime] = None
    published_at: Optional[dt.datetime] = None
    gcs_raw_uri: str
    gcs_text_uri: Optional[str] = None
    download_url: Optional[str] = None
    text_download_url: Optional[str] = None


class EvidenceOut(BaseModel):
    id: int
    quote: str
    page: Optional[int] = None
    document_id: int
    source_display: Optional[str] = None  # e.g. "wechat_baiguan" or "gmail · Invest_Digest"


class NarrativeOut(BaseModel):
    id: int
    theme_id: int
    statement: str
    stance: str = "unlabeled"  # labelling disabled; was bull|bear|neutral
    relation_to_prevailing: str = "unlabeled"  # labelling disabled; was consensus|contrarian|refinement|new_angle
    date_created: dt.datetime  # when this narrative first appeared
    first_seen: dt.datetime
    last_seen: dt.datetime
    status: str = "active"  # not stored on Narrative model; default for API response
    sub_theme: Optional[str] = None
    narrative_stance: Optional[str] = None  # bullish|bearish|mixed|neutral from LLM
    confidence_level: Optional[str] = None  # fact|opinion from LLM
    evidence: list[EvidenceOut] = Field(default_factory=list)
    # When include_children=true on narratives endpoint, label of the theme this narrative belongs to (may be a child).
    theme_label: Optional[str] = None


class ThemeOut(BaseModel):
    id: int
    canonical_label: str
    description: Optional[str] = None
    last_updated: Optional[dt.datetime] = None
    is_new: bool = False
    parent_theme_id: Optional[int] = None
    parent_theme_label: Optional[str] = None


class ThemeIdLabelOut(BaseModel):
    id: int
    canonical_label: str


class BasketItemOut(BaseModel):
    """Theme row for My Basket list (followed themes)."""
    id: int
    canonical_label: str
    description: Optional[str] = None
    instrument_count: int = 0


class ThemeNotesOut(BaseModel):
    content: Optional[str] = None


class ThemeNotesUpdate(BaseModel):
    content: Optional[str] = None


class BasketSummaryItemOut(BasketItemOut):
    """Basket row with optional price/valuation metrics (from primary ticker)."""
    primary_symbol: Optional[str] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    latest_rsi: Optional[float] = None
    pct_1m: Optional[float] = None
    pct_3m: Optional[float] = None
    pct_ytd: Optional[float] = None
    pct_6m: Optional[float] = None
    quarterly_earnings_growth_yoy: Optional[float] = None
    quarterly_revenue_growth_yoy: Optional[float] = None
    next_fy_eps_estimate: Optional[float] = None
    eps_revision_up_30d: Optional[int] = None
    eps_revision_down_30d: Optional[int] = None
    eps_growth_pct: Optional[float] = None


class ThemeBasketMetricsOut(BaseModel):
    """Metrics for one theme's primary ticker (for lazy-loaded basket)."""
    theme_id: int
    primary_symbol: Optional[str] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    latest_rsi: Optional[float] = None
    pct_1m: Optional[float] = None
    pct_3m: Optional[float] = None
    pct_ytd: Optional[float] = None
    pct_6m: Optional[float] = None
    quarterly_earnings_growth_yoy: Optional[float] = None
    quarterly_revenue_growth_yoy: Optional[float] = None
    next_fy_eps_estimate: Optional[float] = None
    eps_revision_up_30d: Optional[int] = None
    eps_revision_down_30d: Optional[int] = None
    eps_growth_pct: Optional[float] = None


class AdminThemeOut(BaseModel):
    """Theme with metadata for admin theme list and merge."""
    id: int
    canonical_label: str
    description: Optional[str] = None
    first_appeared: Optional[dt.datetime] = None
    document_count: int = 0  # distinct documents mentioning this theme (numerator for % voice share)
    last_updated: Optional[dt.datetime] = None


class ThemeWithNarrativesOut(ThemeOut):
    narratives: list[NarrativeOut] = Field(default_factory=list)
    # IDs of direct child themes (for hierarchy UI).
    child_theme_ids: list[int] = Field(default_factory=list)


class ThemeParentUpdate(BaseModel):
    """Set or clear this theme's parent (group into bigger theme)."""
    parent_theme_id: Optional[int] = None  # null = ungroup


class ThemeDailyMetricOut(BaseModel):
    theme_id: int
    date: dt.date
    doc_count: int
    mention_count: int
    share_of_voice: Optional[float] = None
    consensus_count: int = 0
    contrarian_count: int = 0
    refinement_count: int = 0
    new_angle_count: int = 0


class ThemeMetricsByStanceOut(BaseModel):
    """Daily share/count of narratives by narrative_stance (bullish/bearish/mixed/neutral)."""
    date: str
    bullish_count: int = 0
    bearish_count: int = 0
    mixed_count: int = 0
    neutral_count: int = 0
    total_count: int = 0


class ThemeMetricsByConfidenceOut(BaseModel):
    """Daily count of narratives by confidence_level (fact/opinion)."""
    date: str
    fact_count: int = 0
    opinion_count: int = 0
    total_count: int = 0


class ThemeSubThemeDailyOut(BaseModel):
    """Daily metrics per sub-theme for stacked share-of-voice chart."""
    date: str
    sub_theme: str
    doc_count: int = 0
    mention_count: int = 0


class NarrativeDailyMetricOut(BaseModel):
    narrative_id: int
    date: dt.date
    doc_count: int
    mention_count: int
    burst_score: Optional[float] = None
    accel_score: Optional[float] = None
    novelty_score: Optional[float] = None


class IngestJobOut(BaseModel):
    id: int
    document_id: int
    filename: Optional[str] = None
    source_name: Optional[str] = None
    source_type: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: dt.datetime
    started_at: Optional[dt.datetime] = None
    finished_at: Optional[dt.datetime] = None


class RequeueIngestJobsOut(BaseModel):
    requeued: int


class CancelIngestJobsOut(BaseModel):
    cancelled: int
    started_at: Optional[dt.datetime] = None
    finished_at: Optional[dt.datetime] = None


class ThemeDocumentNarrativeOut(BaseModel):
    statement: str
    stance: str
    relation_to_prevailing: str


class ThemeDocumentOut(BaseModel):
    id: int
    filename: str
    received_at: dt.datetime
    summary: Optional[str] = None
    narratives: list[ThemeDocumentNarrativeOut] = Field(default_factory=list)
    excerpts: list[str] = Field(default_factory=list)


class NarrativeSummaryOut(BaseModel):
    summary: str


class NarrativeSummaryExtendedOut(BaseModel):
    """Past-month summary with trending sub-themes and inflection alert (heuristics + optional LLM)."""
    summary: str
    trending_sub_themes: list[str] = Field(default_factory=list)
    inflection_alert: Optional[str] = None


class BatchNarrativeSummaryItemOut(BaseModel):
    """One theme's narrative summary for batch endpoint."""
    summary: str
    trending_sub_themes: list[str] = Field(default_factory=list)
    inflection_alert: Optional[str] = None


class NarrativeShiftOut(BaseModel):
    date: str
    description: str


class ThemeNetworkNodeOut(BaseModel):
    id: int
    canonical_label: str
    mention_count: int = 0


class ThemeNetworkEdgeOut(BaseModel):
    theme_id_a: int
    theme_id_b: int
    weight: int


class ThemeNetworkOut(BaseModel):
    nodes: list[ThemeNetworkNodeOut]
    edges: list[ThemeNetworkEdgeOut]


class ThemeNetworkSnapshotOut(BaseModel):
    period_label: str
    nodes: list[ThemeNetworkNodeOut]
    edges: list[ThemeNetworkEdgeOut]


class ThemeNetworkSnapshotsOut(BaseModel):
    snapshots: list[ThemeNetworkSnapshotOut]


class ExtractionPromptOut(BaseModel):
    """Current theme/narrative extraction prompt template (user-editable)."""
    prompt_template: str
    hint: str = "Use {{schema}} and {{text}} as placeholders. Saving writes to prompts/extract_themes.txt."


class ExtractionPromptUpdate(BaseModel):
    prompt_template: str


class ExtractionDryRunRequest(BaseModel):
    """Request for POST /admin/extraction-dry-run: run extraction with multiple models, no DB write."""

    text: Optional[str] = Field(None, description="Document text to extract from. Omit if using document_id.")
    document_id: Optional[int] = Field(None, description="Existing document ID; text is loaded from storage (read-only).")
    models: list[str] = Field(
        default_factory=list,
        description="Model names to run (e.g. ['gpt-4o-mini', 'gpt-4o']). Uses current LLM_PROVIDER. Empty = use configured LLM_MODEL only.",
    )


class ThemeMergeRequest(BaseModel):
    source_theme_id: int
    target_theme_id: int


class ThemeMergeOut(BaseModel):
    merged: bool = True
    source_theme_id: int
    target_theme_id: int
    narratives_moved: int


class SuggestMergeGroupOut(BaseModel):
    """One suggested merge: these theme_ids / labels refer to the same theme."""
    theme_ids: list[int]
    labels: list[str]
    canonical_theme_id: int  # merge all others in theme_ids into this one


class SuggestMergesOut(BaseModel):
    suggestions: list[SuggestMergeGroupOut]


class CreateThemeRequest(BaseModel):
    canonical_label: str
    description: Optional[str] = None


class PatchThemeRequest(BaseModel):
    canonical_label: Optional[str] = None
    description: Optional[str] = None


class ReassignNarrativesRequest(BaseModel):
    narrative_ids: list[int]
    target_theme_id: int


class ReassignNarrativesOut(BaseModel):
    moved: int
    skipped: int  # duplicates (same statement already exists in target)
    target_theme_id: int
    target_label: str


# ---- Theme narrative evolution insights (beyond sentiment) ----

LiteralTrajectory = Literal["improving", "worsening", "mixed", "unchanged", "unknown"]


class TrajectoryPointOut(BaseModel):
    """One point in theme trajectory over time (e.g. per week)."""
    date: str
    direction: LiteralTrajectory
    note: Optional[str] = None
    mention_trend: Optional[float] = None  # e.g. 7d change in mention count
    share_trend: Optional[float] = None  # e.g. 7d change in share of voice


class ConsensusPeriodOut(BaseModel):
    """Prevailing narrative in a time period."""
    period_start: str
    period_end: str
    narrative_id: int
    statement: str
    share: float  # fraction of theme mentions in this period
    mention_count: int


class EmergingNarrativeOut(BaseModel):
    """Narrative that is new or gaining as an angle."""
    narrative_id: int
    statement: str
    first_seen: str
    mention_count: int
    novelty_score: Optional[float] = None
    relation_to_prevailing: str = "unlabeled"


class ThemeDebateOut(BaseModel):
    """How debated this theme is (multiple competing views, no clear consensus)."""
    score: float  # 0–1; higher = more debated
    label: str  # e.g. "Highly debated", "Moderate debate", "Clear consensus"
    narrative_count: int
    top_narrative_share: Optional[float] = None  # share of top narrative; low = more debate


class ThemeInsightsOut(BaseModel):
    """Composite insights for a theme: trajectory, consensus evolution, emerging angles, debate."""
    trajectory: list[TrajectoryPointOut] = Field(default_factory=list)
    consensus_evolution: list[ConsensusPeriodOut] = Field(default_factory=list)
    emerging: list[EmergingNarrativeOut] = Field(default_factory=list)
    debate: Optional[ThemeDebateOut] = None


class SentimentRankingsOut(BaseModel):
    """Most positive and most negative themes by stance over a window."""
    most_positive: list[ThemeOut] = Field(default_factory=list)
    most_negative: list[ThemeOut] = Field(default_factory=list)


class InflectionsOut(BaseModel):
    """Four inflection lists: less bullish, less bearish, attention peaking, most crowded."""
    bullish_turning_neutral_bearish: list[ThemeOut] = Field(default_factory=list)
    bearish_turning_neutral_bullish: list[ThemeOut] = Field(default_factory=list)
    attention_peaking: list[ThemeOut] = Field(default_factory=list)
    most_crowded: list[ThemeOut] = Field(default_factory=list)


class ThemeInstrumentOut(BaseModel):
    id: int
    theme_id: int
    symbol: str
    display_name: Optional[str] = None
    type: str = "stock"
    source: str = "manual"


class ThemeInstrumentCreate(BaseModel):
    symbol: str
    display_name: Optional[str] = None
    type: str = "stock"
    source: str = "manual"


class SuggestedInstrumentItem(BaseModel):
    symbol: str
    display_name: Optional[str] = None
    type: str = "stock"


class SuggestInstrumentsOut(BaseModel):
    """LLM-suggested tickers for a theme (not yet persisted)."""
    suggestions: list[SuggestedInstrumentItem] = Field(default_factory=list)


class InstrumentSearchItem(BaseModel):
    """One result from Alpha Vantage SYMBOL_SEARCH (typeahead when adding tickers)."""
    symbol: str
    name: Optional[str] = None
    type: str = "stock"
    region: Optional[str] = None
    currency: Optional[str] = None
    match_score: float = 0.0


class InstrumentSearchOut(BaseModel):
    """Ticker search results for add-instrument typeahead."""
    matches: list[InstrumentSearchItem] = Field(default_factory=list)
    message: Optional[str] = None


class InstrumentSummaryOut(BaseModel):
    """Instrument with price and valuation metrics for basket ticker rows."""
    id: int
    symbol: str
    display_name: Optional[str] = None
    type: str = "stock"
    source: str = "manual"
    # When include_children=true, the theme this instrument belongs to (may be a child).
    theme_id: Optional[int] = None
    theme_label: Optional[str] = None
    last_close: Optional[float] = None
    pct_1m: Optional[float] = None
    pct_3m: Optional[float] = None
    pct_ytd: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    latest_rsi: Optional[float] = None
    quarterly_earnings_growth_yoy: Optional[float] = None
    quarterly_revenue_growth_yoy: Optional[float] = None
    next_fy_eps_estimate: Optional[float] = None
    eps_revision_up_30d: Optional[int] = None
    eps_revision_down_30d: Optional[int] = None
    eps_growth_pct: Optional[float] = None
    message: Optional[str] = None


class BasketTickerRowOut(BaseModel):
    """One ticker in the basket with theme tag (for flat ticker-only basket view)."""
    theme_id: int
    canonical_label: str
    id: int
    symbol: str
    display_name: Optional[str] = None
    type: str = "stock"
    source: str = "manual"
    last_close: Optional[float] = None
    pct_1m: Optional[float] = None
    pct_3m: Optional[float] = None
    pct_ytd: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    latest_rsi: Optional[float] = None
    quarterly_earnings_growth_yoy: Optional[float] = None
    quarterly_revenue_growth_yoy: Optional[float] = None
    next_fy_eps_estimate: Optional[float] = None
    eps_revision_up_30d: Optional[int] = None
    eps_revision_down_30d: Optional[int] = None
    eps_growth_pct: Optional[float] = None
    message: Optional[str] = None

