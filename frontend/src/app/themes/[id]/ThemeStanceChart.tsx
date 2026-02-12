"use client";

import {
  Area,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ThemeMetricsByStance = {
  date: string;
  bullish_count: number;
  bearish_count: number;
  mixed_count: number;
  neutral_count: number;
  total_count: number;
};

const STANCE_COLORS = {
  bullish: "#22c55e",
  bearish: "#ef4444",
  mixed: "#f59e0b",
  neutral: "#94a3b8",
};

export function ThemeStanceChart({ data }: { data: ThemeMetricsByStance[] }) {
  const hasData = Array.isArray(data) && data.length > 0;
  const chartData = hasData
    ? data.map((d) => {
        const total = (d.bullish_count || 0) + (d.bearish_count || 0) + (d.mixed_count || 0) + (d.neutral_count || 0);
        const div = total > 0 ? total : 1;
        return {
          date: d.date,
          shortDate: d.date.slice(5),
          bullish_pct: ((d.bullish_count || 0) / div) * 100,
          bearish_pct: ((d.bearish_count || 0) / div) * 100,
          mixed_pct: ((d.mixed_count || 0) / div) * 100,
          neutral_pct: ((d.neutral_count || 0) / div) * 100,
          bullish_count: d.bullish_count || 0,
          bearish_count: d.bearish_count || 0,
          mixed_count: d.mixed_count || 0,
          neutral_count: d.neutral_count || 0,
          total,
        };
      })
    : [];

  if (!hasData) {
    return (
      <div className="flex h-48 w-full items-center justify-center rounded border border-zinc-200 bg-zinc-50/50 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/30 dark:text-zinc-400">
        No stance data for this time range.
      </div>
    );
  }

  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <XAxis dataKey="shortDate" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0]?.payload as (typeof chartData)[0] | undefined;
              if (!p) return null;
              return (
                <div className="rounded-lg border border-zinc-200 bg-white p-3 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">{p.date}</div>
                  <div className="mt-1 space-y-0.5">
                    <div style={{ color: STANCE_COLORS.bullish }}>
                      Bullish: {p.bullish_pct.toFixed(0)}% ({p.bullish_count})
                    </div>
                    <div style={{ color: STANCE_COLORS.bearish }}>
                      Bearish: {p.bearish_pct.toFixed(0)}% ({p.bearish_count})
                    </div>
                    <div style={{ color: STANCE_COLORS.mixed }}>
                      Mixed: {p.mixed_pct.toFixed(0)}% ({p.mixed_count})
                    </div>
                    <div style={{ color: STANCE_COLORS.neutral }}>
                      Neutral: {p.neutral_pct.toFixed(0)}% ({p.neutral_count})
                    </div>
                    <div className="pt-1 font-medium">Total: {p.total}</div>
                  </div>
                </div>
              );
            }}
          />
          <Area
            type="monotone"
            dataKey="bullish_pct"
            stackId="stance"
            fill={STANCE_COLORS.bullish}
            stroke={STANCE_COLORS.bullish}
            name="Bullish"
          />
          <Area
            type="monotone"
            dataKey="bearish_pct"
            stackId="stance"
            fill={STANCE_COLORS.bearish}
            stroke={STANCE_COLORS.bearish}
            name="Bearish"
          />
          <Area
            type="monotone"
            dataKey="mixed_pct"
            stackId="stance"
            fill={STANCE_COLORS.mixed}
            stroke={STANCE_COLORS.mixed}
            name="Mixed"
          />
          <Area
            type="monotone"
            dataKey="neutral_pct"
            stackId="stance"
            fill={STANCE_COLORS.neutral}
            stroke={STANCE_COLORS.neutral}
            name="Neutral"
          />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-2 flex flex-wrap gap-3 text-[10px]">
        <span style={{ color: STANCE_COLORS.bullish }}>Bullish</span>
        <span style={{ color: STANCE_COLORS.bearish }}>Bearish</span>
        <span style={{ color: STANCE_COLORS.mixed }}>Mixed</span>
        <span style={{ color: STANCE_COLORS.neutral }}>Neutral</span>
      </div>
    </div>
  );
}
