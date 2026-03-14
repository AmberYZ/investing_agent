"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { TodaysNarratives } from "./TodaysNarratives";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const PAGE_SIZE = 30;

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
  theme_label?: string | null;
};

export function ThemeNarrativesClient({
  themeId,
  themeLabel,
}: {
  themeId: string;
  themeLabel: string;
}) {
  const [narratives, setNarratives] = useState<Narrative[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchPage = useCallback(
    async (offset: number): Promise<Narrative[]> => {
      const params = new URLSearchParams({
        include_children: "true",
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      const res = await fetch(`${API_BASE}/themes/${themeId}/narratives?${params}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`Failed to load narratives: ${res.status}`);
      return res.json();
    },
    [themeId]
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchPage(0)
      .then((data) => {
        if (!cancelled) {
          const list = Array.isArray(data) ? data : [];
          setNarratives(list);
          setHasMore(list.length >= PAGE_SIZE);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPage]);

  const loadMore = useCallback(() => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    const offset = narratives.length;
    fetchPage(offset)
      .then((data) => {
        const next = Array.isArray(data) ? data : [];
        setNarratives((prev) => [...prev, ...next]);
        setHasMore(next.length >= PAGE_SIZE);
      })
      .finally(() => setLoadingMore(false));
  }, [fetchPage, loadingMore, hasMore, narratives.length]);

  useLayoutEffect(() => {
    const el = loadMoreRef.current;
    if (!el || !hasMore || loading || loadingMore) return;
    const scrollRoot =
      containerRef.current?.closest<HTMLElement>("[data-narrative-scroll]") ?? null;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadMore();
      },
      { root: scrollRoot, rootMargin: "120px", threshold: 0 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loading, loadingMore, loadMore]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-zinc-500 dark:text-zinc-400">
        Loading narratives…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
        {error}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="space-y-3">
      <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
        Newest first. Scroll to load more.
      </p>
      <TodaysNarratives narratives={narratives} themeId={themeId} themeLabel={themeLabel} />
      {narratives.length > 0 && (hasMore || loadingMore) && (
        <div ref={loadMoreRef} className="flex flex-col items-center gap-2 py-4">
          {loadingMore ? (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">Loading more…</span>
          ) : (
            <>
              <button
                type="button"
                onClick={loadMore}
                className="rounded border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              >
                Load more
              </button>
              <span className="text-[11px] text-zinc-400 dark:text-zinc-500">
                or scroll down
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
