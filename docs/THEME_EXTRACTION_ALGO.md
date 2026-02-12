# Theme extraction algorithm

This doc describes how themes are extracted from new documents and how that interacts with `theme.embedding`, `theme_merge_reinforcement`, and related tables.

---

## When each table is updated

| Table / field | When it is written |
|---------------|--------------------|
| **theme_merge_reinforcement** | Only when the **user** merges two existing themes in the admin UI (Themes & merge → Merge). One row per merged-away theme: `source_label`, `source_embedding`, `target_theme_id`. Never written during document extraction. |
| **theme.embedding** | When a **new** theme is created (extraction produced a label that did not match any existing theme or reinforcement). We embed that label and set `Theme.embedding`. For existing themes we do not update embedding during extraction. |
| **theme_aliases** | Whenever we resolve an extracted label to an existing theme (by alias, reinforcement, similarity, or substring). We add `ThemeAlias(theme_id=existing_id, alias=extracted_label)`. |
| **narratives / evidence** | Always: we attach extracted narratives and evidence to the theme returned by `resolve_theme` (either an existing or a newly created theme). |

So:

- **Extracted label matches an existing theme (or reinforcement):**  
  No new theme, no new row in `theme_merge_reinforcement`, no change to `theme.embedding`. We add an alias (if needed), and attach narratives/evidence to that existing theme.

- **Extracted label is new:**  
  We create a new `Theme`, set `theme.embedding` from the embedded label, and attach narratives/evidence to it. Still no change to `theme_merge_reinforcement` (that table only records user merges).

---

## Exact algorithm: extracting themes from a new document

1. **Chunk and extract**  
   Chunk the document text, optionally embed chunks. Run LLM or heuristic extraction to get a list of **themes** (labels) and **narratives** (with optional evidence).

2. **For each extracted theme label** (dedupe by canonical label within the document), run **resolve_theme(db, label)**:

   - **1) Exact match by canonical label**  
     `Theme.canonical_label == canonicalize_label(label)`.  
     → Return that theme. No embedding call, no writes to reinforcement or theme.embedding.

   - **2) Match by alias**  
     Look up `ThemeAlias` for the canonical label.  
     → Return that theme, ensure alias exists. No embedding, no reinforcement/theme.embedding writes.

   - **2.5) Merge reinforcement**  
     If enabled and embedding is available: embed the label once, compare to all `theme_merge_reinforcement.source_embedding`. If best cosine similarity ≥ `theme_merge_reinforcement_threshold`, return that row’s `target_theme_id` (the existing theme).  
     → Return that theme, add alias. **We do not write** to `theme_merge_reinforcement` here (only read). We do not change `theme.embedding`.

   - **3) Similarity to existing themes**  
     Embed the label (again), compare to every `Theme.embedding`. If best cosine similarity ≥ `theme_similarity_embedding_threshold`, return that theme; else try token (Dice) similarity.  
     → Return that theme, add alias. No writes to reinforcement or theme.embedding.

   - **3.5) Substring match**  
     If the canonical label is a substring of an existing theme label (or vice versa), use the shorter (broader) theme.  
     → Return that theme, add alias. No embedding/reinforcement writes.

   - **4) Create new theme**  
     No match: create `Theme(canonical_label=canon)`, embed the label, set `Theme.embedding`, and return the new theme.  
     → **Only here** do we write `theme.embedding`. Still no write to `theme_merge_reinforcement`.

3. **Attach narratives and evidence**  
   For each narrative under that theme, `upsert_narrative(db, theme_id=resolved_theme.id, ...)` and create `Evidence` rows. All of this is attached to the theme returned by `resolve_theme` (existing or new).

---

## Summary

- **theme_merge_reinforcement:** Only reflects **user** merge decisions (admin UI). Read during extraction to steer labels to previously merged-into themes; never written during extraction.
- **theme.embedding:** Set when a **new** theme is created in `resolve_theme`; unchanged when we resolve to an existing theme.
- **Extract flow:** Extract labels → resolve each label (exact → alias → reinforcement → existing-theme similarity → substring → create new) → attach narratives/evidence to the resolved theme. New themes get an embedding; existing themes and reinforcement table are only read (and aliases/evidence updated as needed).
