"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type TrackUpdate = {
  item: string;
  update?: string | null;
  last_checked?: string | null;
};

type TrackResults = {
  items: string[];
  updates: TrackUpdate[];
};

export function ThemeTrackedResultsBox({ themeId }: { themeId: string }) {
  const [data, setData] = useState<TrackResults | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchResults = useCallback(() => {
    setLoading(true);
    fetch(`${API_BASE}/themes/${themeId}/track-results`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((d: TrackResults | null) => setData(d ?? { items: [], updates: [] }))
      .catch(() => setData({ items: [], updates: [] }))
      .finally(() => setLoading(false));
  }, [themeId]);

  useEffect(() => {
    fetchResults();
  }, [fetchResults]);

  if (loading) {
    return (
      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Tracked results</h2>
        <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">Loading…</p>
      </section>
    );
  }

  const items = data?.items ?? [];
  const updates = data?.updates ?? [];
  const updatesByItem = new Map(updates.map((u) => [u.item, u]));
  const hasUpdates = updates.length > 0;

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
      <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Tracked results</h2>
      <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
        Updates from Refresh digest. Add items via the Track button above.
      </p>

      {items.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
          Add things to track (Track button above) and run{" "}
          <Link href="/basket" className="font-medium text-zinc-800 underline hover:no-underline dark:text-zinc-200">
            Refresh digest
          </Link>{" "}
          on the basket to see updates here.
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          {items.map((item) => {
            const update = updatesByItem.get(item);
            return (
              <div key={item} className="rounded-lg border border-zinc-100 bg-zinc-50/50 p-2.5 dark:border-zinc-800 dark:bg-zinc-900/50">
                <div className="text-xs font-medium text-zinc-700 dark:text-zinc-300">{item}</div>
                {update?.update ? (
                  <>
                    <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">{update.update}</p>
                    {update.last_checked && (
                      <p className="mt-0.5 text-[10px] text-zinc-500 dark:text-zinc-400">
                        Last checked: {update.last_checked}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                    {hasUpdates ? "No update yet." : "Run Refresh digest on the basket to see updates."}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
