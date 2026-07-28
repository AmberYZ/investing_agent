"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ThemeCardGrid } from "../../components/ThemeCardGrid";
import { getReadThemeData } from "../../lib/read-themes";
import type { DiscussionsTimeline, MegathemeNode } from "./page";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const WINDOW_DAYS = 60;
const SMOOTHING_DAYS = 7;
const TOP_N_OPTIONS = [5, 8, 10, 15, 20] as const;
const DEFAULT_TOP_N = 8;

/** 7-day trailing moving average for a series. */
function movingAverage(values: number[], window: number): number[] {
  if (window < 1 || values.length === 0) return values;
  const out: number[] = [];
  for (let i = 0; i < values.length; i++) {
    const start = Math.max(0, i - window + 1);
    const slice = values.slice(start, i + 1);
    const sum = slice.reduce((a, b) => a + b, 0);
    out.push(slice.length ? Math.round((sum / slice.length) * 10) / 10 : 0);
  }
  return out;
}

type Theme = {
  id: number;
  canonical_label: string;
  description?: string | null;
  last_updated: string | null;
  is_new: boolean;
};

type ThemeMetric = {
  theme_id: number;
  date: string;
  doc_count: number;
  mention_count: number;
  share_of_voice: number | null;
  consensus_count: number;
  contrarian_count: number;
  refinement_count: number;
  new_angle_count: number;
};

function parseDateRange(start: string, end: string): { startDate: Date; endDate: Date; days: number } {
  const startDate = new Date(start + "Z");
  const endDate = new Date(end + "Z");
  const days = Math.round((endDate.getTime() - startDate.getTime()) / (24 * 60 * 60 * 1000));
  return { startDate, endDate, days };
}

function dateToKey(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** High-contrast, distinguishable colors for lines (repeat if more than 12). */
const LINE_COLORS = [
  "#0d9488", "#2563eb", "#dc2626", "#9333ea", "#ea580c",
  "#059669", "#4f46e5", "#db2777", "#ca8a04", "#0891b2",
  "#65a30d", "#be185d",
];

export function ThemeTimelineClient({ timeline }: { timeline: DiscussionsTimeline }) {
  const { startDate, endDate, days: totalDays } = parseDateRange(timeline.start_date, timeline.end_date);
  const [selectedDateKey, setSelectedDateKey] = useState(timeline.end_date.slice(0, 10));
  const [topN, setTopN] = useState(DEFAULT_TOP_N);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedThemes, setExpandedThemes] = useState<Theme[] | null>(null);
  const [expandedMetrics, setExpandedMetrics] = useState<Record<number, ThemeMetric[]> | null>(null);
  const [loadingExpand, setLoadingExpand] = useState(false);
  const [hoveredLineId, setHoveredLineId] = useState<string | null>(null);

  const selectedDate = useMemo(() => new Date(selectedDateKey + "Z"), [selectedDateKey]);

  // 60 days ending on selected date (inclusive)
  const windowDates = useMemo(() => {
    const out: string[] = [];
    const end = new Date(selectedDateKey + "Z");
    for (let i = WINDOW_DAYS - 1; i >= 0; i--) {
      const d = new Date(end);
      d.setUTCDate(d.getUTCDate() - i);
      out.push(dateToKey(d));
    }
    return out;
  }, [selectedDateKey]);

  // Megathemes with activity in this 60-day window, sorted by total volume (desc), then take top N
  const nodesInWindow = useMemo(() => {
    const withActivity = timeline.nodes.filter((n) =>
      windowDates.some((d) => (n.mention_count_by_date[d] ?? 0) > 0)
    );
    const withTotal = withActivity.map((n) => ({
      node: n,
      total: windowDates.reduce((sum, d) => sum + (n.mention_count_by_date[d] ?? 0), 0),
    }));
    withTotal.sort((a, b) => b.total - a.total);
    return withTotal.slice(0, topN).map((x) => x.node);
  }, [timeline.nodes, windowDates, topN]);

  // Chart data: one row per day in window; raw counts then 7-day smoothed for trendlines
  const chartData = useMemo(() => {
    const rawRows = windowDates.map((dateKey) => {
      const row: Record<string, string | number> = { date: dateKey.slice(5), dateKey };
      for (const n of nodesInWindow) {
        row[n.id] = n.mention_count_by_date[dateKey] ?? 0;
      }
      return row;
    });
    const smoothedRows = rawRows.map((row) => ({ ...row }));
    for (const n of nodesInWindow) {
      const series = rawRows.map((r) => Number(r[n.id]) || 0);
      const smoothed = movingAverage(series, SMOOTHING_DAYS);
      smoothedRows.forEach((row, i) => {
        row[n.id] = smoothed[i] ?? 0;
      });
    }
    return smoothedRows;
  }, [windowDates, nodesInWindow]);

  const sliderValue = useMemo(() => {
    const start = startDate.getTime();
    const end = endDate.getTime();
    const sel = selectedDate.getTime();
    return ((sel - start) / (end - start)) * 100;
  }, [startDate, endDate, selectedDate]);

  const setSliderFromPercent = useCallback(
    (pct: number) => {
      const start = startDate.getTime();
      const end = endDate.getTime();
      const t = start + (pct / 100) * (end - start);
      setSelectedDateKey(dateToKey(new Date(t)));
    },
    [startDate, endDate]
  );

  const expandMegatheme = useCallback(async (node: MegathemeNode) => {
    if (expandedId === node.id) {
      setExpandedId(null);
      setExpandedThemes(null);
      setExpandedMetrics(null);
      return;
    }
    setExpandedId(node.id);
    setLoadingExpand(true);
    try {
      const idsParam = node.theme_ids.map((id) => `ids=${id}`).join("&");
      const themesRes = await fetch(`${API_BASE}/themes?${idsParam}`, { cache: "no-store" });
      if (!themesRes.ok) {
        setExpandedThemes([]);
        setExpandedMetrics({});
        return;
      }
      const themes: Theme[] = await themesRes.json();
      const metricsRes = await Promise.all(
        node.theme_ids.map((id) =>
          fetch(`${API_BASE}/themes/${id}/metrics?months=6`, { cache: "no-store" }).then((r) =>
            r.ok ? r.json() : []
          )
        )
      );
      const metricsMap: Record<number, ThemeMetric[]> = {};
      node.theme_ids.forEach((id, i) => {
        metricsMap[id] = Array.isArray(metricsRes[i]) ? metricsRes[i] : [];
      });
      setExpandedThemes(themes);
      setExpandedMetrics(metricsMap);
    } finally {
      setLoadingExpand(false);
    }
  }, [expandedId]);

  const readData = useMemo(() => getReadThemeData(), []);

  const handleLegendClick = useCallback(
    (e: { dataKey?: string }) => {
      const id = e?.dataKey;
      if (!id || id === "date" || id === "dateKey") return;
      const node = nodesInWindow.find((n) => n.id === id);
      if (node) expandMegatheme(node);
    },
    [nodesInWindow, expandMegatheme]
  );

  const handleLineClick = useCallback(
    (node: MegathemeNode) => () => {
      expandMegatheme(node);
    },
    [expandMegatheme]
  );

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            {selectedDate.toLocaleDateString("en-US", {
              weekday: "short",
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
          </span>
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 dark:text-zinc-400">Show top</span>
            <div className="flex rounded-lg border border-zinc-200 bg-zinc-50 p-0.5 dark:border-zinc-700 dark:bg-zinc-800/50">
              {TOP_N_OPTIONS.map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setTopN(n)}
                  className={`min-w-[2rem] rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                    topN === n
                      ? "bg-white text-zinc-900 shadow dark:bg-zinc-700 dark:text-zinc-100"
                      : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
            <span className="text-zinc-500 dark:text-zinc-400">megathemes</span>
          </div>
          <span className="w-full text-zinc-500 dark:text-zinc-400 sm:w-auto">
            60 days ending this day · drag slider to scrub
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={100 / Math.max(1, totalDays)}
          value={sliderValue}
          onChange={(e) => setSliderFromPercent(Number(e.target.value))}
          className="h-2 w-full cursor-pointer appearance-none rounded-lg bg-zinc-200 dark:bg-zinc-700 accent-emerald-600 dark:accent-emerald-500"
        />
      </div>

      {nodesInWindow.length === 0 ? (
        <div className="flex min-h-[320px] items-center justify-center rounded-xl border border-zinc-200 bg-zinc-50/50 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/30 dark:text-zinc-400">
          No megathemes with activity in this 60-day window.
        </div>
      ) : (
        <>
          <div className="theme-timeline-chart rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950 shadow-sm">
            <style>{`
              .theme-timeline-chart .recharts-curve,
              .theme-timeline-chart .recharts-line-curve { transition: stroke-width 0.2s ease, stroke-opacity 0.2s ease; }
            `}</style>
            <ResponsiveContainer width="100%" height={400}>
              <LineChart
                data={chartData}
                margin={{ top: 12, right: 12, left: 12, bottom: 12 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(228 228 231 / 0.5)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: "var(--muted-foreground, #71717a)" }}
                  tickLine={false}
                  axisLine={{ stroke: "rgb(228 228 231 / 0.8)" }}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "var(--muted-foreground, #71717a)" }}
                  tickLine={false}
                  axisLine={false}
                  width={36}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ stroke: "rgb(113 113 122)", strokeWidth: 1, strokeDasharray: "4 4" }}
                  contentStyle={{
                    backgroundColor: "rgb(255 255 255)",
                    border: "1px solid rgb(228 228 231)",
                    borderRadius: "0.75rem",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
                    padding: "0.75rem 1rem",
                  }}
                  wrapperStyle={{ outline: "none" }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const dateKey = (payload[0]?.payload as { dateKey?: string })?.dateKey ?? "";
                    const dateLabel = dateKey
                      ? new Date(dateKey + "Z").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" })
                      : dateKey;
                    const items = payload
                      .filter((p) => p.dataKey !== "date" && p.dataKey !== "dateKey" && Number(p.value) > 0)
                      .map((p) => {
                        const idx = nodesInWindow.findIndex((n) => n.id === p.dataKey);
                        const color = LINE_COLORS[idx % LINE_COLORS.length];
                        const node = nodesInWindow.find((n) => n.id === p.dataKey);
                        const isHovered = hoveredLineId === p.dataKey;
                        return { dataKey: p.dataKey, label: node?.label ?? String(p.dataKey), value: Number(p.value), color, isHovered };
                      })
                      .sort((a, b) => b.value - a.value);
                    return (
                      <div className="min-w-[200px] bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-lg p-3 transition-shadow duration-150">
                        <div className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 mb-2 border-b border-zinc-200 dark:border-zinc-700 pb-1.5">
                          {dateLabel}
                        </div>
                        <div className="space-y-1.5">
                          {items.map((item) => (
                            <div
                              key={item.dataKey}
                              className={`flex items-center justify-between gap-4 rounded-md px-1.5 py-0.5 -mx-1.5 transition-colors duration-150 ${
                                item.isHovered ? "bg-zinc-100 dark:bg-zinc-800" : ""
                              }`}
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                <span
                                  className="shrink-0 w-3 h-3 rounded-full border border-white dark:border-zinc-800 shadow-sm"
                                  style={{ backgroundColor: item.color }}
                                />
                                <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200 truncate" title={item.label}>
                                  {item.label}
                                </span>
                              </div>
                              <span className="text-sm tabular-nums text-zinc-600 dark:text-zinc-300 shrink-0">
                                {item.value} mention{item.value !== 1 ? "s" : ""}
                              </span>
                            </div>
                          ))}
                        </div>
                        <p className="mt-2 pt-2 border-t border-zinc-100 dark:border-zinc-800 text-[11px] text-zinc-500 dark:text-zinc-400">
                          Click line or legend to expand themes
                        </p>
                      </div>
                    );
                  }}
                />
                <Legend
                  onClick={handleLegendClick}
                  wrapperStyle={{ cursor: "pointer" }}
                  formatter={(value, entry) => {
                    const idx = nodesInWindow.findIndex((n) => n.id === entry.dataKey);
                    const color = LINE_COLORS[idx % LINE_COLORS.length];
                    const isHovered = hoveredLineId === entry.dataKey;
                    return (
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-sm font-medium transition-colors duration-150 ${
                          isHovered
                            ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
                            : "text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-zinc-100"
                        }`}
                      >
                        <span
                          className="shrink-0 w-2.5 h-2.5 rounded-sm"
                          style={{ backgroundColor: color }}
                        />
                        {nodesInWindow.find((n) => n.id === entry.dataKey)?.label ?? value}
                      </span>
                    );
                  }}
                />
                {nodesInWindow.map((node, i) => {
                  const isHovered = hoveredLineId === node.id;
                  const isDimmed = hoveredLineId != null && hoveredLineId !== node.id;
                  return (
                    <Line
                      key={node.id}
                      type="monotone"
                      dataKey={node.id}
                      name={node.label}
                      stroke={LINE_COLORS[i % LINE_COLORS.length]}
                      strokeWidth={isHovered ? 5 : 3}
                      strokeOpacity={isDimmed ? 0.35 : 1}
                      dot={false}
                      activeDot={{ r: isHovered ? 6 : 4, strokeWidth: 2, cursor: "pointer" }}
                      isAnimationActive={false}
                      connectNulls
                      onClick={handleLineClick(node)}
                      onMouseEnter={() => setHoveredLineId(node.id)}
                      onMouseLeave={() => setHoveredLineId(null)}
                      style={{
                        cursor: "pointer",
                        transition: "stroke-width 0.2s ease, stroke-opacity 0.2s ease",
                      }}
                    />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
            <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
              Showing top {nodesInWindow.length} megathemes by volume. Lines are 7-day trendlines. Click a line or legend item to expand and see themes below.
            </p>
          </div>

          {expandedId && (
            <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950 overflow-hidden shadow-sm">
              <div className="border-b border-zinc-200 dark:border-zinc-800 px-4 py-3">
                <div className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                  Themes in this megatheme
                </div>
                {expandedThemes && expandedThemes.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {expandedThemes.map((t) => (
                      <Link
                        key={t.id}
                        href={`/themes/${t.id}`}
                        className="inline-flex items-center rounded-md bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                      >
                        {t.canonical_label}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
              <div className="p-4">
                {loadingExpand ? (
                  <div className="py-8 text-center text-sm text-zinc-500 dark:text-zinc-400">
                    Loading themes…
                  </div>
                ) : expandedThemes && expandedThemes.length > 0 && expandedMetrics ? (
                  <ThemeCardGrid
                    list={expandedThemes}
                    metricsMap={expandedMetrics}
                    readData={readData}
                    allDismissedAt={null}
                    followedIds={new Set()}
                  />
                ) : (
                  <div className="py-4 text-sm text-zinc-500 dark:text-zinc-400">
                    No themes in this cluster.
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
