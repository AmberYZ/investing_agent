"use client";

import {
  Bar,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type ThemeDetailMetric = {
  date: string;
  share_of_voice?: number | null;
  mention_count?: number;
};

/** Share of voice over time only (no consensus/contrarian breakdown). */
export function ThemeDetailChart({
  data,
  onDayClick,
}: {
  data: ThemeDetailMetric[];
  onDayClick?: (date: string) => void;
}) {
  const hasData = Array.isArray(data) && data.length > 0;
  const chartData = hasData
    ? data.map((d) => {
        const dateStr = String(d?.date ?? "");
        const sharePct =
          d.share_of_voice != null
            ? d.share_of_voice <= 1
              ? d.share_of_voice * 100
              : d.share_of_voice
            : 0;
        return {
          date: dateStr.slice(5),
          fullDate: dateStr,
          share: sharePct,
          mention_count: Number(d.mention_count) || 0,
        };
      })
    : [];

  const maxShare = chartData.length ? Math.max(...chartData.map((d) => d.share), 1) : 100;
  const yMax = Math.min(100, maxShare * 1.1);

  if (!hasData) {
    return (
      <div className="flex h-64 w-full items-center justify-center rounded border border-zinc-200 bg-zinc-50/50 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/30 dark:text-zinc-400">
        No volume data for this time range.
      </div>
    );
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} domain={[0, yMax]} allowDataOverflow tickFormatter={(v) => `${v}%`} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0]?.payload as (typeof chartData)[0] | undefined;
              if (!p) return null;
              return (
                <div className="rounded-lg border border-zinc-200 bg-white p-3 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">{p.fullDate}</div>
                  <div className="mt-1 text-zinc-600 dark:text-zinc-400">
                    Share of voice: {Number(p.share).toFixed(1)}% · {p.mention_count} mentions
                  </div>
                  {onDayClick && (
                    <div className="mt-2 text-[10px] text-zinc-500">Click chart to see documents</div>
                  )}
                </div>
              );
            }}
          />
          <Line
            type="monotone"
            dataKey="share"
            stroke="#0f766e"
            strokeWidth={2}
            dot={{ r: 3 }}
            name="Share of voice"
            connectNulls
          />
          {onDayClick && (
            <Bar
              dataKey="share"
              fill="transparent"
              cursor="pointer"
              onClick={(data: { payload?: { fullDate?: string }; fullDate?: string }) =>
                onDayClick(data?.payload?.fullDate ?? data?.fullDate ?? "")
              }
              radius={0}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-2 flex flex-wrap gap-3 text-[10px]">
        <span style={{ color: "#0f766e" }}>Share of voice</span>
        {onDayClick && <span className="text-zinc-500">· Click a day to see documents</span>}
      </div>
    </div>
  );
}
