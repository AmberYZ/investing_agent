# Plan: Deduplicate Semantically Equivalent Themes

**Implemented (items 2, 4, 5):** Alias resolution at ingestion, embedding-based similarity at ingestion, backfill-embeddings endpoint, POST /themes/merge, GET /themes/suggest-merges. See "Usage" at the end.

---

## Problem

After extraction, multiple themes can refer to the same thing (e.g. "US-China trade negotiations" vs "US-China trade relations"). Currently:

- **Canonicalization** (`worker.canonicalize_label`) only lowercases and normalizes whitespace, so these become separate themes.
- **ThemeAlias** exists in the schema but is not used during ingestion or theme lookup.
- Each variant gets its own `Theme` row and its own narratives, fragmenting the view.

## Proposed Approach (layered)

### 1. Tighten the extraction prompt (quick win, no code schema change)

**Goal:** Reduce *new* duplicates by steering the LLM toward consistent, canonical phrasing.

**Changes in `backend/app/prompts/extract_themes_default.txt` (and user override):**

- Add a short instruction: *"Use consistent, canonical theme labels. Prefer one standard phrasing per topic (e.g. 'US–China trade relations' rather than mixing 'negotiations', 'talks', 'relations'). If a theme could match an existing topic, use the same label you would use in a theme index."*
- Optionally add 1–2 examples of "same theme, one label" in the Theme quality section.

**Pros:** Low effort, fewer future duplicates.  
**Cons:** Does not fix existing data or cross-document variance the model still produces.

---

### 2. Use ThemeAlias at ingestion (resolve known synonyms)

**Goal:** When the LLM returns a label that is already registered as an **alias** of an existing theme, attach narratives to that existing theme instead of creating a new one.

**Implementation:**

- **Theme resolution in worker:** Before `upsert_theme(db, label)`:
  1. `canon = canonicalize_label(label)` (unchanged).
  2. Try to find theme by **canonical_label** (current behavior).
  3. If not found, try to find a theme that has this label as a **ThemeAlias** (normalize alias with `canonicalize_label` when storing and when looking up).
  4. If found via alias → use that theme and optionally **add** the current `label` as an alias if not already present (so next time we resolve even faster).
  5. If not found → create new theme with `canonical_label = canon` and optionally add `label` as first alias when it differs from canon (e.g. original casing).

- **Alias storage:** When creating a new theme, if the LLM returned a label that normalizes to `canon`, store the original `label` in `ThemeAlias` for that theme (so "US-China trade relations" and "us-china trade relations" both resolve). When we resolve via alias, add the incoming `label` as alias with `created_by="system"` and e.g. `confidence=1.0`.

**Pros:** No new tables; uses existing ThemeAlias; fixes duplicates as soon as aliases exist (manually or from merge).  
**Cons:** Only helps when aliases already exist or when we add them (e.g. via merge or suggestions).

---

### 3. Smarter canonicalization (optional, conservative)

**Goal:** Catch trivial variants without ML (e.g. "negotiations" vs "relations" for the same phrase).

**Options (pick one or combine):**

- **Rule-based synonym list:** Maintain a small mapping (e.g. "negotiations" → "relations") applied only to a **suffix** or **segment** of the label so we don’t over-normalize (e.g. "US-China trade negotiations" → "US-China trade relations" only if we have a rule for that segment).
- **Stemming / optional token normalization:** Normalize common suffixes (e.g. -tion, -s) for a **last token** only, so "US-China trade negotiations" and "US-China trade relations" still differ unless we add explicit rules. Prefer explicit synonym list over aggressive stemming to avoid merging distinct themes.

**Pros:** No API calls; fast.  
**Cons:** Requires maintaining rules; risk of over-merging if too aggressive.

---

### 4. Embedding-based similarity (optional, for suggestions or auto-merge)

**Goal:** Detect that "US-China trade negotiations" and "US-China trade relations" are semantically close and either suggest a merge or auto-resolve to one theme.

**Implementation:**

- **Option A – At ingestion:** When about to create a new theme, optionally:
  1. Embed the new label (reuse existing Vertex `embed_texts` or equivalent).
  2. Compare to embeddings of existing theme labels (and optionally aliases). If you don’t store theme embeddings today, run a one-off job to embed all `Theme.canonical_label` (+ aliases) and store in a small table or cache.
  3. If max similarity &gt; threshold (e.g. 0.92): either **auto-resolve** to the best-matching theme and add the new label as alias, or **suggest** in a log/admin for manual merge.

- **Option B – Batch job:** Periodically (e.g. nightly): embed all theme labels, compute pairwise similarity, list pairs above threshold for review; allow "merge" action that merges theme B into A and adds B’s label as alias of A.

**Pros:** Catches semantic near-duplicates without maintaining synonym lists.  
**Cons:** Depends on embedding API; needs threshold tuning; optional storage for theme embeddings.

---

### 5. LLM-based merge suggestions (optional)

**Goal:** Use the same LLM as extraction to propose which themes are the same.

**Implementation:**

- **Batch job or admin action:** Send the list of theme labels (e.g. top 200 by mention count) to the LLM with a prompt: *"Which of these theme labels refer to the same investment theme? Return groups of equivalent labels."* Parse response into groups; for each group, suggest one canonical label and the rest as aliases (or suggest merge into one theme).
- **Flow:** Show suggestions in admin UI; on confirm, merge themes (move narratives, add aliases, delete or deprecate duplicate theme).

**Pros:** Can capture nuance and context.  
**Cons:** Cost and latency; needs robust parsing and idempotent merge logic.

---

### 6. Admin: merge two themes (required for existing data)

**Goal:** Let a human merge two themes (e.g. "US-China trade negotiations" into "US-China trade relations"), so all narratives live under one theme and the other label becomes an alias.

**Implementation:**

- **API:** e.g. `POST /themes/merge` with `source_theme_id` and `target_theme_id`.
  - Reassign all narratives of `source_theme_id` to `target_theme_id`.
  - Insert `ThemeAlias(theme_id=target_theme_id, alias=source_theme.canonical_label, created_by="user")`.
  - Delete `source_theme` (or mark deprecated if you add a status field).
- **Frontend:** In theme list or theme detail, "Merge into another theme" → pick target theme → confirm. Optional: show "Suggested merges" from embedding or LLM job and one-click accept.

**Pros:** Fixes existing duplicates and gives a single control point for all strategies above.  
**Cons:** Requires UI and backend endpoint.

---

## Recommended order of implementation

| Order | Item | Effort | Impact |
|-------|------|--------|--------|
| 1 | Prompt tweaks (§1) | Low | Fewer new duplicates |
| 2 | Theme resolution via ThemeAlias at ingestion (§2) | Medium | Same theme when alias exists; foundation for merge |
| 3 | Admin merge API + minimal UI (§6) | Medium | Fix existing data; user can create aliases by merging |
| 4 | (Optional) Embedding-based suggestion or auto-merge (§4) | Higher | Catches semantic duplicates with little manual rules |
| 5 | (Optional) LLM merge-suggestion job (§5) | Higher | Good for large, one-off cleanups |
| 6 | (Optional) Rule-based canonicalization (§3) | Low–medium | Small extra gain if you have clear patterns |

## Summary

- **Must-have:** Prompt update, alias-aware theme resolution at ingestion, and a merge API + UI so that "US-China trade negotiations" and "US-China trade relations" can be one theme with one alias.
- **Nice-to-have:** Embedding or LLM-based suggestion to surface merge candidates; optional rule-based normalization for very common variants.

This plan reuses the existing `ThemeAlias` table and keeps a single source of truth (one theme id) while allowing multiple equivalent labels to resolve to it.

---

## Usage (implemented)

- **Ingestion (worker):** Each extracted theme label is resolved via `resolve_theme(db, label)`: first by canonical label, then by ThemeAlias, then (if Vertex is enabled) by embedding similarity (threshold 0.92). New themes get an embedding stored for future similarity. No config change needed.

- **Backfill embeddings (for existing themes):** Call `POST /themes/backfill-embeddings` once after enabling Vertex so existing themes have embeddings and new ingestions can match against them. Requires `enable_vertex` and `gcp_project`.

- **Merge two themes (e.g. after review):** `POST /themes/merge` with body `{"source_theme_id": <id>, "target_theme_id": <id>}`. Moves all narratives to the target, adds the source theme’s label as a user alias on the target, and deletes the source theme.

- **LLM merge suggestions:** `GET /themes/suggest-merges?limit=200` returns `{ "suggestions": [ { "theme_ids": [5, 7], "labels": ["...", "..."] }, ... ] }` for groups the LLM considers the same theme. Use these to decide merges and then call `POST /themes/merge`. Requires `LLM_API_KEY`.
