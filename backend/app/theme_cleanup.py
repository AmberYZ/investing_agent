"""
Periodic cleanup: remove inactive themes with fewer than N narratives that are not followed.
Inactive = same as archived: not in get_active_theme_ids (no evidence in last inactive_days by document date).
"""
from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analytics import get_active_theme_ids
from app.followed_themes import get_followed_theme_ids, unfollow_theme
from app.models import (
    Narrative,
    Theme,
    ThemeMergeReinforcement,
    ThemeMentionsDaily,
    ThemeNarrativeSummaryCache,
    ThemeRelationDaily,
    ThemeSubThemeMetrics,
    ThemeSubThemeMentionsDaily,
)

logger = logging.getLogger("investing_agent.theme_cleanup")


def delete_theme_cascade(db: Session, theme: Theme) -> None:
    """
    Delete a theme and all related data (same as admin DELETE /admin/themes/{id}).
    Caller must ensure the theme exists and is loaded in this session.
    """
    theme_id = theme.id
    db.query(ThemeMergeReinforcement).filter(
        ThemeMergeReinforcement.target_theme_id == theme_id
    ).delete(synchronize_session="fetch")
    db.query(ThemeMentionsDaily).filter(ThemeMentionsDaily.theme_id == theme_id).delete(
        synchronize_session="fetch"
    )
    db.query(ThemeRelationDaily).filter(ThemeRelationDaily.theme_id == theme_id).delete(
        synchronize_session="fetch"
    )
    db.query(ThemeSubThemeMetrics).filter(ThemeSubThemeMetrics.theme_id == theme_id).delete(
        synchronize_session="fetch"
    )
    db.query(ThemeSubThemeMentionsDaily).filter(
        ThemeSubThemeMentionsDaily.theme_id == theme_id
    ).delete(synchronize_session="fetch")
    db.query(ThemeNarrativeSummaryCache).filter(
        ThemeNarrativeSummaryCache.theme_id == theme_id
    ).delete(synchronize_session="fetch")
    unfollow_theme(theme_id)
    db.delete(theme)


def remove_empty_unfollowed_themes(
    db: Session,
    *,
    inactive_days: int = 30,
    min_narratives: int = 3,
) -> int:
    """
    Delete themes that are inactive, have fewer than min_narratives narratives, and are not followed.
    Inactive = same as archived: not in get_active_theme_ids(db, inactive_days).
    Returns the number of themes removed.
    """
    all_theme_ids = {r[0] for r in db.query(Theme.id).all()}
    active_ids = get_active_theme_ids(db, inactive_days)
    inactive_theme_ids = all_theme_ids - active_ids

    # Narrative count per theme (theme_id -> count)
    narrative_counts = dict(
        db.query(Narrative.theme_id, func.count(Narrative.id))
        .group_by(Narrative.theme_id)
        .all()
    )
    followed_ids = set(get_followed_theme_ids())

    to_remove = [
        t
        for t in db.query(Theme).filter(Theme.id.in_(inactive_theme_ids)).all()
        if narrative_counts.get(t.id, 0) < min_narratives and t.id not in followed_ids
    ]

    removed = 0
    for theme in to_remove:
        try:
            logger.info(
                "Removing inactive unfollowed theme id=%s label=%s (narratives=%s)",
                theme.id,
                theme.canonical_label,
                narrative_counts.get(theme.id, 0),
            )
            delete_theme_cascade(db, theme)
            removed += 1
        except Exception as e:
            logger.exception("Failed to remove theme id=%s: %s", theme.id, e)
            db.rollback()
            continue
    if removed:
        db.commit()
    return removed
