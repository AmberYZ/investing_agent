"use client";

import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type TrajectoryPoint = {
  date: string;
  direction: "improving" | "worsening" | "mixed" | "unchanged" | "unknown";
  note?: string | null;
  mention_trend?: number | null;
  share_trend?: number | null;
};

type ConsensusPeriod = {
  period_start: string;
  period_end: string;
  narrative_id: number;
  statement: string;
  share: number;
  mention_count: number;
};

type EmergingNarrative = {
  narrative_id: number;
  statement: string;
  first_seen: string;
  mention_count: number;
  novelty_score?: number | null;
  relation_to_prevailing: string;
};

type ThemeDebate = {
  score: number;
  label: string;
  narrative_count: number;
  top_narrative_share?: number | null;
};

export type ThemeInsightsData = {
  trajectory: TrajectoryPoint[];
  consensus_evolution: ConsensusPeriod[];
  emerging: EmergingNarrative[];
  debate: ThemeDebate | null;
};

const DIRECTION_COLORS: Record<string, string> = {
  improving: "#22c55e",
  worsening: "#ef4444",
  mixed: "#f59e0b",
  unchanged: "#94a3b8",
  unknown: "#64748b",
};

const DIRECTION_LABELS: Record<string, string> = {
  improving: "Improving",
  worsening: "Worsening",
  mixed: "Mixed",
  unchanged: "Unchanged",
  unknown: "Unknown",
};

function TrajectoryChart({ points }: { points: TrajectoryPoint[] }) {
  if (points.length === 0) return null;
  const order = { improving: 3, mixed: 2, unchanged: 1, worsening: 0, unknown: 0 };
  const chartData = points.map((p) => ({
    ...p,
    shortDate: p.date.slice(5),
    value: order[p.direction] ?? 0,
  }));
  return (
    <div className="h-40 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <XAxis dataKey="shortDate" tick={{ fontSize: 10 }} />
          <YAxis
            domain={[0, 3]}
            tick={{ fontSize: 10 }}
            tickFormatter={(v) =>
              ["Worsening", "Unch.", "Mixed", "Improving"][v] ?? ""
            }
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.[0]) return null;
              const p = payload[0].payload as (typeof chartData)[0];
              return (
                <div className="rounded-lg border border-zinc-200 bg-white p-2 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                  <div className="font-medium">{p.date}</div>
                  <div style={{ color: DIRECTION_COLORS[p.direction] }}>
                    {DIRECTION_LABELS[p.direction]}
                  </div>
                  {p.note && <div className="mt-1 text-zinc-500">{p.note}</div>}
                </div>
              );
            }}
          />
          <Area
            type="monotone"
            dataKey="value"
            fill={DIRECTION_COLORS.unchanged}
            stroke="transparent"
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#0f766e"
            strokeWidth={2}
            dot={({ cx, cy, payload }) => (
              <circle
                cx={cx}
                cy={cy}
                r={4}
                fill={DIRECTION_COLORS[payload.direction] ?? "#64748b"}
                stroke="#fff"
                strokeWidth={1}
              />
            )}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ThemeInsights({
  insights,
  themeLabel,
}: {
  insights: ThemeInsightsData;
  themeLabel: string;
}) {
  const { trajectory, consensus_evolution, emerging, debate } = insights;
  const hasAny =
    trajectory.length > 0 ||
    consensus_evolution.length > 0 ||
    emerging.length > 0 ||
    debate;

  if (!hasAny) return null;

  return (
    <section className="mt-8 space-y-8">
      <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
        Narrative evolution insights
      </h2>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        How this theme changes over time, where consensus is shifting, new angles, and debate intensity—beyond simple sentiment.
      </p>

      {/* 1. Trajectory: how the theme is changing over time */}
      {trajectory.length > 0 && (
        <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            1. How is &ldquo;{themeLabel}&rdquo; changing over time?
          </h3>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Direction derived from mention volume and share of voice (improving = rising attention; worsening = declining).
          </p>
          <div className="mt-4">
            <TrajectoryChart points={trajectory} />
          </div>
        </div>
      )}

      {/* 2. Consensus evolution: prevailing narrative by period */}
      {consensus_evolution.length > 0 && (
        <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            2. How does consensus change over time?
          </h3>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Prevailing view each period (e.g. week). Shifts indicate narrative rotation (e.g. from positive to ROI concerns).
          </p>
          <div className="mt-4 space-y-3">
            {consensus_evolution.slice(-8).map((p, i) => (
              <div
                key={`${p.period_start}-${p.narrative_id}`}
                className="flex gap-3 rounded-lg border border-zinc-100 bg-zinc-50/50 p-3 dark:border-zinc-800 dark:bg-zinc-900/30"
              >
                <div className="shrink-0 font-mono text-[10px] text-zinc-500 dark:text-zinc-400">
                  {p.period_start} → {p.period_end}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-zinc-800 dark:text-zinc-200">
                    &ldquo;{p.statement}&rdquo;
                  </p>
                  <p className="mt-1 text-[10px] text-zinc-500 dark:text-zinc-400">
                    {(p.share * 100).toFixed(0)}% of mentions · {p.mention_count} refs
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 3. Emerging topics / new angles */}
      {emerging.length > 0 && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/30 p-5 dark:border-violet-800 dark:bg-violet-950/20">
          <h3 className="text-sm font-semibold text-violet-900 dark:text-violet-100">
            3. New emerging topics and angles
          </h3>
          <p className="mt-1 text-xs text-violet-700 dark:text-violet-300">
            Narratives that appeared recently (last 60 days). Surfaces new angles within the theme.
          </p>
          <ul className="mt-4 space-y-3">
            {emerging.slice(0, 6).map((n) => (
              <li
                key={n.narrative_id}
                className="rounded-lg border border-violet-200 bg-white p-3 dark:border-violet-800 dark:bg-zinc-900/50"
              >
                <p className="text-sm text-zinc-800 dark:text-zinc-200">
                  {n.statement}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-zinc-500 dark:text-zinc-400">
                  <span>First seen: {n.first_seen}</span>
                  <span>·</span>
                  <span>{n.mention_count} mentions</span>
                  {n.novelty_score != null && (
                    <>
                      <span>·</span>
                      <span>Novelty: {n.novelty_score}</span>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 4. Debate intensity */}
      {debate && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/30 p-5 dark:border-amber-800 dark:bg-amber-950/20">
          <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-100">
            4. Is this theme heavily debated?
          </h3>
          <p className="mt-1 text-xs text-amber-800 dark:text-amber-200">
            When many competing views exist and no single narrative dominates, the theme is &ldquo;heavily debated&rdquo;—no quick conclusion.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <div
              className="rounded-lg border border-amber-300 bg-white px-4 py-2 dark:border-amber-700 dark:bg-zinc-900/50"
              title={`Score: ${debate.score} (0 = clear consensus, 1 = highly debated)`}
            >
              <span className="text-sm font-medium text-amber-900 dark:text-amber-100">
                {debate.label}
              </span>
            </div>
            <div className="text-xs text-zinc-600 dark:text-zinc-400">
              {debate.narrative_count} distinct narrative
              {debate.narrative_count !== 1 ? "s" : ""}
              {debate.top_narrative_share != null && (
                <> · Top view: {(debate.top_narrative_share * 100).toFixed(0)}% of mentions</>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
