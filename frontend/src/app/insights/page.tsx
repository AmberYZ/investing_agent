"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type InsightEvidence = {
  document_id?: number | null;
  narrative_id?: number | null;
  theme_id?: number | null;
  document_title?: string | null;
  theme_label?: string | null;
  quote_snippet?: string | null;
};

type InsightItem = {
  title: string;
  kind: string;
  hypothesis: string;
  reasoning: string;
  evidence: InsightEvidence[];
};

type UniverseInsights = {
  consensus: InsightItem[];
  non_consensus: InsightItem[];
  forward_look: InsightItem[];
  generated_at?: string | null;
  lookback_days: number;
  stale: boolean;
};

const KIND_STYLES: Record<string, string> = {
  opportunity: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  risk: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  sector: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  theme: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  company: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
};

function formatGeneratedAt(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return null;
  }
}

function KindBadge({ kind }: { kind: string }) {
  const key = kind.toLowerCase();
  const cls = KIND_STYLES[key] ?? "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide ${cls}`}>
      {kind}
    </span>
  );
}

function EvidenceLinks({ evidence }: { evidence: InsightEvidence[] }) {
  if (!evidence.length) return null;
  return (
    <div className="mt-3 border-t border-zinc-100 pt-3 dark:border-zinc-800">
      <h4 className="text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Evidence
      </h4>
      <ul className="mt-2 space-y-2">
        {evidence.map((ev, i) => (
          <li key={i} className="rounded-lg bg-zinc-50 px-3 py-2 text-xs dark:bg-zinc-900/60">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              {ev.theme_id != null && ev.theme_label && (
                <Link
                  href={`/themes/${ev.theme_id}`}
                  className="font-medium text-zinc-800 hover:underline dark:text-zinc-200"
                >
                  {ev.theme_label}
                </Link>
              )}
              {ev.document_id != null && (
                <>
                  {ev.theme_label && <span className="text-zinc-400">·</span>}
                  <Link
                    href={`/documents/${ev.document_id}`}
                    className="font-medium text-zinc-700 hover:underline dark:text-zinc-300"
                  >
                    {ev.document_title ?? `Document ${ev.document_id}`}
                  </Link>
                </>
              )}
            </div>
            {ev.quote_snippet && (
              <p className="mt-1 text-zinc-600 dark:text-zinc-400">&ldquo;{ev.quote_snippet}&rdquo;</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function InsightCard({ item, index }: { item: InsightItem; index: number }) {
  return (
    <article className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-zinc-200 text-xs font-semibold text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200">
            {index + 1}
          </span>
          <h3 className="font-semibold text-zinc-900 dark:text-zinc-100">{item.title}</h3>
        </div>
        <KindBadge kind={item.kind} />
      </div>
      <p className="mt-3 text-sm font-medium text-zinc-800 dark:text-zinc-200">{item.hypothesis}</p>
      <div className="mt-2">
        <h4 className="text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Reasoning
        </h4>
        <p className="mt-1 text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">{item.reasoning}</p>
      </div>
      <EvidenceLinks evidence={item.evidence} />
    </article>
  );
}

function InsightSection({
  title,
  subtitle,
  items,
  emptyMessage,
}: {
  title: string;
  subtitle: string;
  items: InsightItem[];
  emptyMessage: string;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{title}</h2>
        <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">{subtitle}</p>
      </div>
      {items.length === 0 ? (
        <p className="rounded-xl border border-dashed border-zinc-200 px-4 py-6 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          {emptyMessage}
        </p>
      ) : (
        <div className="space-y-3">
          {items.map((item, i) => (
            <InsightCard key={`${item.title}-${i}`} item={item} index={i} />
          ))}
        </div>
      )}
    </section>
  );
}

export default function InsightsPage() {
  const [data, setData] = useState<UniverseInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchInsights = useCallback(async () => {
    setError(null);
    const res = await fetch(`${API_BASE}/insights/universe`, { cache: "no-store" });
    if (!res.ok) throw new Error(res.statusText || "Failed to load insights");
    return res.json() as Promise<UniverseInsights>;
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    fetchInsights()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [fetchInsights]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/insights/universe/refresh`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? res.statusText ?? "Refresh failed");
      }
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const generatedLabel = formatGeneratedAt(data?.generated_at);
  const hasContent =
    (data?.consensus?.length ?? 0) +
      (data?.non_consensus?.length ?? 0) +
      (data?.forward_look?.length ?? 0) >
    0;

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <main className="mx-auto w-full max-w-5xl px-6 py-10">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Market Insights</h1>
            <p className="mt-1 max-w-2xl text-sm text-zinc-500 dark:text-zinc-400">
              Deductions from your full recent research universe — themes, narratives, and document
              summaries. Not summaries: each item shows the logic and links to source documents.
            </p>
            {generatedLabel && (
              <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                Last generated {generatedLabel}
                {data?.lookback_days ? ` · ${data.lookback_days}-day lookback` : ""}
                {data?.stale ? " · may be stale (refreshes on weekdays)" : ""}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing || loading}
            className="flex items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
            title="Regenerate insights from recent data (uses LLM, may take up to a minute)"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={refreshing ? "animate-spin" : ""}
              aria-hidden
            >
              <path d="M21 3v6h-6" />
              <path d="M3 21v-6h6" />
              <path d="M21 3l-9 9" />
              <path d="M3 21l9-9" />
            </svg>
            {refreshing ? "Generating…" : "Refresh insights"}
          </button>
        </div>

        {loading && (
          <p className="mt-8 text-sm text-zinc-500 dark:text-zinc-400">Loading insights…</p>
        )}
        {!loading && error && (
          <p className="mt-8 text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
        {!loading && !error && !hasContent && (
          <div className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              No insights yet. Ingest recent research documents and click{" "}
              <strong>Refresh insights</strong> to generate your first analysis.
            </p>
            <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              Insights auto-refresh every weekday morning. Requires LLM_API_KEY on the backend.
            </p>
          </div>
        )}
        {!loading && !error && hasContent && data && (
          <div className="mt-8 space-y-10">
            <InsightSection
              title="Consensus opportunities & risks"
              subtitle="Views where multiple sources and themes align — what the crowd already agrees on."
              items={data.consensus}
              emptyMessage="No consensus items in the latest run."
            />
            <InsightSection
              title="Non-consensus & under-noticed"
              subtitle="Emerging angles, contrarian views, or debated themes not yet widely priced in."
              items={data.non_consensus}
              emptyMessage="No non-consensus items in the latest run."
            />
            <InsightSection
              title="Forward look"
              subtitle="Logical deductions on what sectors, themes, or companies could rise from today's setup."
              items={data.forward_look}
              emptyMessage="No forward deductions in the latest run."
            />
          </div>
        )}
      </main>
    </div>
  );
}
