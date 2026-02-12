"""
Theme merge: discover merge candidates (embedding similarity—label + content—optional LLM)
and execute merge (move narratives, aliases, daily tables; delete source theme).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.llm.embeddings import is_embedding_available
from app.llm.suggest_merges import suggest_theme_merge_groups
from app.models import (
    Evidence,
    Narrative,
    Theme,
    ThemeAlias,
    ThemeMentionsDaily,
    ThemeMergeReinforcement,
    ThemeRelationDaily,
)
from app.settings import settings
from app.worker import (
    canonicalize_label,
    _cosine_similarity,
    _token_set,
)

logger = logging.getLogger("investing_agent.theme_merge")

_MAX_CONTENT_SIGNATURE_CHARS = 8000

# Region/entity token groups: themes from different groups must not be merged by rules.
# E.g. "china consumer" and "us consumer" are distinct theses.
_ENTITY_GROUPS: list[frozenset[str]] = [
    frozenset({"china", "chinese"}),
    frozenset({"us", "america", "american"}),
    frozenset({"europe", "european"}),
    frozenset({"japan", "japanese"}),
    frozenset({"uk", "british"}),
    frozenset({"india", "indian"}),
    frozenset({"asia", "asian"}),  # can conflict with china/japan/india when used as primary region
]


def _labels_conflict_entities(canon_a: str, canon_b: str) -> bool:
    """True if the two labels imply different regions/entities (e.g. China vs US) and must not be merged."""
    ta = _token_set(canon_a)
    tb = _token_set(canon_b)
    groups_a = {g for g in _ENTITY_GROUPS if ta & g}
    groups_b = {g for g in _ENTITY_GROUPS if tb & g}
    if not groups_a or not groups_b:
        return False
    return groups_a != groups_b


@dataclass
class MergeOptions:
    """Options for compute_merge_candidates."""

    embedding_threshold: float | None = None  # default from settings
    use_embedding: bool = True
    use_content_embedding: bool = True  # use narratives + quotes for embedding (when Vertex enabled)
    content_embedding_threshold: float | None = None  # default from settings
    content_weight: float | None = None  # weight when combining label_sim and content_sim (0=label only, 1=content only)
    require_both_embeddings: bool | None = None  # when True, only merge if BOTH label and content sim pass; None = use settings
    use_llm: bool = False
    max_themes_for_llm: int = 200
    max_narratives_per_theme: int = 5
    max_quotes_per_theme: int = 8
    max_quote_chars: int = 250


@dataclass
class MergeSet:
    """One set of theme IDs to merge, with chosen canonical (target) theme."""

    theme_ids: list[int]
    canonical_theme_id: int
    labels: list[str] = field(default_factory=list)


def _union_find_merge(pairs: list[tuple[int, int]]) -> list[set[int]]:
    """Turn list of (a, b) pairs into list of disjoint sets (union-find)."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for a, b in pairs:
        union(a, b)

    # Group by root
    groups: dict[int, set[int]] = {}
    for x in parent:
        root = find(x)
        if root not in groups:
            groups[root] = set()
        groups[root].add(x)
    return list(groups.values())


def _pick_canonical(
    db: Session,
    theme_ids: list[int],
    themes_by_id: dict[int, Theme],
) -> int:
    """Choose which theme ID to keep (canonical). Prefer shorter/broader label, then more activity, then lower id."""
    if len(theme_ids) == 1:
        return theme_ids[0]
    themes = [themes_by_id[tid] for tid in theme_ids if tid in themes_by_id]
    if not themes:
        return theme_ids[0]
    labels = [t.canonical_label for t in themes]
    canon_labels = [canonicalize_label(lb) for lb in labels]
    token_sets = [_token_set(lb) for lb in canon_labels]

    # 1) Substring: if one label is proper substring of another, prefer shorter
    for i, t in enumerate(themes):
        c = canon_labels[i]
        for j, o in enumerate(themes):
            if i == j:
                continue
            oc = canon_labels[j]
            if c in oc and len(c) < len(oc):
                return t.id
            if oc in c and len(oc) < len(c):
                return o.id

    # 2) Token set: prefer theme with fewer tokens (broader label)
    best_idx = min(
        range(len(themes)),
        key=lambda i: (len(token_sets[i]), themes[i].id),
    )
    if len(token_sets[best_idx]) < max(len(ts) for ts in token_sets):
        return themes[best_idx].id

    # 3) Activity: more narratives, then more evidence
    def activity(theme_id: int) -> tuple[int, int]:
        n_count = db.query(Narrative).filter(Narrative.theme_id == theme_id).count()
        e_count = (
            db.query(Evidence.id)
            .join(Narrative, Narrative.id == Evidence.narrative_id)
            .filter(Narrative.theme_id == theme_id)
            .count()
        )
        return (n_count, e_count)

    best = max(themes, key=lambda t: activity(t.id))
    # 4) Tie: lower id (older)
    same_activity = [t for t in themes if activity(t.id) == activity(best.id)]
    return min(t.id for t in same_activity)


def _candidates_embedding(
    db: Session,
    themes: list[Theme],
    threshold: float,
) -> list[tuple[int, int]]:
    """Pairs with embedding cosine similarity >= threshold (only themes that have embedding)."""
    with_emb = [t for t in themes if t.embedding]
    pairs: list[tuple[int, int]] = []
    for i in range(len(with_emb)):
        for j in range(i + 1, len(with_emb)):
            sim = _cosine_similarity(with_emb[i].embedding or [], with_emb[j].embedding or [])
            if sim >= threshold:
                pairs.append((with_emb[i].id, with_emb[j].id))
    return pairs


def _theme_content_signature(
    db: Session,
    theme: Theme,
    max_narratives: int = 5,
    max_quotes: int = 8,
    max_quote_chars: int = 250,
) -> str:
    """
    Build a text signature for a theme: label + representative narratives + quotes.
    Used for content-aware embedding so themes that discuss the same topic merge even if labels differ.
    """
    parts = [f"Theme: {theme.canonical_label}", "Narratives:"]
    narratives = (
        db.query(Narrative.statement)
        .filter(Narrative.theme_id == theme.id)
        .limit(max_narratives)
        .all()
    )
    for row in narratives:
        stmt = row[0] if row else None
        if stmt and str(stmt).strip():
            parts.append(str(stmt).strip()[:500])
    parts.append("Quotes:")
    quotes = (
        db.query(Evidence.quote)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .filter(Narrative.theme_id == theme.id)
        .limit(max_quotes)
        .all()
    )
    for row in quotes:
        quote = row[0] if row else None
        if quote and str(quote).strip():
            parts.append(str(quote).strip()[:max_quote_chars])
    text = "\n".join(parts)
    if len(text) > _MAX_CONTENT_SIGNATURE_CHARS:
        text = text[:_MAX_CONTENT_SIGNATURE_CHARS]
    return text


def _candidates_content_embedding(
    db: Session,
    themes: list[Theme],
    threshold: float,
    max_narratives: int,
    max_quotes: int,
    max_quote_chars: int,
    batch_size: int = 20,
) -> list[tuple[int, int]]:
    """
    Build content signatures (label + narratives + quotes) for each theme, embed them
    (Vertex or OpenAI), return pairs with cosine similarity >= threshold.
    """
    from app.llm.embeddings import embed_texts
    if not is_embedding_available():
        return []
    signatures: list[str] = []
    for t in themes:
        sig = _theme_content_signature(
            db, t,
            max_narratives=max_narratives,
            max_quotes=max_quotes,
            max_quote_chars=max_quote_chars,
        )
        signatures.append(sig)
    if not signatures:
        return []
    num_batches = (len(signatures) + batch_size - 1) // batch_size
    logger.info("Requesting content embeddings from LLM for %d theme(s) (%d batch(es))", len(themes), num_batches)
    all_embeddings: list[list[float]] = []
    for i in range(0, len(signatures), batch_size):
        batch = signatures[i : i + batch_size]
        batch_num = i // batch_size + 1
        try:
            logger.debug("Content embedding batch %d/%d: requesting %d text(s)", batch_num, num_batches, len(batch))
            embs = embed_texts(texts=batch)
            all_embeddings.extend(embs)
        except Exception as e:
            logger.warning("Content embedding batch failed: %s", e)
            all_embeddings.extend([[]] * len(batch))
    if len(all_embeddings) != len(themes):
        return []
    pairs: list[tuple[int, int]] = []
    for i in range(len(themes)):
        if not all_embeddings[i]:
            continue
        for j in range(i + 1, len(themes)):
            if not all_embeddings[j]:
                continue
            sim = _cosine_similarity(all_embeddings[i], all_embeddings[j])
            if sim >= threshold:
                pairs.append((themes[i].id, themes[j].id))
    return pairs


def compute_merge_candidates(
    db: Session,
    options: Optional[MergeOptions] = None,
) -> list[MergeSet]:
    """
    Discover theme pairs/groups that should be merged using string rules, embedding similarity,
    and optionally LLM. Returns a list of merge sets, each with a chosen canonical theme_id.
    """
    opts = options or MergeOptions()
    embedding_thr = opts.embedding_threshold
    if embedding_thr is None:
        embedding_thr = settings.theme_merge_suggestion_embedding_threshold

    themes = db.query(Theme).order_by(Theme.id).all()
    if not themes:
        return []
    themes_by_id = {t.id: t for t in themes}
    label_pairs: list[tuple[int, int]] = []
    content_pairs: list[tuple[int, int]] = []

    # A) Label embedding similarity (Theme.embedding) — uses only saved embeddings, no API call
    if opts.use_embedding:
        with_emb = sum(1 for t in themes if t.embedding and len(t.embedding or []) > 0)
        without_emb = len(themes) - with_emb
        if with_emb:
            if without_emb:
                logger.info("Label embeddings: using saved for %d theme(s), %d theme(s) have no saved embedding (skipped)", with_emb, without_emb)
            else:
                logger.info("Label embeddings: using saved for all %d theme(s) (no API call)", with_emb)
            label_pairs = _candidates_embedding(db, themes, embedding_thr)
        elif without_emb:
            logger.info("Label embeddings: no themes have saved embeddings (skipping label similarity; enable embedding at ingest to populate)")

    # B) Content-aware embedding (label + narratives + quotes)
    if (
        opts.use_content_embedding
        and settings.theme_merge_use_content_embedding
        and is_embedding_available()
    ):
        content_thr = opts.content_embedding_threshold
        if content_thr is None:
            content_thr = settings.theme_merge_content_embedding_threshold
        try:
            content_pairs = _candidates_content_embedding(
                db,
                themes,
                content_thr,
                opts.max_narratives_per_theme,
                opts.max_quotes_per_theme,
                opts.max_quote_chars,
            )
            if content_pairs:
                logger.info("Content embedding added %d candidate pair(s)", len(content_pairs))
        except Exception as e:
            logger.warning("Content embedding step failed: %s", e)
            content_pairs = []

    # Stricter: only merge when BOTH label and content similarity pass (avoids e.g. "Pop Mart IP" with "China IP retailers").
    require_both = (
        opts.require_both_embeddings
        if opts.require_both_embeddings is not None
        else getattr(settings, "theme_merge_require_both_embeddings", True)
    )
    def _norm(p: tuple[int, int]) -> tuple[int, int]:
        return (min(p[0], p[1]), max(p[0], p[1]))
    if require_both and label_pairs and content_pairs:
        both_keys = {_norm(p) for p in label_pairs} & {_norm(p) for p in content_pairs}
        all_pairs = list(both_keys)
    else:
        all_pairs = list(label_pairs) + list(content_pairs)

    # C) Optional LLM (suggest_theme_merge_groups) — adds more pairs to the pool
    if opts.use_llm and settings.theme_merge_use_llm_suggest and settings.llm_api_key:
        try:
            labels = [t.canonical_label for t in themes[: opts.max_themes_for_llm]]
            groups = suggest_theme_merge_groups(labels)
            label_to_theme = {canonicalize_label(t.canonical_label): t for t in themes}
            for group in groups:
                if len(group) < 2:
                    continue
                ids_in_group: list[int] = []
                for lb in group:
                    canon = canonicalize_label(lb)
                    if canon in label_to_theme:
                        tid = label_to_theme[canon].id
                        if tid not in ids_in_group:
                            ids_in_group.append(tid)
                for i in range(len(ids_in_group)):
                    for j in range(i + 1, len(ids_in_group)):
                        all_pairs.append((ids_in_group[i], ids_in_group[j]))
        except Exception as e:
            logger.warning("LLM suggest-merges failed, continuing without: %s", e)

    # Dedupe pairs and drop any with conflicting entities (e.g. China vs US)
    seen_pair: set[tuple[int, int]] = set()
    unique_pairs: list[tuple[int, int]] = []
    for a, b in all_pairs:
        if a == b:
            continue
        if a not in themes_by_id or b not in themes_by_id:
            continue
        if _labels_conflict_entities(
            canonicalize_label(themes_by_id[a].canonical_label),
            canonicalize_label(themes_by_id[b].canonical_label),
        ):
            continue
        key = (min(a, b), max(a, b))
        if key not in seen_pair:
            seen_pair.add(key)
            unique_pairs.append((a, b))

    sets = _union_find_merge(unique_pairs)
    # Only return sets with at least 2 themes
    merge_sets: list[MergeSet] = []
    for s in sets:
        if len(s) < 2:
            continue
        theme_ids = sorted(s)
        canonical_id = _pick_canonical(db, theme_ids, themes_by_id)
        labels = [themes_by_id[tid].canonical_label for tid in theme_ids if tid in themes_by_id]
        merge_sets.append(
            MergeSet(theme_ids=theme_ids, canonical_theme_id=canonical_id, labels=labels)
        )
    return merge_sets


def execute_theme_merge(
    db: Session,
    source_theme_id: int,
    target_theme_id: int,
) -> int:
    """
    Merge source theme into target: move narratives, aliases, daily tables; delete source theme.
    Returns number of narratives moved.
    """
    if source_theme_id == target_theme_id:
        return 0
    source = db.query(Theme).filter(Theme.id == source_theme_id).one_or_none()
    target = db.query(Theme).filter(Theme.id == target_theme_id).one_or_none()
    if not source or not target:
        raise ValueError("Source or target theme not found")
    narratives_moved = db.query(Narrative).filter(Narrative.theme_id == source_theme_id).count()

    # 1) Narratives
    db.query(Narrative).filter(Narrative.theme_id == source_theme_id).update(
        {Narrative.theme_id: target_theme_id},
        synchronize_session="fetch",
    )

    # 2) Aliases: copy source aliases to target (skip duplicates), then delete source aliases
    source_aliases = (
        db.query(ThemeAlias).filter(ThemeAlias.theme_id == source_theme_id).all()
    )
    existing_target_aliases = {
        row.alias
        for row in db.query(ThemeAlias.alias).filter(ThemeAlias.theme_id == target_theme_id).all()
    }
    for al in source_aliases:
        if al.alias not in existing_target_aliases:
            db.add(
                ThemeAlias(
                    theme_id=target_theme_id,
                    alias=al.alias,
                    created_by=al.created_by,
                    confidence=al.confidence,
                )
            )
            existing_target_aliases.add(al.alias)
    db.query(ThemeAlias).filter(ThemeAlias.theme_id == source_theme_id).delete(
        synchronize_session="fetch"
    )

    # 3) ThemeMentionsDaily: merge counts into target by date, then delete source rows
    source_daily = (
        db.query(ThemeMentionsDaily)
        .filter(ThemeMentionsDaily.theme_id == source_theme_id)
        .all()
    )
    for row in source_daily:
        target_row = (
            db.query(ThemeMentionsDaily)
            .filter(
                ThemeMentionsDaily.theme_id == target_theme_id,
                ThemeMentionsDaily.date == row.date,
            )
            .one_or_none()
        )
        if target_row:
            target_row.doc_count = (target_row.doc_count or 0) + (row.doc_count or 0)
            target_row.mention_count = (target_row.mention_count or 0) + (row.mention_count or 0)
        else:
            db.add(
                ThemeMentionsDaily(
                    theme_id=target_theme_id,
                    date=row.date,
                    doc_count=row.doc_count or 0,
                    mention_count=row.mention_count or 0,
                    share_of_voice=row.share_of_voice,
                )
            )
    db.query(ThemeMentionsDaily).filter(ThemeMentionsDaily.theme_id == source_theme_id).delete(
        synchronize_session="fetch"
    )

    # 4) ThemeRelationDaily: same
    source_rel = (
        db.query(ThemeRelationDaily)
        .filter(ThemeRelationDaily.theme_id == source_theme_id)
        .all()
    )
    for row in source_rel:
        target_row = (
            db.query(ThemeRelationDaily)
            .filter(
                ThemeRelationDaily.theme_id == target_theme_id,
                ThemeRelationDaily.date == row.date,
            )
            .one_or_none()
        )
        if target_row:
            target_row.consensus_count += row.consensus_count or 0
            target_row.contrarian_count += row.contrarian_count or 0
            target_row.refinement_count += row.refinement_count or 0
            target_row.new_angle_count += row.new_angle_count or 0
        else:
            db.add(
                ThemeRelationDaily(
                    theme_id=target_theme_id,
                    date=row.date,
                    consensus_count=row.consensus_count or 0,
                    contrarian_count=row.contrarian_count or 0,
                    refinement_count=row.refinement_count or 0,
                    new_angle_count=row.new_angle_count or 0,
                )
            )
    db.query(ThemeRelationDaily).filter(ThemeRelationDaily.theme_id == source_theme_id).delete(
        synchronize_session="fetch"
    )

    # 4.5) Reinforcement: remember that source_label was explicitly merged into target.
    # This lets future extraction resolve similar labels to the user-chosen canonical theme.
    if getattr(settings, "theme_merge_reinforcement_enabled", False):
        try:
            db.add(
                ThemeMergeReinforcement(
                    source_label=canonicalize_label(source.canonical_label),
                    source_embedding=source.embedding,
                    target_theme_id=target_theme_id,
                )
            )
        except Exception as e:  # noqa: BLE001
            # Non-fatal: if reinforcement fails, the core merge should still succeed.
            logger.warning(
                "Failed to record theme merge reinforcement for %s -> %s: %s",
                source_theme_id,
                target_theme_id,
                e,
            )

    # 5) Delete source theme (narratives and aliases already moved)
    db.query(Theme).filter(Theme.id == source_theme_id).delete(synchronize_session="fetch")

    db.flush()
    logger.info(
        "Merged theme %s into %s, narratives_moved=%s",
        source_theme_id,
        target_theme_id,
        narratives_moved,
    )
    return narratives_moved
