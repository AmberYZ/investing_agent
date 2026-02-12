"use client";

import { memo, useMemo } from "react";
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

export type ThemeMetric = {
  date: string;
  share_of_voice: number | null;
  mention_count: number;
};

function ThemeCardChartInner({ data, id: chartId }: { data: ThemeMetric[]; id: number }) {
  const gradId = `share-grad-${chartId}`;
  // Use share_of_voice when available, else fall back to mention_count so the chart always shows something
  const chartData = useMemo(
    () =>
      data.length > 0
        ? data.map((d) => {
            const pct =
              d.share_of_voice != null
                ? d.share_of_voice <= 1
                  ? d.share_of_voice * 100
                  : d.share_of_voice
                : null;
            return {
              date: d.date.slice(5),
              pct: pct ?? d.mention_count,
            };
          })
        : [{ date: "", pct: 0 }],
    [data]
  );
  const maxVal = useMemo(() => {
    const values = chartData.map((d) => d.pct).filter((v) => v > 0);
    return values.length ? Math.max(...values) : 1;
  }, [chartData]);

  return (
    <div className="h-12 w-full shrink-0 text-emerald-500 dark:text-emerald-400">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="currentColor" stopOpacity={0.3} />
              <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="date" hide />
          <YAxis hide domain={[0, maxVal * 1.1 || 1]} />
          <Area
            type="monotone"
            dataKey="pct"
            stroke="currentColor"
            fill={`url(#${gradId})`}
            strokeWidth={1}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export const ThemeCardChart = memo(ThemeCardChartInner);
