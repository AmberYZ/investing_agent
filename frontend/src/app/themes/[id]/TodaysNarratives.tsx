"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Evidence = {
  id: number;
  quote: string;
  page?: number | null;
  document_id: number;
  source_display?: string | null;
};

type Narrative = {
  id: number;
  theme_id: number;
  statement: string;
  date_created?: string | null;
  first_seen?: string | null;
  last_seen?: string | null;
  sub_theme?: string | null;
  narrative_stance?: string | null;
  confidence_level?: string | null;
  evidence: Evidence[];
};

type ThemeOption = { id: number; canonical_label: string };

/** First evidence's doc/source used for the single "Open original" and source label per narrative */
function narrativePrimaryEvidence(evidence: Evidence[]) {
  return evidence.length > 0 ? evidence[0] : null;
}

/** Unique source labels from evidence (for display when multiple docs) */
function narrativeSourceLabel(evidence: Evidence[]): string {
  const labels = [...new Set(evidence.map((e) => e.source_display).filter(Boolean))] as string[];
  return labels.length ? labels.join(", ") : "";
}

export function TodaysNarratives({
  narratives,
  themeId,
}: {
  narratives: Narrative[];
  themeId: string;
}) {
  if (narratives.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-5 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
        No narratives for this theme.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {narratives.map((n) => (
        <NarrativeCard key={n.id} narrative={n} themeId={themeId} />
      ))}
    </div>
  );
}

function NarrativeCard({
  narrative: n,
  themeId,
}: {
  narrative: Narrative;
  themeId: string;
}) {
  const router = useRouter();
  const [showAllQuotes, setShowAllQuotes] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);
  const [themes, setThemes] = useState<ThemeOption[]>([]);
  const [targetThemeId, setTargetThemeId] = useState<string>("");
  const [reassignLoading, setReassignLoading] = useState(false);
  const [reassignError, setReassignError] = useState<string | null>(null);

  const evidence = n.evidence ?? [];
  const primary = narrativePrimaryEvidence(evidence);
  const sourceLabel = narrativeSourceLabel(evidence);
  const documentUrl = primary
    ? `/documents/${primary.document_id}?highlight=${encodeURIComponent(primary.quote)}`
    : null;
  const INITIAL_QUOTES = 3;
  const visibleQuotes = showAllQuotes ? evidence : evidence.slice(0, INITIAL_QUOTES);
  const hasMoreQuotes = evidence.length > INITIAL_QUOTES && !showAllQuotes;

  const openReassign = useCallback(() => {
    setReassignOpen(true);
    setReassignError(null);
    setTargetThemeId("");
    fetch(`${API_BASE}/themes?sort=label`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data: ThemeOption[]) => {
        setThemes(Array.isArray(data) ? data.filter((t) => t.id !== Number(themeId)) : []);
      })
      .catch(() => setThemes([]));
  }, [themeId]);

  const runReassign = useCallback(async () => {
    const tid = targetThemeId ? Number(targetThemeId) : null;
    if (tid == null || tid === Number(themeId)) return;
    setReassignLoading(true);
    setReassignError(null);
    try {
      const res = await fetch(`${API_BASE}/admin/themes/reassign-narratives`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ narrative_ids: [n.id], target_theme_id: tid }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          typeof err?.detail === "string" ? err.detail : err?.detail?.message ?? `Reassign failed: ${res.status}`
        );
      }
      setReassignOpen(false);
      router.refresh();
    } catch (e) {
      setReassignError(e instanceof Error ? e.message : "Reassign failed");
    } finally {
      setReassignLoading(false);
    }
  }, [n.id, targetThemeId, themeId, router]);

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{n.statement}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {(n.date_created || n.first_seen) && (
              <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                {(n.date_created ?? n.first_seen ?? "").slice(0, 10)}
              </span>
            )}
            <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[11px] font-medium text-sky-800 dark:bg-sky-900/50 dark:text-sky-200">
              {n.confidence_level ?? "—"}
            </span>
            <span
              className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                n.narrative_stance === "bullish"
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
                  : n.narrative_stance === "bearish"
                    ? "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200"
                    : n.narrative_stance === "mixed"
                      ? "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200"
                      : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
              }`}
            >
              {n.narrative_stance ?? "—"}
            </span>
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
              {n.sub_theme ?? "—"}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {sourceLabel && (
            <span className="text-[11px] text-zinc-400 dark:text-zinc-500" title="Source">
              {sourceLabel}
            </span>
          )}
          {documentUrl && (
            <Link
              href={documentUrl}
              className="shrink-0 rounded bg-zinc-800 px-2 py-1 text-[11px] font-medium text-zinc-50 hover:bg-zinc-700 dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-100"
            >
              Open original
            </Link>
          )}
          <button
            type="button"
            onClick={openReassign}
            className="shrink-0 rounded border border-zinc-300 bg-white px-2 py-1 text-[11px] font-medium text-zinc-600 hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            Reassign
          </button>
        </div>
      </div>

      {/* Quotes as compact text */}
      <div className="mt-2 border-t border-zinc-100 pt-2 dark:border-zinc-800">
        {evidence.length === 0 ? (
          <div className="text-[11px] text-zinc-500 dark:text-zinc-400">No evidence quotes.</div>
        ) : (
          <>
            <ul className="space-y-0.5 text-xs text-zinc-600 dark:text-zinc-300">
              {visibleQuotes.map((e) => (
                <li key={e.id} className="leading-snug">
                  &ldquo;{e.quote}&rdquo;
                </li>
              ))}
            </ul>
            {hasMoreQuotes && (
              <button
                type="button"
                onClick={() => setShowAllQuotes(true)}
                className="mt-1 text-[11px] font-medium text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100"
              >
                Show {evidence.length - INITIAL_QUOTES} more quote{evidence.length - INITIAL_QUOTES === 1 ? "" : "s"}
              </button>
            )}
          </>
        )}
      </div>

      {/* Reassign modal / inline */}
      {reassignOpen && (
        <div className="mt-3 rounded border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-900/50">
          <div className="text-xs font-medium text-zinc-700 dark:text-zinc-300">Move narrative to theme</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select
              value={targetThemeId}
              onChange={(e) => setTargetThemeId(e.target.value)}
              className="min-w-[180px] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100"
            >
              <option value="">Select theme…</option>
              {themes.map((t) => (
                <option key={t.id} value={String(t.id)}>
                  {t.canonical_label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={runReassign}
              disabled={reassignLoading || !targetThemeId}
              className="rounded bg-zinc-800 px-2 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-200 dark:text-zinc-900"
            >
              {reassignLoading ? "Moving…" : "Move"}
            </button>
            <button
              type="button"
              onClick={() => setReassignOpen(false)}
              className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-xs font-medium text-zinc-700 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
            >
              Cancel
            </button>
          </div>
          {reassignError && (
            <p className="mt-2 text-xs text-red-600 dark:text-red-400">{reassignError}</p>
          )}
        </div>
      )}
    </div>
  );
}
