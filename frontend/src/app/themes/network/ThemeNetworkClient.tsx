"use client";

import { useMemo, useState } from "react";
import { ThemeNetworkGraph } from "../../components/ThemeNetworkGraph";

type ThemeNetwork = {
  nodes: { id: number; canonical_label: string; mention_count: number }[];
  edges: { theme_id_a: number; theme_id_b: number; weight: number }[];
};

type Snapshot = { period_label: string; nodes: ThemeNetwork["nodes"]; edges: ThemeNetwork["edges"] };

export function ThemeNetworkClient({
  initialData,
  snapshots,
  months,
}: {
  initialData: ThemeNetwork | null;
  snapshots: Snapshot[] | null;
  months: number;
}) {
  const [viewMode, setViewMode] = useState<"all" | "period">("all");
  const [selectedPeriodIndex, setSelectedPeriodIndex] = useState(snapshots?.length ? snapshots.length - 1 : 0);

  const currentGraph = useMemo(() => {
    if (viewMode === "period" && snapshots?.length && snapshots[selectedPeriodIndex]) {
      const s = snapshots[selectedPeriodIndex];
      return { nodes: s.nodes, edges: s.edges };
    }
    return initialData;
  }, [viewMode, selectedPeriodIndex, snapshots, initialData]);

  const hasSnapshots = snapshots != null && snapshots.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-zinc-500 dark:text-zinc-400">View:</span>
          <button
            type="button"
            onClick={() => setViewMode("all")}
            className={`rounded-lg px-3 py-1.5 font-medium transition ${
              viewMode === "all"
                ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
                : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-700"
            }`}
          >
            All ({months} mo)
          </button>
          {hasSnapshots && (
            <button
              type="button"
              onClick={() => setViewMode("period")}
              className={`rounded-lg px-3 py-1.5 font-medium transition ${
                viewMode === "period"
                  ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
                  : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-700"
              }`}
            >
              By month
            </button>
          )}
        </div>
        {viewMode === "period" && hasSnapshots && (
          <select
            value={selectedPeriodIndex}
            onChange={(e) => setSelectedPeriodIndex(Number(e.target.value))}
            className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          >
            {snapshots.map((s, i) => (
              <option key={s.period_label} value={i}>
                {s.period_label}
              </option>
            ))}
          </select>
        )}
      </div>

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        {viewMode === "all"
          ? `Themes that appeared together in the same documents over the last ${months} months.`
          : `Themes that appeared together in the same documents in ${snapshots?.[selectedPeriodIndex]?.period_label ?? "this period"}.`}{" "}
        Node size = volume; line thickness = co-occurrence. <strong>Hover</strong> a theme to see its full name and highlight related themes; click to open.
      </p>

      {!currentGraph || currentGraph.nodes.length === 0 ? (
        <div className="flex h-[640px] items-center justify-center rounded-xl border border-zinc-200 bg-zinc-50/50 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/30 dark:text-zinc-400">
          {viewMode === "period"
            ? `No theme co-occurrence in ${snapshots?.[selectedPeriodIndex]?.period_label ?? "this period"}.`
            : "No themes in this time range."}
        </div>
      ) : (
        <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
          <ThemeNetworkGraph
            nodes={currentGraph.nodes}
            edges={currentGraph.edges}
            height={640}
          />
        </div>
      )}
    </div>
  );
}
