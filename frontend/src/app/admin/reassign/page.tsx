"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const CREATE_NEW_VALUE = "__new__";

type AdminTheme = {
  id: number;
  canonical_label: string;
  description?: string | null;
  first_appeared?: string | null;
  document_count: number;
  last_updated?: string | null;
};

type NarrativeItem = {
  id: number;
  theme_id: number;
  statement: string;
  sub_theme?: string | null;
  narrative_stance?: string | null;
  last_seen: string;
};

export default function AdminReassignPage() {
  const [themes, setThemes] = useState<AdminTheme[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceThemeId, setSourceThemeId] = useState<number | null>(null);
  const [targetSelect, setTargetSelect] = useState<string>("");
  const [newThemeLabel, setNewThemeLabel] = useState("");
  const [narratives, setNarratives] = useState<NarrativeItem[]>([]);
  const [narrativesLoading, setNarrativesLoading] = useState(false);
  const [selectedNarrativeIds, setSelectedNarrativeIds] = useState<Set<number>>(new Set());
  const [reassignLoading, setReassignLoading] = useState(false);
  const [reassignMessage, setReassignMessage] = useState<string | null>(null);

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

  const loadNarratives = useCallback(async (themeId: number) => {
    setNarrativesLoading(true);
    setReassignMessage(null);
    setSelectedNarrativeIds(new Set());
    try {
      const res = await fetch(`${API_BASE}/themes/${themeId}/narratives`, { cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load narratives: ${res.status}`);
      const data = await res.json();
      setNarratives(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load narratives");
      setNarratives([]);
    } finally {
      setNarrativesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (sourceThemeId != null) loadNarratives(sourceThemeId);
    else setNarratives([]);
  }, [sourceThemeId, loadNarratives]);

  const targetThemeOptions = themes.filter((t) => t.id !== sourceThemeId);
  const isCreateNew = targetSelect === CREATE_NEW_VALUE;
  const effectiveTargetId =
    isCreateNew ? null : (targetSelect ? Number(targetSelect) : null);

  function toggleNarrative(id: number) {
    setSelectedNarrativeIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAllNarratives() {
    setSelectedNarrativeIds(new Set(narratives.map((n) => n.id)));
  }

  function deselectAllNarratives() {
    setSelectedNarrativeIds(new Set());
  }

  async function runReassign() {
    if (selectedNarrativeIds.size === 0) return;
    let targetThemeId: number;
    if (isCreateNew) {
      const label = newThemeLabel.trim();
      if (!label) {
        setError("Enter a name for the new theme.");
        return;
      }
      setReassignLoading(true);
      setError(null);
      setReassignMessage(null);
      try {
        const createRes = await fetch(`${API_BASE}/admin/themes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ canonical_label: label }),
        });
        if (!createRes.ok) {
          const err = await createRes.json().catch(() => ({}));
          throw new Error(typeof err?.detail === "string" ? err.detail : `Create theme failed: ${createRes.status}`);
        }
        const created = await createRes.json();
        targetThemeId = created.id;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Create theme failed");
        setReassignLoading(false);
        return;
      }
    } else {
      if (effectiveTargetId == null) {
        setError("Select a target theme or create a new one.");
        return;
      }
      targetThemeId = effectiveTargetId;
    }

    setReassignLoading(true);
    setError(null);
    setReassignMessage(null);
    try {
      const res = await fetch(`${API_BASE}/admin/themes/reassign-narratives`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          narrative_ids: Array.from(selectedNarrativeIds),
          target_theme_id: targetThemeId,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          typeof err?.detail === "string" ? err.detail : err?.detail?.message ?? `Reassign failed: ${res.status}`
        );
      }
      const data = await res.json();
      const msg =
        data.skipped > 0
          ? `Moved ${data.moved} narrative(s) to "${data.target_label}". ${data.skipped} skipped (duplicate statement in target).`
          : `Moved ${data.moved} narrative(s) to "${data.target_label}".`;
      setReassignMessage(msg);
      setSelectedNarrativeIds(new Set());
      if (isCreateNew) {
        setTargetSelect("");
        setNewThemeLabel("");
      }
      await loadThemes();
      if (sourceThemeId != null) await loadNarratives(sourceThemeId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reassign failed");
    } finally {
      setReassignLoading(false);
    }
  }

  const canMove =
    selectedNarrativeIds.size > 0 &&
    (effectiveTargetId != null || (isCreateNew && newThemeLabel.trim() !== ""));

  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">Reassign narratives</h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
        Move individual narratives from one theme to another when they were miscategorized (e.g. metaX narratives under meta). You can select an existing target theme or create a new one.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
          {error}
        </div>
      )}

      <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mt-2 flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">Source theme</span>
            <select
              value={sourceThemeId ?? ""}
              onChange={(e) => setSourceThemeId(e.target.value ? Number(e.target.value) : null)}
              className="min-w-[200px] rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            >
              <option value="">Select theme…</option>
              {themes.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.canonical_label} (id: {t.id})
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">Target theme</span>
            <select
              value={targetSelect}
              onChange={(e) => {
                setTargetSelect(e.target.value);
                if (e.target.value !== CREATE_NEW_VALUE) setNewThemeLabel("");
              }}
              className="min-w-[220px] rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            >
              <option value="">Select theme…</option>
              {targetThemeOptions.map((t) => (
                <option key={t.id} value={String(t.id)}>
                  {t.canonical_label} (id: {t.id})
                </option>
              ))}
              <option value={CREATE_NEW_VALUE}>Create new theme…</option>
            </select>
          </label>
          {isCreateNew && (
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">New theme name</span>
              <input
                type="text"
                value={newThemeLabel}
                onChange={(e) => setNewThemeLabel(e.target.value)}
                placeholder="e.g. metaX"
                className="min-w-[180px] rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
            </label>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={selectAllNarratives}
            disabled={narratives.length === 0}
            className="rounded border border-zinc-300 bg-white px-2 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Select all
          </button>
          <button
            type="button"
            onClick={deselectAllNarratives}
            className="rounded border border-zinc-300 bg-white px-2 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Deselect all
          </button>
        </div>
        {narrativesLoading ? (
          <p className="mt-3 text-sm text-zinc-500">Loading narratives…</p>
        ) : narratives.length === 0 && sourceThemeId != null ? (
          <p className="mt-3 text-sm text-zinc-500">No narratives for this theme.</p>
        ) : narratives.length > 0 ? (
          <div className="mt-3 max-h-64 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {narratives.map((n) => (
                <li key={n.id} className="flex items-start gap-2 px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selectedNarrativeIds.has(n.id)}
                    onChange={() => toggleNarrative(n.id)}
                    className="mt-1 rounded border-zinc-300"
                  />
                  <div className="min-w-0 flex-1 text-sm">
                    <span className="font-medium text-zinc-900 dark:text-zinc-100">{n.statement}</span>
                    <div className="mt-1 flex flex-wrap gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                      {n.sub_theme && <span>sub: {n.sub_theme}</span>}
                      {n.narrative_stance && <span>{n.narrative_stance}</span>}
                      <span>{n.last_seen ? new Date(n.last_seen).toLocaleDateString() : ""}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {reassignMessage && (
          <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200">
            {reassignMessage}
          </div>
        )}
        <div className="mt-3">
          <button
            type="button"
            onClick={runReassign}
            disabled={reassignLoading || !canMove}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 dark:bg-blue-700 dark:hover:bg-blue-800"
          >
            {reassignLoading ? "Moving…" : `Move ${selectedNarrativeIds.size} selected narrative(s)`}
          </button>
        </div>
      </div>
    </>
  );
}
