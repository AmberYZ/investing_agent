import Link from "next/link";
import { FollowThemeButtonWrapper } from "./FollowThemeButtonWrapper";
import { GroupThemeIntoParent } from "./GroupThemeIntoParent";
import { MarkThemeAsRead } from "./MarkThemeAsRead";
import { ThemeChartAndDayDocs } from "./ThemeChartAndDayDocs";
import { ThemeConfidenceChart } from "./ThemeConfidenceChart";
import { ThemeInstruments } from "./ThemeInstruments";
import { ThemeNotes } from "./ThemeNotes";
import { ThemeStanceChart } from "./ThemeStanceChart";
import { ThemeNarrativesClient } from "./ThemeNarrativesClient";

type Evidence = {
  id: number;
  quote: string;
  page?: number | null;
  document_id: number;
};

type Narrative = {
  id: number;
  theme_id: number;
  statement: string;
  stance: string;
  relation_to_prevailing: string;
  date_created: string;
  first_seen: string;
  last_seen: string;
  status: string;
  sub_theme?: string | null;
  narrative_stance?: string | null;
  confidence_level?: string | null;
  evidence: Evidence[];
  /** Set when narrative is from a child theme (include_children=true). */
  theme_label?: string | null;
};

type ThemeDetail = {
  id: number;
  canonical_label: string;
  description?: string | null;
  last_updated?: string | null;
  narratives: Omit<Narrative, "evidence">[];
  parent_theme_id?: number | null;
  parent_theme_label?: string | null;
  child_theme_ids?: number[];
};

type ThemeDailyMetric = {
  theme_id: number;
  date: string;
  doc_count: number;
  mention_count: number;
  share_of_voice: number | null;
};

type ThemeMetricsByStance = {
  date: string;
  bullish_count: number;
  bearish_count: number;
  mixed_count: number;
  neutral_count: number;
  total_count: number;
};

type ThemeSubThemeDaily = {
  date: string;
  sub_theme: string;
  doc_count: number;
  mention_count: number;
};

type NarrativeSummaryExtended = {
  summary: string;
  trending_sub_themes?: string[];
  inflection_alert?: string | null;
};

type ThemeDocument = {
  id: number;
  filename: string;
  received_at: string;
  summary: string | null;
  narratives: { statement: string; stance: string; relation_to_prevailing: string }[];
  excerpts: string[];
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function getTheme(id: string): Promise<ThemeDetail | null> {
  const res = await fetch(`${API_BASE}/themes/${id}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

async function getThemeMetrics(id: string, months: number): Promise<ThemeDailyMetric[]> {
  const res = await fetch(`${API_BASE}/themes/${id}/metrics?months=${months}`, {
    cache: "no-store",
  });
  if (!res.ok) return [];
  return res.json();
}

async function getThemeMetricsByStance(id: string, months: number): Promise<ThemeMetricsByStance[]> {
  const res = await fetch(`${API_BASE}/themes/${id}/metrics-by-stance?months=${months}`, {
    cache: "no-store",
  });
  if (!res.ok) return [];
  return res.json();
}

async function getThemeMetricsBySubTheme(id: string, months: number): Promise<ThemeSubThemeDaily[]> {
  const res = await fetch(`${API_BASE}/themes/${id}/metrics-by-sub-theme?months=${months}`, {
    cache: "no-store",
  });
  if (!res.ok) return [];
  return res.json();
}

async function getNarrativeSummary(id: string, period: "all" | "30d" = "30d"): Promise<NarrativeSummaryExtended | { summary: string } | null> {
  const res = await fetch(`${API_BASE}/themes/${id}/narrative-summary?period=${period}`, {
    cache: "no-store",
  });
  if (!res.ok) return null;
  return res.json();
}

async function getThemeDocuments(id: string): Promise<ThemeDocument[]> {
  const res = await fetch(`${API_BASE}/themes/${id}/documents`, { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

function Sparkline({ data }: { data: number[] }) {
  if (data.length === 0) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const norm = max === min ? data.map(() => 0.5) : data.map((v) => (v - min) / (max - min));
  const width = 120;
  const height = 32;
  const step = data.length === 1 ? width : width / (data.length - 1);
  const points = norm
    .map((v, i) => {
      const x = i * step;
      const y = height - v * (height - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-8 w-32 text-emerald-500 dark:text-emerald-400"
      aria-hidden="true"
    >
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}

function PastMonthSentimentBar({ metricsByStance }: { metricsByStance: ThemeMetricsByStance[] }) {
  const last30 = metricsByStance.slice(-30);
  const totals = last30.reduce(
    (acc, d) => ({
      bullish: acc.bullish + d.bullish_count,
      bearish: acc.bearish + d.bearish_count,
      mixed: acc.mixed + d.mixed_count,
      neutral: acc.neutral + d.neutral_count,
    }),
    { bullish: 0, bearish: 0, mixed: 0, neutral: 0 }
  );
  const total = totals.bullish + totals.bearish + totals.mixed + totals.neutral;
  if (total === 0) {
    return (
      <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
        No narratives yet for this theme in the past month.
      </p>
    );
  }
  const pct = (n: number) => (n / total) * 100;
  const segments = [
    { key: "bullish", width: pct(totals.bullish), color: "bg-emerald-500", label: "Bullish" },
    { key: "bearish", width: pct(totals.bearish), color: "bg-red-500", label: "Bearish" },
    { key: "mixed", width: pct(totals.mixed), color: "bg-amber-400", label: "Mixed" },
    { key: "neutral", width: pct(totals.neutral), color: "bg-zinc-400 dark:bg-zinc-500", label: "Neutral" },
  ].filter((s) => s.width > 0);
  return (
    <div className="mt-1.5">
      <div
        className="flex h-3 w-full overflow-hidden rounded-full"
        role="img"
        aria-label={`Past month: Bullish ${Math.round(pct(totals.bullish))}%, Bearish ${Math.round(pct(totals.bearish))}%, Mixed ${Math.round(pct(totals.mixed))}%, Neutral ${Math.round(pct(totals.neutral))}%`}
      >
        {segments.map((s) => (
          <div
            key={s.key}
            className={`${s.color} shrink-0 transition-[width]`}
            style={{ width: `${s.width}%` }}
            title={`${s.label}: ${s.width.toFixed(1)}%`}
          />
        ))}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-zinc-500 dark:text-zinc-400">
        {segments.map((s) => (
          <span key={s.key} className="flex items-center gap-1">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${s.color}`} aria-hidden />
            {s.label} {s.width.toFixed(0)}%
          </span>
        ))}
      </div>
    </div>
  );
}

export default async function ThemePage(
  props: {
    params: Promise<{ id: string }>;
    searchParams: Promise<{ months?: string }>;
  }
) {
  const { id } = await props.params;
  const { months: monthsParam } = await props.searchParams;
  const months = monthsParam === "12" ? 12 : 6;

  const [theme, metrics, metricsByStance, metricsBySubTheme, documents] = await Promise.all([
    getTheme(id),
    getThemeMetrics(id, months),
    getThemeMetricsByStance(id, months),
    getThemeMetricsBySubTheme(id, months),
    getThemeDocuments(id),
  ]);

  if (!theme) {
    return (
      <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
        <main className="mx-auto w-full max-w-5xl px-6 py-10">
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            <Link href="/" className="hover:underline">Themes</Link> / Theme not found
          </div>
          <p className="mt-4">This theme may have been removed or the link is invalid.</p>
        </main>
      </div>
    );
  }

  const sovSeries = (metrics ?? []).map((m) => {
    const sov = m.share_of_voice;
    if (sov == null) return 0;
    return sov <= 1 ? sov * 100 : sov;
  });
  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <MarkThemeAsRead themeId={theme.id} themeLastUpdated={theme.last_updated ?? null} />
      <main className="mx-auto w-full max-w-6xl px-6 py-10">
        {/* 1) Header: title, compact narrative summary (left); Add to basket, Notes, range, sparkline (right) */}
        <div className="flex flex-wrap items-stretch justify-between gap-6">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-zinc-500 dark:text-zinc-400">
              <Link href="/" className="hover:underline">
                Themes
              </Link>{" "}
              / {theme.canonical_label}
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">
              {theme.canonical_label}
            </h1>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              {theme.description ?? "—"}
            </p>
            {/* Past month sentiment mix — colored bar */}
            <div className="mt-3 rounded-lg bg-zinc-50/80 px-3 py-2 dark:bg-zinc-900/50">
              <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Narrative summary (past month)
              </div>
              <PastMonthSentimentBar metricsByStance={metricsByStance ?? []} />
            </div>
          </div>
          <div className="flex flex-col items-end justify-between gap-2 text-xs text-zinc-500 dark:text-zinc-400">
            <div className="flex flex-wrap items-center gap-2">
              <FollowThemeButtonWrapper themeId={theme.id} />
              <ThemeNotes themeId={id} />
              <GroupThemeIntoParent
                themeId={theme.id}
                themeLabel={theme.canonical_label}
                parentThemeId={theme.parent_theme_id ?? undefined}
                parentThemeLabel={theme.parent_theme_label ?? undefined}
                childThemeIds={theme.child_theme_ids ?? []}
              />
            </div>
            <div className="flex items-center gap-2">
              <span>Range:</span>
              <Link
                href={`/themes/${id}?months=6`}
                className={months === 6 ? "font-medium text-zinc-900 dark:text-zinc-100" : "hover:underline"}
              >
                6 months
              </Link>
              <Link
                href={`/themes/${id}?months=12`}
                className={months === 12 ? "font-medium text-zinc-900 dark:text-zinc-100" : "hover:underline"}
              >
                1 year
              </Link>
            </div>
            {(metrics ?? []).length > 0 && (
              <div className="font-mono">
                {metrics[0].date} → {metrics[metrics.length - 1].date}
              </div>
            )}
            {sovSeries.length > 0 && (
              <div className="flex items-center gap-2">
                <Sparkline data={sovSeries} />
                <span className="text-[11px]">share of voice</span>
              </div>
            )}
          </div>
        </div>

        {/* 2) Two columns: left = charts + instruments, right = narratives */}
        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-stretch">
          <div className="min-w-0 space-y-4">
            <ThemeInstruments themeId={id} months={months} compactLayout />
            <ThemeChartAndDayDocs
              metrics={metrics ?? []}
              metricsBySubTheme={metricsBySubTheme ?? []}
              documents={documents ?? []}
              themeId={id}
              compactLayout
            />
            <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                Narrative stance over time
              </h2>
              <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
                Bullish / bearish / mixed / neutral, stacked.
              </p>
              <div className="mt-3">
                {(metricsByStance ?? []).length > 0 ? (
                  <ThemeStanceChart data={metricsByStance} />
                ) : (
                  <div className="flex h-40 w-full items-center justify-center rounded border border-zinc-200 bg-zinc-50/50 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/30 dark:text-zinc-400">
                    No stance data
                  </div>
                )}
              </div>
            </section>
            <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                Sentiment: Fact vs Opinion
              </h2>
              <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
                Fact vs opinion stance breakdown.
              </p>
              <div className="mt-3">
                <ThemeConfidenceChart themeId={id} />
              </div>
            </section>
          </div>
          {/* Wrapper so this column doesn't affect row height; section fills it and scrolls inside */}
          <div className="relative min-h-0 min-w-0 lg:h-full">
            <section className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950 lg:absolute lg:inset-0 lg:h-full">
              <div className="shrink-0 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
                <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                  Narratives
                </h2>
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                  Newest first. Open original to view source; Reassign to move to another theme.
                </p>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3" data-narrative-scroll>
                <ThemeNarrativesClient themeId={id} themeLabel={theme.canonical_label} />
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
