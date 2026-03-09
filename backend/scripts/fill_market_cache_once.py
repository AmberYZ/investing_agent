#!/usr/bin/env python3
"""One-off script to fill theme_market_snapshot and instrument_market_snapshot (no other aggregation)."""
from __future__ import annotations

import sys
from pathlib import Path

# backend/scripts -> backend
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.aggregations import _theme_and_descendant_ids
from app.db import SessionLocal, init_db
from app.followed_themes import get_followed_theme_ids
from app.models import ThemeInstrument
from app.trading_digest import populate_daily_market_cache, populate_instrument_market_cache


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        followed_ids = get_followed_theme_ids()
        if not followed_ids:
            print("No followed themes. Add themes to your basket first.")
            return
        print(f"Followed themes: {len(followed_ids)}")
        n_themes = populate_daily_market_cache(db, followed_ids)
        print(f"Theme market cache: {n_themes} themes updated")
        theme_ids_flat = []
        for tid in followed_ids:
            theme_ids_flat.extend(_theme_and_descendant_ids(db, tid))
        theme_ids_flat = list(set(theme_ids_flat))
        symbols = [
            r[0]
            for r in db.query(ThemeInstrument.symbol)
            .filter(ThemeInstrument.theme_id.in_(theme_ids_flat))
            .distinct()
            .all()
            if r[0]
        ]
        if not symbols:
            print("No instruments in followed themes.")
            return
        print(f"Instruments: {len(symbols)} symbols")
        n_instruments = populate_instrument_market_cache(db, symbols)
        print(f"Instrument market cache: {n_instruments} symbols updated")
        print("Done. Market data caches filled.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
