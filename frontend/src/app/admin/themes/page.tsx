"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type AdminTheme = {
  id: number;
  canonical_label: string;
  description?: string | null;
  first_appeared?: string | null;
  document_count: number;
  last_updated?: string | null;
};

type SuggestGroup = {
  theme_ids: number[];
  labels: string[];
  canonical_theme_id: number;
};

const defaultParams = {
  embedding_threshold: 0.74,
  content_embedding_threshold: 0.8,
  use_llm: false,
  use_content_embedding: false,
  require_both_embeddings: false,
};

export default function AdminThemesPage() {
  const [themes, setThemes] = useState<AdminTheme[]>([]);
  const [loading, setLoading] = useState(true);
  const [suggestions, setSuggestions] = useState<SuggestGroup[]>([]);
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [dryRunDone, setDryRunDone] = useState(false);
  const [mergeLoading, setMergeLoading] = useState<number | null>(null);
  const [params, setParams] = useState(defaultParams);
  const [error, setError] = useState<string | null>(null);
  const [renameThemeId, setRenameThemeId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const loadThemes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let res = await fetch(`${API_BASE}/admin/themes?sort=label`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setThemes(Array.isArray(data) ? data : []);
      } else if (res.status === 404) {
        const fallback = await fetch(`${API_BASE}/themes?sort=label`, { cache: "no-store" });
        if (!fallback.ok) throw new Error(`Failed to load themes: ${fallback.status}`);
        const data = await fallback.json();
        setThemes(
          Array.isArray(data)
            ? data.map((t: { id: number; canonical_label: string; description?: string | null; last_updated?: string | null }) => ({
                ...t,
                first_appeared: null,
                document_count: 0,
              }))
            : []
        );
      } else {
        throw new Error(`Failed to load themes: ${res.status}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load themes");
      setThemes([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadThemes();
  }, [loadThemes]);

  async function runDryRun() {
    setDryRunLoading(true);
    setDryRunDone(false);
    setError(null);
    setSuggestions([]);
    try {
      const q = new URLSearchParams();
      if (params.embedding_threshold != null) q.set("embedding_threshold", String(params.embedding_threshold));
      if (params.content_embedding_threshold != null) q.set("content_embedding_threshold", String(params.content_embedding_threshold));
      q.set("use_llm", String(params.use_llm));
      q.set("use_content_embedding", String(params.use_content_embedding));
      if (params.require_both_embeddings != null) q.set("require_both_embeddings", String(params.require_both_embeddings));
      const res = await fetch(`${API_BASE}/admin/themes/suggest-merges?${q.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`Dry run failed: ${res.status}`);
      const data = await res.json();
      setSuggestions(data?.suggestions ?? []);
      setDryRunDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Dry run failed");
    } finally {
      setDryRunLoading(false);
    }
  }

  async function saveRename() {
    if (renameThemeId == null || !renameValue.trim()) return;
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/admin/themes/${renameThemeId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canonical_label: renameValue.trim() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err?.detail === "string" ? err.detail : `Rename failed: ${res.status}`);
      }
      setRenameThemeId(null);
      setRenameValue("");
      await loadThemes();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rename failed");
    }
  }

  function startRename(t: AdminTheme) {
    setRenameThemeId(t.id);
    setRenameValue(t.canonical_label);
    setError(null);
  }

  function cancelRename() {
    setRenameThemeId(null);
    setRenameValue("");
  }

  async function runMerge(group: SuggestGroup) {
    const canonicalId = group.canonical_theme_id;
    const toMerge = group.theme_ids.filter((id) => id !== canonicalId);
    if (toMerge.length === 0) return;
    setMergeLoading(canonicalId);
    setError(null);
    try {
      for (const sourceId of toMerge) {
        const res = await fetch(`${API_BASE}/admin/themes/merge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_theme_id: sourceId, target_theme_id: canonicalId }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err?.detail ?? `Merge failed: ${res.status}`);
        }
      }
      setSuggestions((prev) => prev.filter((s) => s.canonical_theme_id !== canonicalId || s.theme_ids.length !== group.theme_ids.length));
      await loadThemes();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Merge failed");
    } finally {
      setMergeLoading(null);
    }
  }

  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">Themes & merge</h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
        View all themes and their metadata. Use merge parameters and &quot;Dry run&quot; to preview suggested merges, then &quot;Merge&quot; to combine themes into one.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
          {error}
        </div>
      )}

      {/* Theme list */}
      <div className="mt-6">
        <h2 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">All themes ({themes.length})</h2>
        {loading ? (
          <p className="mt-2 text-sm text-zinc-500">Loading…</p>
        ) : (
          <div className="mt-2 overflow-x-auto rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-3 py-2">ID</th>
                  <th className="px-3 py-2">Label</th>
                  <th className="px-3 py-2">First appeared</th>
                  <th className="px-3 py-2">#documents</th>
                  <th className="px-3 py-2">Last updated</th>
                  <th className="px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {themes.map((t) => (
                  <tr key={t.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                    <td className="px-3 py-2 font-mono text-zinc-600 dark:text-zinc-400">{t.id}</td>
                    <td className="px-3 py-2 font-medium">
                      {renameThemeId === t.id ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <input
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            className="min-w-[120px] rounded border border-zinc-200 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                            autoFocus
                          />
                          <button
                            type="button"
                            onClick={saveRename}
                            disabled={!renameValue.trim()}
                            className="rounded bg-emerald-600 px-2 py-1 text-xs text-white hover:bg-emerald-700 disabled:opacity-50"
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            onClick={cancelRename}
                            className="rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        t.canonical_label
                      )}
                    </td>
                    <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
                      {t.first_appeared ? new Date(t.first_appeared).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-3 py-2">{t.document_count}</td>
                    <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
                      {t.last_updated ? new Date(t.last_updated).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-3 py-2">
                      {renameThemeId === t.id ? null : (
                        <>
                          <Link href={`/themes/${t.id}`} className="text-blue-600 hover:underline dark:text-blue-400">
                            View
                          </Link>
                          {" · "}
                          <button
                            type="button"
                            onClick={() => startRename(t)}
                            className="text-blue-600 hover:underline dark:text-blue-400"
                          >
                            Rename
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Merge parameters */}
      <div className="mt-10 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">Merge parameters</h2>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          Adjust thresholds and options for the merge suggestion (dry run). Higher threshold = fewer, more conservative suggestions.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">Label embedding threshold (0–1)</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={params.embedding_threshold}
              onChange={(e) => setParams((p) => ({ ...p, embedding_threshold: parseFloat(e.target.value) || 0.92 }))}
              className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">Content embedding threshold (0–1)</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={params.content_embedding_threshold}
              onChange={(e) => setParams((p) => ({ ...p, content_embedding_threshold: parseFloat(e.target.value) || 0.9 }))}
              className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
          </label>
          <label className="flex items-center gap-2 pt-6">
            <input
              type="checkbox"
              checked={params.require_both_embeddings}
              onChange={(e) => setParams((p) => ({ ...p, require_both_embeddings: e.target.checked }))}
              className="rounded border-zinc-300"
            />
            <span className="text-sm text-zinc-700 dark:text-zinc-300">Require both label and content similarity</span>
          </label>
          <label className="flex items-center gap-2 pt-6">
            <input
              type="checkbox"
              checked={params.use_content_embedding}
              onChange={(e) => setParams((p) => ({ ...p, use_content_embedding: e.target.checked }))}
              className="rounded border-zinc-300"
            />
            <span className="text-sm text-zinc-700 dark:text-zinc-300">Use content embedding</span>
          </label>
          <label className="flex items-center gap-2 pt-6">
            <input
              type="checkbox"
              checked={params.use_llm}
              onChange={(e) => setParams((p) => ({ ...p, use_llm: e.target.checked }))}
              className="rounded border-zinc-300"
            />
            <span className="text-sm text-zinc-700 dark:text-zinc-300">Use LLM to suggest groups</span>
          </label>
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={runDryRun}
            disabled={dryRunLoading}
            className="rounded-lg border border-zinc-300 bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-800 hover:bg-zinc-200 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
          >
            {dryRunLoading ? "Running…" : "Dry run (suggest merges)"}
          </button>
          <span className="self-center text-sm text-zinc-500 dark:text-zinc-400">
            Then use <strong>Merge</strong> below on each group to apply.
          </span>
        </div>
      </div>

      {/* Suggested merge groups */}
      <div className="mt-8">
        <h2 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">Suggested merge groups</h2>
        {dryRunLoading ? (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950/50 dark:text-blue-200">
            <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
            Analyzing {themes.length} theme(s) for merge candidates… This may take a moment.
          </div>
        ) : suggestions.length === 0 ? (
          dryRunDone ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
              Dry run complete — no merge candidates found with the current parameters. Try lowering the embedding threshold or enabling content embedding / LLM.
            </div>
          ) : (
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
              Run &quot;Dry run&quot; above to see suggested groups. Then click <strong>Merge</strong> on a group to perform the real merge (moves narratives into the canonical theme and deletes the source theme).
            </p>
          )
        ) : (
          <>
            <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200">
              Dry run complete — found {suggestions.length} merge group(s).
            </div>
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
              Green = canonical theme (others merge into it). Click <strong>Merge</strong> to apply (real merge).
            </p>
            <ul className="mt-4 space-y-4">
              {suggestions.map((group, idx) => (
                <li
                  key={idx}
                  className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    {(group.labels.length ? group.labels : group.theme_ids.map(String)).map((label, i) => (
                      <span
                        key={i}
                        className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          group.theme_ids[i] === group.canonical_theme_id
                            ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
                            : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                        }`}
                      >
                        #{group.theme_ids[i]} {label}
                      </span>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                    Canonical: theme #{group.canonical_theme_id} (others will be merged into it)
                  </p>
                  <button
                    type="button"
                    onClick={() => runMerge(group)}
                    disabled={mergeLoading !== null}
                    className="mt-3 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50 dark:bg-emerald-700 dark:hover:bg-emerald-800"
                  >
                    {mergeLoading === group.canonical_theme_id ? "Merging…" : "Merge"}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </>
  );
}
