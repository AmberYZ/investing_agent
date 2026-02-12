"use client";

import { useEffect, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const STANCE_COLORS: Record<string, string> = {
  bullish: "#22c55e",
  bearish: "#ef4444",
  mixed: "#f59e0b",
  neutral: "#94a3b8",
};

const HORIZONS = [
  { label: "1 mo", days: 30 },
  { label: "3 mo", days: 90 },
  { label: "6 mo", days: 180 },
  { label: "All", days: 365 },
] as const;

type StanceCounts = {
  bullish: number;
  bearish: number;
  mixed: number;
  neutral: number;
  total: number;
};

type StanceByConfidence = {
  fact: StanceCounts;
  opinion: StanceCounts;
};

function buildPieData(counts: StanceCounts) {
  const total = counts.total || 1;
  return (["bullish", "bearish", "mixed", "neutral"] as const)
    .map((stance) => ({
      name: stance.charAt(0).toUpperCase() + stance.slice(1),
      value: counts[stance],
      pct: ((counts[stance] / total) * 100).toFixed(0),
      color: STANCE_COLORS[stance],
    }))
    .filter((d) => d.value > 0);
}

function StancePie({ title, counts }: { title: string; counts: StanceCounts }) {
  const data = buildPieData(counts);
  const total = counts.total;

  if (total === 0) {
    return (
      <div className="flex flex-1 flex-col items-center">
        <div className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-200">{title}</div>
        <div className="flex h-40 w-40 items-center justify-center rounded-full border border-dashed border-zinc-300 text-xs text-zinc-400 dark:border-zinc-700">
          No data
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col items-center">
      <div className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-200">
        {title} <span className="font-normal text-zinc-400">({total})</span>
      </div>
      <div className="h-44 w-44">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={30}
              outerRadius={65}
              paddingAngle={2}
              label={({ name, pct }) => `${name} ${pct}%`}
              labelLine={false}
              style={{ fontSize: 10 }}
            >
              {data.map((entry, i) => (
                <Cell key={i} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                if (!d) return null;
                return (
                  <div className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                    <span style={{ color: d.color }} className="font-medium">
                      {d.name}
                    </span>
                    : {d.value} ({d.pct}%)
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function ThemeConfidenceChart({ themeId }: { themeId: string }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<StanceByConfidence | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`${API_BASE}/themes/${themeId}/stance-by-confidence?days=${days}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [themeId, days]);

  const empty =
    !data || (data.fact.total === 0 && data.opinion.total === 0);

  return (
    <div>
      {/* Time horizon selector */}
      <div className="mb-4 flex items-center gap-2">
        <span className="text-xs text-zinc-500 dark:text-zinc-400">Period:</span>
        {HORIZONS.map((h) => (
          <button
            key={h.days}
            onClick={() => setDays(h.days)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
              days === h.days
                ? "bg-zinc-900 text-zinc-50 dark:bg-zinc-100 dark:text-zinc-900"
                : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
            }`}
          >
            {h.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex h-48 items-center justify-center text-sm text-zinc-400">
          Loading...
        </div>
      ) : empty ? (
        <div className="flex h-48 w-full items-center justify-center rounded border border-zinc-200 bg-zinc-50/50 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/30 dark:text-zinc-400">
          No fact/opinion data for this period.
        </div>
      ) : (
        <>
          <div className="flex flex-col items-stretch gap-6 sm:flex-row sm:justify-center">
            <StancePie title="Fact-based narratives" counts={data!.fact} />
            <StancePie title="Opinion-based narratives" counts={data!.opinion} />
          </div>
          {/* Legend */}
          <div className="mt-4 flex flex-wrap justify-center gap-4 text-[11px]">
            {(["bullish", "bearish", "mixed", "neutral"] as const).map((s) => (
              <span key={s} className="flex items-center gap-1">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: STANCE_COLORS[s] }}
                />
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
