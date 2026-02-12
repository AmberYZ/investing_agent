"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Area, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ThemeDetailChart } from "../../components/ThemeDetailChart";

type ThemeDailyMetric = {
  theme_id: number;
  date: string;
  doc_count: number;
  mention_count: number;
  share_of_voice: number | null;
};

type ThemeSubThemeDaily = {
  date: string;
  sub_theme: string;
  doc_count: number;
  mention_count: number;
};

type ThemeDocument = {
  id: number;
  filename: string;
  received_at: string;
  summary: string | null;
  narratives: { statement: string; stance: string; relation_to_prevailing: string }[];
  excerpts: string[];
};

function formatDateOnly(iso: string): string {
  return iso.slice(0, 10);
}

const MAX_SUB_THEMES = 8;
const OTHER_KEY = "Other";

// Expanded palette with enough contrast between neighbouring colours
const PALETTE = [
  "#3b82f6", // blue
  "#22c55e", // green
  "#f59e0b", // amber
  "#a855f7", // purple
  "#ec4899", // pink
  "#14b8a6", // teal
  "#ef4444", // red
  "#6366f1", // indigo
  "#84cc16", // lime
  "#f97316", // orange
  "#06b6d4", // cyan
  "#d946ef", // fuchsia
  "#78716c", // stone (for "Other")
];

// Build 100-% stacked data by date, keeping only the top sub-themes
function buildStackedData(
  subThemeMetrics: ThemeSubThemeDaily[],
): {
  data: { date: string; shortDate: string; [key: string]: string | number }[];
  keys: string[];
  colorMap: Record<string, string>;
} {
  // 1. Aggregate total mentions per sub-theme to rank them
  const totals: Record<string, number> = {};
  for (const r of subThemeMetrics) {
    totals[r.sub_theme] = (totals[r.sub_theme] ?? 0) + r.mention_count;
  }
  const ranked = Object.entries(totals).sort((a, b) => b[1] - a[1]);
  const topThemes = ranked.slice(0, MAX_SUB_THEMES).map(([name]) => name);
  const hasOther = ranked.length > MAX_SUB_THEMES;

  // 2. Build raw counts by date, collapsing small sub-themes into "Other"
  const byDate: Record<string, Record<string, number>> = {};
  for (const r of subThemeMetrics) {
    const d = r.date.slice(0, 10);
    if (!byDate[d]) byDate[d] = {};
    const bucket = topThemes.includes(r.sub_theme) ? r.sub_theme : OTHER_KEY;
    byDate[d][bucket] = (byDate[d][bucket] ?? 0) + r.mention_count;
  }

  // 3. Keys in display order (top themes first, then Other)
  const keys = hasOther ? [...topThemes, OTHER_KEY] : topThemes;

  // 4. Build colour map
  const colorMap: Record<string, string> = {};
  keys.forEach((k, i) => {
    colorMap[k] = k === OTHER_KEY ? "#9ca3af" : PALETTE[i % PALETTE.length];
  });

  // 5. Normalise each day to percentages (0-100)
  const data = Object.entries(byDate)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, vals]) => {
      const total = keys.reduce((sum, k) => sum + (vals[k] ?? 0), 0);
      const row: { date: string; shortDate: string; [key: string]: string | number } = {
        date,
        shortDate: date.slice(5),
      };
      keys.forEach((k) => {
        row[k] = total > 0 ? Math.round(((vals[k] ?? 0) / total) * 1000) / 10 : 0;
      });
      // keep raw counts for tooltip
      keys.forEach((k) => {
        row[`_raw_${k}`] = vals[k] ?? 0;
      });
      return row;
    });

  return { data, keys, colorMap };
}

export function ThemeChartAndDayDocs({
  metrics,
  metricsBySubTheme = [],
  documents,
  themeId,
}: {
  metrics: ThemeDailyMetric[];
  metricsBySubTheme?: ThemeSubThemeDaily[];
  documents: ThemeDocument[];
  themeId: string;
}) {
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [stackedBySubTheme, setStackedBySubTheme] = useState(true);
  const dayDocsPanelRef = useRef<HTMLDivElement>(null);

  // Close the day-docs panel when clicking outside it
  useEffect(() => {
    if (!selectedDay) return;
    function handleClickOutside(e: MouseEvent) {
      if (dayDocsPanelRef.current && !dayDocsPanelRef.current.contains(e.target as Node)) {
        setSelectedDay(null);
      }
    }
    // Delay attaching to avoid the same click that opened the panel from closing it
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClickOutside);
    }, 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [selectedDay]);

  const docsForDay =
    selectedDay && documents.length > 0
      ? documents.filter((d) => formatDateOnly(d.received_at) === selectedDay)
      : [];

  const { data: stackedData, keys: subThemeKeys, colorMap } =
    metricsBySubTheme.length > 0
      ? buildStackedData(metricsBySubTheme)
      : { data: [], keys: [] as string[], colorMap: {} as Record<string, string> };

  return (
    <section className="mt-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
          Share of voice over time
        </h2>
        {metricsBySubTheme.length > 0 && (
          <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
            <input
              type="checkbox"
              checked={stackedBySubTheme}
              onChange={(e) => setStackedBySubTheme(e.target.checked)}
              className="rounded border-zinc-300"
            />
            Stack by sub-theme
          </label>
        )}
      </div>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        This theme&apos;s share of document mentions over time. Click a day to see documents for that date.
        {metricsBySubTheme.length > 0 && " Toggle “Stack by sub-theme” to see breakdown by sub-theme."}
      </p>
      <div className="mt-4">
        {stackedBySubTheme && stackedData.length > 0 ? (
          <>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  data={stackedData}
                  margin={{ top: 8, right: 8, bottom: 8, left: 8 }}
                  onClick={(state) => {
                    if (state?.activePayload?.[0]?.payload?.date) {
                      setSelectedDay(state.activePayload[0].payload.date);
                    }
                  }}
                  style={{ cursor: "pointer" }}
                >
                  <XAxis dataKey="shortDate" tick={{ fontSize: 11 }} />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    domain={[0, 100]}
                    tickFormatter={(v: number) => `${v}%`}
                    allowDataOverflow={false}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const p = payload[0]?.payload as (typeof stackedData)[0] | undefined;
                      if (!p) return null;
                      return (
                        <div className="rounded-lg border border-zinc-200 bg-white p-3 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                          <div className="mb-1.5 font-medium text-zinc-900 dark:text-zinc-100">{p.date}</div>
                          <div className="space-y-1">
                            {subThemeKeys.map((k) => (
                              <div key={k} className="flex items-center gap-2">
                                <span
                                  className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-sm"
                                  style={{ backgroundColor: colorMap[k] }}
                                />
                                <span className="truncate text-zinc-700 dark:text-zinc-300" style={{ maxWidth: 180 }}>{k}</span>
                                <span className="ml-auto whitespace-nowrap font-medium text-zinc-900 dark:text-zinc-100">
                                  {Number(p[k] ?? 0).toFixed(1)}%
                                </span>
                                <span className="whitespace-nowrap text-zinc-400">
                                  ({Number(p[`_raw_${k}`] ?? 0)})
                                </span>
                              </div>
                            ))}
                          </div>
                          <div className="mt-2 text-[10px] text-zinc-500">Click to see documents</div>
                        </div>
                      );
                    }}
                  />
                  {subThemeKeys.map((key) => (
                    <Area
                      key={key}
                      type="monotone"
                      dataKey={key}
                      stackId="sub"
                      fill={colorMap[key]}
                      stroke={colorMap[key]}
                      fillOpacity={0.85}
                      strokeWidth={0.5}
                      name={key}
                    />
                  ))}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            {/* Legend */}
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 px-1">
              {subThemeKeys.map((k) => (
                <div key={k} className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-400">
                  <span
                    className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-sm"
                    style={{ backgroundColor: colorMap[k] }}
                  />
                  <span className="max-w-[180px] truncate">{k}</span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <ThemeDetailChart data={metrics} onDayClick={(date) => setSelectedDay(date || null)} />
        )}
      </div>

      {selectedDay && (
        <div ref={dayDocsPanelRef} className="mt-6 border-t border-zinc-200 pt-6 dark:border-zinc-800">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              Documents on {selectedDay}
            </h3>
            <button
              onClick={() => setSelectedDay(null)}
              className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
              aria-label="Close documents panel"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          {docsForDay.length === 0 ? (
            <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              No documents for this theme on this day.
            </p>
          ) : (
            <div className="mt-3 space-y-4">
              {docsForDay.map((doc) => (
                <div
                  key={doc.id}
                  className="rounded-lg border border-zinc-100 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/30"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Link
                      href={`/documents/${doc.id}`}
                      className="font-medium text-zinc-900 hover:underline dark:text-zinc-100"
                    >
                      {doc.filename}
                    </Link>
                    <Link
                      href={`/documents/${doc.id}`}
                      className="rounded bg-zinc-900 px-2 py-1 text-[11px] font-medium text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
                    >
                      Open Original
                    </Link>
                  </div>
                  {(doc.narratives ?? []).length > 0 && (
                    <div className="mt-2 space-y-1.5">
                      {(doc.narratives ?? []).map((n, i) => (
                        <div key={i} className="group relative">
                          <div className="rounded bg-zinc-100 px-2.5 py-1.5 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                            <span className="line-clamp-2">{n.statement ?? ""}</span>
                          </div>
                          {(n.statement?.length ?? 0) > 100 && (
                            <div className="pointer-events-none absolute left-0 top-full z-50 mt-1 hidden max-w-md rounded-lg border border-zinc-200 bg-white p-3 text-xs text-zinc-700 shadow-xl group-hover:block dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200">
                              {n.statement}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {(doc.excerpts ?? []).length > 0 && (
                    <div className="mt-3 space-y-2">
                      {(doc.excerpts ?? []).slice(0, 3).map((ex, i) => (
                        <div
                          key={i}
                          className="rounded border border-zinc-200 bg-white p-2 text-xs text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900/50 dark:text-zinc-200"
                        >
                          &ldquo;{(ex ?? "").slice(0, 300)}
                          {(ex ?? "").length > 300 ? "…" : ""}&rdquo;
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
