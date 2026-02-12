"use client";

import Link from "next/link";
import { useState } from "react";

type Evidence = {
  id: number;
  quote: string;
  page?: number | null;
  document_id: number;
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

const INITIAL_QUOTES = 2;

function EvidenceQuote({ e }: { e: Evidence }) {
  const documentUrl = `/documents/${e.document_id}?highlight=${encodeURIComponent(e.quote)}`;
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
      <div className="whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-200">
        &ldquo;{e.quote}&rdquo;
      </div>
      <div className="mt-3 flex items-center justify-end">
        <Link
          href={documentUrl}
          className="rounded bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
        >
          Open original
        </Link>
      </div>
    </div>
  );
}

export function TodaysNarratives({ narratives }: { narratives: Narrative[] }) {
  if (narratives.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-5 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
        No narratives for this theme.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {narratives.map((n) => (
        <NarrativeCard key={n.id} narrative={n} />
      ))}
    </div>
  );
}

function NarrativeCard({ narrative: n }: { narrative: Narrative }) {
  const [showAllQuotes, setShowAllQuotes] = useState(false);
  const evidence = n.evidence ?? [];
  const visible = showAllQuotes ? evidence : evidence.slice(0, INITIAL_QUOTES);
  const hasMore = evidence.length > INITIAL_QUOTES && !showAllQuotes;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{n.statement}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {(n.date_created || n.first_seen) && (
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            {(n.date_created ?? n.first_seen ?? "").slice(0, 10)}
          </span>
        )}
        <span className="rounded bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-800 dark:bg-sky-900/50 dark:text-sky-200">
          {n.confidence_level ?? "—"}
        </span>
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${
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
        <span className="rounded bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
          {n.sub_theme ?? "—"}
        </span>
      </div>
      <div className="mt-3 space-y-3">
        {evidence.length === 0 ? (
          <div className="text-xs text-zinc-500 dark:text-zinc-400">No evidence quotes stored.</div>
        ) : (
          <>
            {visible.map((e) => (
              <EvidenceQuote key={e.id} e={e} />
            ))}
            {hasMore && (
              <button
                type="button"
                onClick={() => setShowAllQuotes(true)}
                className="text-xs font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              >
                Show {evidence.length - INITIAL_QUOTES} more quote{evidence.length - INITIAL_QUOTES === 1 ? "" : "s"}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
