"use client";

import { useEffect, useState, useCallback, useRef } from "react";

type IngestJob = {
  id: number;
  document_id: number;
  filename?: string | null;
  source_name?: string | null;
  source_type?: string | null;
  status: string;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

const POLL_ACTIVE_MS = 3_000;  // 3s when jobs are queued/processing
const POLL_IDLE_MS = 15_000;   // 15s when all jobs are settled

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

function statusBadge(status: string) {
  const base = "rounded-full border px-2 py-0.5 text-[10px] font-medium";
  switch (status) {
    case "queued":
      return `${base} border-zinc-300 bg-zinc-100 text-zinc-700 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300`;
    case "processing":
      return `${base} border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300`;
    case "done":
      return `${base} border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300`;
    case "error":
      return `${base} border-red-300 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300`;
    default:
      return `${base} border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400`;
  }
}

function truncateFilename(name: string | null | undefined, maxWords = 5): string {
  if (!name) return "—";
  const base = name.split("/").pop() ?? name;
  const words = base.split(/[\s_\-]+/);
  if (words.length <= maxWords) return base;
  return words.slice(0, maxWords).join(" ") + "…";
}

async function fetchIngestJobs(): Promise<IngestJob[]> {
  const url = `${API_BASE}/admin/ingest-jobs?_t=${Date.now()}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const res = await fetch(url, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export function IngestJobsLive() {
  const [jobs, setJobs] = useState<IngestJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const doFetch = useCallback(async () => {
    try {
      const data = await fetchIngestJobs();
      if (!mountedRef.current) return;
      setJobs(data);
      setError(null);
      setLastUpdated(new Date());
    } catch (e) {
      if (!mountedRef.current) return;
      setError(e instanceof Error ? e.message : "Failed to fetch");
      // Keep existing jobs data visible on transient errors
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  // Simple interval-based polling — always polls at the active rate.
  // This ensures queued/processing transitions are always captured.
  useEffect(() => {
    mountedRef.current = true;
    doFetch(); // initial fetch

    intervalRef.current = setInterval(doFetch, POLL_ACTIVE_MS);

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [doFetch]);

  // Listen for immediate-refresh events from Cancel/Requeue buttons
  useEffect(() => {
    const handler = () => doFetch();
    window.addEventListener("ingest-jobs-changed", handler);
    return () => window.removeEventListener("ingest-jobs-changed", handler);
  }, [doFetch]);

  const queuedCount = jobs.filter((j) => j.status === "queued").length;
  const processingCount = jobs.filter((j) => j.status === "processing").length;
  const errorCount = jobs.filter((j) => j.status === "error").length;
  const doneCount = jobs.filter((j) => j.status === "done").length;

  const nonDoneJobs = jobs.filter((j) => j.status !== "done");
  const doneJobs = jobs.filter((j) => j.status === "done").slice(0, 100);
  const displayJobs = [...nonDoneJobs, ...doneJobs];
  const hasActiveJobs = queuedCount > 0 || processingCount > 0;

  if (loading && jobs.length === 0) {
    return (
      <div className="mt-6 text-sm text-zinc-500 dark:text-zinc-400">
        Loading ingest jobs…
      </div>
    );
  }

  if (error && jobs.length === 0) {
    return (
      <div className="mt-6 space-y-2">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          Could not load ingest jobs: {error}
        </div>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Make sure the backend is running at <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">{API_BASE}</code>
        </p>
      </div>
    );
  }

  return (
    <>
      {/* ---- Summary counts ---- */}
      {jobs.length > 0 && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-zinc-100 px-2.5 py-1 font-medium text-zinc-700 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              Queued <span className="font-semibold">{queuedCount}</span>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-blue-300 bg-blue-50 px-2.5 py-1 font-medium text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300">
              Processing <span className="font-semibold">{processingCount}</span>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-red-50 px-2.5 py-1 font-medium text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
              Error <span className="font-semibold">{errorCount}</span>
            </span>
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              ({doneCount} done — showing up to 100)
            </span>
            {lastUpdated && (
              <span className="ml-auto flex items-center gap-1.5 text-xs text-zinc-400 dark:text-zinc-500">
                {hasActiveJobs && (
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
                  </span>
                )}
                Updated {lastUpdated.toLocaleTimeString()}
                {error ? " (last fetch failed)" : ""}
              </span>
            )}
          </div>
          {queuedCount > 0 && processingCount === 0 && (
            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-200">
              Queued jobs are processed one at a time by the <strong>ingest worker</strong>. If jobs stay queued, check the terminal where you ran <code className="rounded bg-amber-100 px-1 dark:bg-amber-900">./dev.sh</code>: the worker should log &quot;Starting ingest job&quot; and use your LLM (OpenAI/Vertex). Ensure <code className="rounded bg-amber-100 px-1 dark:bg-amber-900">LLM_API_KEY</code> is set in the repo <code className="rounded bg-amber-100 px-1 dark:bg-amber-900">.env</code> and the worker process is running.
            </p>
          )}
        </>
      )}

      {/* ---- Table ---- */}
      <div className="mt-6 overflow-x-auto rounded-xl border border-zinc-200 bg-white text-xs dark:border-zinc-800 dark:bg-zinc-950">
        {displayJobs.length === 0 ? (
          <div className="p-5 text-zinc-600 dark:text-zinc-300">
            No ingest jobs yet.
          </div>
        ) : (
          <table className="min-w-full border-collapse">
            <thead>
              <tr className="border-b border-zinc-200 text-[11px] uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <th className="px-3 py-2 text-left">Job</th>
                <th className="px-3 py-2 text-left">Filename</th>
                <th className="px-3 py-2 text-left">Source</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Created</th>
                <th className="px-3 py-2 text-left">Error</th>
              </tr>
            </thead>
            <tbody>
              {displayJobs.map((j) => (
                <tr
                  key={j.id}
                  className="border-b border-zinc-100 last:border-0 dark:border-zinc-900"
                >
                  <td className="px-3 py-2 font-mono text-[11px]">#{j.id}</td>
                  <td className="max-w-[200px] truncate px-3 py-2 text-[11px]" title={j.filename ?? `doc #${j.document_id}`}>
                    {j.filename ? truncateFilename(j.filename) : `doc #${j.document_id}`}
                  </td>
                  <td className="max-w-[140px] truncate px-3 py-2 text-[11px] text-zinc-600 dark:text-zinc-400" title={[j.source_type, j.source_name].filter(Boolean).join(" · ")}>
                    {j.source_name ?? j.source_type ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-[11px]">
                    <span className={statusBadge(j.status)}>{j.status}</span>
                  </td>
                  <td className="px-3 py-2 text-[11px]">
                    {j.created_at ? new Date(j.created_at).toLocaleString() : "—"}
                  </td>
                  <td className="max-w-xs px-3 py-2 text-[11px] text-zinc-700 dark:text-zinc-200">
                    <span className="line-clamp-3">{j.error_message ?? "—"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
