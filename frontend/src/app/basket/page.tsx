"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FollowThemeButton } from "../components/FollowThemeButton";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type BasketItem = {
  id: number;
  canonical_label: string;
  description: string | null;
  instrument_count: number;
  primary_symbol?: string | null;
  forward_pe?: number | null;
  peg_ratio?: number | null;
  latest_rsi?: number | null;
  pct_1m?: number | null;
  pct_3m?: number | null;
  pct_ytd?: number | null;
  pct_6m?: number | null;
  next_fy_eps_estimate?: number | null;
  eps_revision_up_30d?: number | null;
  eps_revision_down_30d?: number | null;
  eps_growth_pct?: number | null;
};

type InstrumentSummary = {
  id: number;
  symbol: string;
  display_name?: string | null;
  type: string;
  source: string;
  last_close?: number | null;
  pct_1m?: number | null;
  pct_3m?: number | null;
  pct_ytd?: number | null;
  forward_pe?: number | null;
  peg_ratio?: number | null;
  latest_rsi?: number | null;
  quarterly_earnings_growth_yoy?: number | null;
  quarterly_revenue_growth_yoy?: number | null;
  next_fy_eps_estimate?: number | null;
  eps_revision_up_30d?: number | null;
  eps_revision_down_30d?: number | null;
  eps_growth_pct?: number | null;
  message?: string | null;
};

/** Flat ticker row for basket ticker-only view (from GET /basket/tickers) */
type BasketTickerRow = InstrumentSummary & {
  theme_id: number;
  canonical_label: string;
};

/** One row per symbol with themes combined (for By ticker table) */
type TickerDisplayRow = Omit<InstrumentSummary, "id"> & {
  theme_ids: number[];
  theme_labels: string[];
};

function dedupeTickerRowsBySymbol(rows: BasketTickerRow[]): TickerDisplayRow[] {
  const bySymbol = new Map<string, BasketTickerRow[]>();
  for (const r of rows) {
    const key = (r.symbol || "").toUpperCase();
    if (!bySymbol.has(key)) bySymbol.set(key, []);
    bySymbol.get(key)!.push(r);
  }
  return Array.from(bySymbol.entries()).map(([symbol, group]) => {
    const first = group[0];
    const theme_ids = [...new Set(group.map((r) => r.theme_id))];
    const theme_labels = theme_ids.map(
      (tid) => group.find((r) => r.theme_id === tid)?.canonical_label ?? ""
    );
    return {
      symbol: first.symbol,
      display_name: first.display_name,
      type: first.type,
      source: first.source,
      last_close: first.last_close,
      pct_1m: first.pct_1m,
      pct_3m: first.pct_3m,
      pct_ytd: first.pct_ytd,
      forward_pe: first.forward_pe,
      peg_ratio: first.peg_ratio,
      latest_rsi: first.latest_rsi,
      quarterly_earnings_growth_yoy: first.quarterly_earnings_growth_yoy,
      quarterly_revenue_growth_yoy: first.quarterly_revenue_growth_yoy,
      next_fy_eps_estimate: first.next_fy_eps_estimate,
      eps_revision_up_30d: first.eps_revision_up_30d,
      eps_revision_down_30d: first.eps_revision_down_30d,
      eps_growth_pct: first.eps_growth_pct,
      message: first.message,
      theme_ids,
      theme_labels,
    };
  });
}

type NarrativeItem = {
  id: number;
  statement: string;
  last_seen: string;
  narrative_stance?: string | null;
  sub_theme?: string | null;
};

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  const s = v >= 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
  return `${s}%`;
}

function fmtNum(v: number | null | undefined): string {
  if (v == null) return "—";
  return String(v);
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1000) return v.toFixed(0);
  if (v >= 1) return v.toFixed(2);
  return v.toFixed(4);
}

/** Build a one-line summary: positive/negative counts or key stats from primary ticker */
function themeSummaryLine(item: BasketItem, metricsLoading?: boolean): string {
  if (metricsLoading) return "Loading metrics…";
  const parts: string[] = [];
  if (item.pct_1m != null) parts.push(`1M ${fmtPct(item.pct_1m)}`);
  if (item.pct_3m != null) parts.push(`3M ${fmtPct(item.pct_3m)}`);
  if (item.pct_ytd != null) parts.push(`YTD ${fmtPct(item.pct_ytd)}`);
  if (item.latest_rsi != null) parts.push(`RSI ${item.latest_rsi}`);
  if (parts.length === 0) return item.primary_symbol ? `${item.primary_symbol} · No data yet` : "No tickers";
  return parts.join(" · ");
}

/** Positive/negative summary for theme (e.g. "2 up, 1 down (1M)") */
function themeSentimentSummary(item: BasketItem, tickers: InstrumentSummary[]): string | null {
  if (tickers.length === 0) return null;
  const with1m = tickers.filter((t) => t.pct_1m != null);
  if (with1m.length === 0) return null;
  const up = with1m.filter((t) => (t.pct_1m ?? 0) >= 0).length;
  const down = with1m.length - up;
  if (up === with1m.length) return "All positive (1M)";
  if (down === with1m.length) return "All negative (1M)";
  return `${up} up, ${down} down (1M)`;
}

/** Fetch all narratives that have evidence on the theme's most recent activity date */
const NARRATIVES_QUERY = "on_latest_date=true";

function ThemeSection({
  item,
  onUnfollowRefetch,
  metricsLoading = false,
}: {
  item: BasketItem;
  onUnfollowRefetch?: () => void;
  metricsLoading?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [tickers, setTickers] = useState<InstrumentSummary[]>([]);
  const [tickersLoading, setTickersLoading] = useState(false);
  const [priceBlink, setPriceBlink] = useState<Record<string, boolean>>({});
  const [narratives, setNarratives] = useState<NarrativeItem[]>([]);
  const [narrativesLoading, setNarrativesLoading] = useState(true);

  useEffect(() => {
    setNarrativesLoading(true);
    fetch(`${API_BASE}/themes/${item.id}/narratives?${NARRATIVES_QUERY}&include_children=true`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data: NarrativeItem[]) => {
        setNarratives(Array.isArray(data) ? data : []);
      })
      .catch(() => setNarratives([]))
      .finally(() => setNarrativesLoading(false));
  }, [item.id]);

  const fetchTickers = useCallback(() => {
    if (!expanded) return;
    setTickersLoading(true);
    fetch(`${API_BASE}/themes/${item.id}/instruments/summary?include_children=true`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data: InstrumentSummary[]) => {
        setTickers(Array.isArray(data) ? data : []);
        setTickersLoading(false);
      })
      .catch(() => setTickersLoading(false));
  }, [item.id, expanded]);

  useEffect(() => {
    if (expanded) fetchTickers();
  }, [expanded, fetchTickers]);

  const triggerPriceBlink = useCallback((symbol: string) => {
    setPriceBlink((prev) => ({ ...prev, [symbol]: true }));
    setTimeout(() => {
      setPriceBlink((prev) => ({ ...prev, [symbol]: false }));
    }, 600);
  }, []);

  const refreshTickersWithBlink = useCallback(() => {
    if (!expanded || tickers.length === 0) return;
    const prevCloses = Object.fromEntries(tickers.map((t) => [t.symbol, t.last_close]));
    fetch(`${API_BASE}/themes/${item.id}/instruments/summary?include_children=true`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data: InstrumentSummary[]) => {
        const next = Array.isArray(data) ? data : [];
        setTickers(next);
        next.forEach((t) => {
          if (t.last_close != null && prevCloses[t.symbol] != null && prevCloses[t.symbol] !== t.last_close) {
            triggerPriceBlink(t.symbol);
          }
        });
      });
  }, [item.id, expanded, tickers, triggerPriceBlink]);

  useEffect(() => {
    if (!expanded || tickers.length === 0) return;
    const t = setInterval(refreshTickersWithBlink, 30000);
    return () => clearInterval(t);
  }, [expanded, tickers.length, refreshTickersWithBlink]);

  const sentiment = expanded ? themeSentimentSummary(item, tickers) : null;

  return (
    <section className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/themes/${item.id}`}
                className="font-semibold text-zinc-900 hover:underline dark:text-zinc-100"
              >
                {item.canonical_label}
              </Link>
              <FollowThemeButton
                themeId={item.id}
                followed
                onToggle={(_, followed) => {
                  if (!followed) onUnfollowRefetch?.();
                }}
                variant="compact"
              />
            </div>
            {item.description && (
              <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400">
                {item.description}
              </p>
            )}
            <p className="mt-1.5 text-sm text-zinc-600 dark:text-zinc-300">
              {themeSummaryLine(item, metricsLoading)}
            </p>
            {sentiment && (
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                {sentiment}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="shrink-0 rounded-lg border border-zinc-300 bg-zinc-50 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            {expanded ? "Hide tickers" : `${item.instrument_count} ticker${item.instrument_count !== 1 ? "s" : ""} ▼`}
          </button>
        </div>

        {/* Latest narratives - full width below header */}
        <div className="mt-4 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <h3 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Narratives (most recent date)</h3>
          {narrativesLoading ? (
            <p className="mt-1.5 text-xs text-zinc-400 dark:text-zinc-500">Loading…</p>
          ) : narratives.length === 0 ? (
            <p className="mt-1.5 text-xs text-zinc-400 dark:text-zinc-500">No narratives on the most recent date.</p>
          ) : (
            <ul className="mt-1.5 space-y-3">
              {narratives.map((n) => (
                <li key={n.id} className="flex flex-col gap-0.5">
                  <span className="text-sm text-zinc-700 dark:text-zinc-200 line-clamp-3">
                    {n.statement}
                  </span>
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-0 text-[11px] text-zinc-400 dark:text-zinc-500">
                    {n.narrative_stance && (
                      <span
                        className={
                          n.narrative_stance === "bullish"
                            ? "font-medium text-emerald-600 dark:text-emerald-400"
                            : n.narrative_stance === "bearish"
                              ? "font-medium text-red-600 dark:text-red-400"
                              : n.narrative_stance === "mixed"
                                ? "text-amber-600 dark:text-amber-400"
                                : ""
                        }
                      >
                        {n.narrative_stance}
                      </span>
                    )}
                    {n.sub_theme && <span>{n.sub_theme}</span>}
                    <span>
                      {n.last_seen ? new Date(n.last_seen).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : ""}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {narratives.length > 0 && (
            <Link
              href={`/themes/${item.id}`}
              className="mt-3 inline-block text-xs font-medium text-zinc-600 hover:underline dark:text-zinc-400"
            >
              View all narratives →
            </Link>
          )}
        </div>

        {expanded && (
          <div className="mt-4 border-t border-zinc-200 pt-4 dark:border-zinc-800">
            {tickersLoading ? (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading tickers…</p>
            ) : tickers.length === 0 ? (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                No tickers. Add some on the theme page.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[800px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-zinc-200 dark:border-zinc-700">
                      <th className="py-2 pr-3 font-medium text-zinc-600 dark:text-zinc-400">Symbol</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">Price</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">1M</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">3M</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">YTD</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">Fwd PE</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">PEG</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">Next FY EPS</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400" title="Revisions up (30d)">Rev ↑</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400" title="Revisions down (30d)">Rev ↓</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400" title="(Next FY EPS estimate − sum of last 4 reported quarters) / sum of last 4 reported × 100">EPS gr%</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400" title="From OVERVIEW: quarterly earnings growth year-over-year.">Qtr EPS YoY %</th>
                      <th className="py-2 pl-2 font-medium text-zinc-600 dark:text-zinc-400">RSI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tickers.map((t) => (
                      <tr key={t.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                        <td className="py-2 pr-3 font-medium text-zinc-900 dark:text-zinc-100">
                          {t.symbol}
                        </td>
                        <td className="py-2 px-2">
                          <span
                            className={`tabular-nums text-zinc-800 dark:text-zinc-200 ${priceBlink[t.symbol] ? "animate-price-blink rounded bg-emerald-200/80 px-0.5 dark:bg-emerald-800/50" : ""}`}
                          >
                            {fmtPrice(t.last_close)}
                          </span>
                        </td>
                        <td className={`py-2 px-2 tabular-nums ${(t.pct_1m ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                          {fmtPct(t.pct_1m)}
                        </td>
                        <td className={`py-2 px-2 tabular-nums ${(t.pct_3m ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                          {fmtPct(t.pct_3m)}
                        </td>
                        <td className={`py-2 px-2 tabular-nums ${(t.pct_ytd ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                          {fmtPct(t.pct_ytd)}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {fmtNum(t.forward_pe)}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {fmtNum(t.peg_ratio)}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {t.next_fy_eps_estimate != null ? String(t.next_fy_eps_estimate) : "—"}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-emerald-600 dark:text-emerald-400">
                          {t.eps_revision_up_30d != null ? String(t.eps_revision_up_30d) : "—"}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-red-600 dark:text-red-400">
                          {t.eps_revision_down_30d != null ? String(t.eps_revision_down_30d) : "—"}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {t.eps_growth_pct != null ? (
                            <span title="(Next FY EPS estimate − sum of last 4 reported) / sum of last 4 reported × 100">{t.eps_growth_pct}%</span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {t.quarterly_earnings_growth_yoy != null ? `${t.quarterly_earnings_growth_yoy}%` : "—"}
                        </td>
                        <td className="py-2 pl-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {fmtNum(t.latest_rsi)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

type BasketViewMode = "theme" | "ticker";

export default function BasketPage() {
  const [viewMode, setViewMode] = useState<BasketViewMode>("theme");
  const [items, setItems] = useState<BasketItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metricsLoading, setMetricsLoading] = useState<Set<number>>(new Set());
  const [tickerRows, setTickerRows] = useState<BasketTickerRow[]>([]);
  const [tickerLoading, setTickerLoading] = useState(false);
  const [tickerMetricsLoading, setTickerMetricsLoading] = useState(false);
  const [tickerError, setTickerError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createLabel, setCreateLabel] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const fetchBasket = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/basket/summary?include_metrics=false`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then((data: BasketItem[]) => {
        const list = Array.isArray(data) ? data : [];
        setItems(list);
        setLoading(false);
        list.forEach((item) => {
          if (!item.primary_symbol) return;
          setMetricsLoading((prev) => new Set(prev).add(item.id));
          fetch(`${API_BASE}/themes/${item.id}/basket-metrics`, { cache: "no-store" })
            .then((r) => (r.ok ? r.json() : null))
            .then((metrics: Partial<BasketItem> & { theme_id?: number } | null) => {
              if (metrics && typeof metrics.theme_id === "number")
                setItems((prev) =>
                  prev.map((it) =>
                    it.id === metrics.theme_id
                      ? {
                          ...it,
                          forward_pe: metrics.forward_pe ?? it.forward_pe,
                          peg_ratio: metrics.peg_ratio ?? it.peg_ratio,
                          latest_rsi: metrics.latest_rsi ?? it.latest_rsi,
                          pct_1m: metrics.pct_1m ?? it.pct_1m,
                          pct_3m: metrics.pct_3m ?? it.pct_3m,
                          pct_ytd: metrics.pct_ytd ?? it.pct_ytd,
                          pct_6m: metrics.pct_6m ?? it.pct_6m,
                          quarterly_earnings_growth_yoy: metrics.quarterly_earnings_growth_yoy ?? it.quarterly_earnings_growth_yoy,
                          quarterly_revenue_growth_yoy: metrics.quarterly_revenue_growth_yoy ?? it.quarterly_revenue_growth_yoy,
                          next_fy_eps_estimate: metrics.next_fy_eps_estimate ?? it.next_fy_eps_estimate,
                          eps_revision_up_30d: metrics.eps_revision_up_30d ?? it.eps_revision_up_30d,
                          eps_revision_down_30d: metrics.eps_revision_down_30d ?? it.eps_revision_down_30d,
                          eps_growth_pct: metrics.eps_growth_pct ?? it.eps_growth_pct,
                        }
                      : it
                  )
                );
            })
            .finally(() =>
              setMetricsLoading((prev) => {
                const next = new Set(prev);
                next.delete(item.id);
                return next;
              })
            );
        });
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Failed to load basket");
        setLoading(false);
      });
  }, []);

  const fetchTickers = useCallback(() => {
    setTickerLoading(true);
    setTickerError(null);
    setTickerMetricsLoading(false);
    // Fast path: get theme + symbol list only (no market data)
    fetch(`${API_BASE}/basket/tickers?include_metrics=false`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then((data: BasketTickerRow[]) => {
        const rows = Array.isArray(data) ? data : [];
        setTickerRows(rows);
        setTickerLoading(false);
        if (rows.length === 0) return;
        // Load metrics in parallel by theme (one request per theme)
        const themeIds = [...new Set(rows.map((r) => r.theme_id))];
        setTickerMetricsLoading(true);
        Promise.all(
          themeIds.map((themeId) =>
            fetch(`${API_BASE}/themes/${themeId}/instruments/summary`, { cache: "no-store" }).then(
              (r) => (r.ok ? r.json() : Promise.resolve([] as InstrumentSummary[]))
            )
          )
        )
          .then((summariesByTheme) => {
            const byTheme = new Map<number, InstrumentSummary[]>();
            themeIds.forEach((id, i) => byTheme.set(id, Array.isArray(summariesByTheme[i]) ? summariesByTheme[i] : []));
            setTickerRows((prev) =>
              prev.map((row) => {
                const summaryList = byTheme.get(row.theme_id) ?? [];
                const inv = summaryList.find((s) => s.id === row.id);
                if (!inv) return row;
                return {
                  ...row,
                  last_close: inv.last_close,
                  pct_1m: inv.pct_1m,
                  pct_3m: inv.pct_3m,
                  pct_ytd: inv.pct_ytd,
                  forward_pe: inv.forward_pe,
                  peg_ratio: inv.peg_ratio,
                  latest_rsi: inv.latest_rsi,
                  quarterly_earnings_growth_yoy: inv.quarterly_earnings_growth_yoy,
                  quarterly_revenue_growth_yoy: inv.quarterly_revenue_growth_yoy,
                  next_fy_eps_estimate: inv.next_fy_eps_estimate,
                  eps_revision_up_30d: inv.eps_revision_up_30d,
                  eps_revision_down_30d: inv.eps_revision_down_30d,
                  eps_growth_pct: inv.eps_growth_pct,
                  message: inv.message,
                };
              })
            );
          })
          .finally(() => setTickerMetricsLoading(false));
      })
      .catch((e) => {
        setTickerError(e instanceof Error ? e.message : "Failed to load tickers");
        setTickerLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchBasket();
  }, [fetchBasket]);

  useEffect(() => {
    if (viewMode === "ticker") fetchTickers();
  }, [viewMode, fetchTickers]);

  const handleCreateTheme = async (e: React.FormEvent) => {
    e.preventDefault();
    const label = createLabel.trim();
    if (!label) return;
    setCreating(true);
    setCreateError(null);
    try {
      const res = await fetch(`${API_BASE}/themes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canonical_label: label, description: createDesc.trim() || null }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? res.statusText);
      }
      const data: { id: number; canonical_label: string } = await res.json();
      setShowCreate(false);
      setCreateLabel("");
      setCreateDesc("");
      fetchBasket();
      window.location.href = `/themes/${data.id}`;
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <main className="mx-auto w-full max-w-5xl px-6 py-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">My Basket</h1>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              {viewMode === "theme"
                ? "Themes you follow. Expand a theme to see tickers and live-style price updates."
                : "All tickers across your followed themes. Sort by theme or symbol."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">View:</span>
            <button
              type="button"
              onClick={() => setViewMode("theme")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium ${viewMode === "theme" ? "bg-zinc-200 dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100" : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"}`}
            >
              By theme
            </button>
            <button
              type="button"
              onClick={() => setViewMode("ticker")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium ${viewMode === "ticker" ? "bg-zinc-200 dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100" : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"}`}
            >
              By ticker
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(!showCreate)}
              className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              {showCreate ? "Cancel" : "Create theme"}
            </button>
          </div>
        </div>

        {showCreate && (
          <form onSubmit={handleCreateTheme} className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">New theme</h2>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              Create a theme (e.g. a stock or topic). It will be added to your basket.
            </p>
            <div className="mt-4 flex flex-wrap gap-4">
              <div>
                <label htmlFor="create-label" className="block text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  Name
                </label>
                <input
                  id="create-label"
                  type="text"
                  value={createLabel}
                  onChange={(e) => setCreateLabel(e.target.value)}
                  placeholder="e.g. AAPL, Gold, China consumer"
                  className="mt-1 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                  required
                />
              </div>
              <div className="min-w-[200px] flex-1">
                <label htmlFor="create-desc" className="block text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  Description (optional)
                </label>
                <input
                  id="create-desc"
                  type="text"
                  value={createDesc}
                  onChange={(e) => setCreateDesc(e.target.value)}
                  placeholder="Short description"
                  className="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                />
              </div>
              <div className="flex items-end">
                <button
                  type="submit"
                  disabled={creating || !createLabel.trim()}
                  className="rounded-lg border border-zinc-300 bg-zinc-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-100"
                >
                  {creating ? "Creating…" : "Create"}
                </button>
              </div>
            </div>
            {createError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{createError}</p>}
          </form>
        )}

        {viewMode === "ticker" ? (
          <>
            {tickerLoading && (
              <p className="mt-6 text-sm text-zinc-500 dark:text-zinc-400">Loading tickers…</p>
            )}
            {!tickerLoading && tickerError && (
              <p className="mt-6 text-sm text-red-600 dark:text-red-400">{tickerError}</p>
            )}
            {!tickerLoading && !tickerError && tickerRows.length === 0 && (
              <p className="mt-6 text-sm text-zinc-500 dark:text-zinc-400">
                No tickers in your basket. Follow themes and add tickers on their theme pages.
              </p>
            )}
            {!tickerLoading && !tickerError && tickerRows.length > 0 && (
              <>
                {tickerMetricsLoading && (
                  <p className="mt-4 text-xs text-zinc-500 dark:text-zinc-400">Loading metrics…</p>
                )}
                <div className="mt-6 overflow-x-auto rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
                <table className="w-full min-w-[900px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-zinc-200 dark:border-zinc-700">
                      <th className="py-2 pl-5 pr-5 font-medium text-zinc-600 dark:text-zinc-400">Symbol</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">Price</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">1M</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">3M</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">YTD</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">Fwd PE</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">PEG</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">Next FY EPS</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400" title="Revisions up (30d)">Rev ↑</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400" title="Revisions down (30d)">Rev ↓</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400" title="(Next FY EPS estimate − sum of last 4 reported quarters) / sum of last 4 reported × 100">EPS gr%</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400" title="From OVERVIEW: quarterly earnings growth year-over-year.">Qtr EPS YoY %</th>
                      <th className="py-2 px-2 font-medium text-zinc-600 dark:text-zinc-400">RSI</th>
                      <th className="py-2 pl-3 font-medium text-zinc-600 dark:text-zinc-400">Theme</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dedupeTickerRowsBySymbol(tickerRows).map((t) => (
                      <tr key={t.symbol} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                        <td className="py-2 pl-5 pr-5 font-medium text-zinc-900 dark:text-zinc-100">
                          {t.symbol}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-800 dark:text-zinc-200">
                          {fmtPrice(t.last_close)}
                        </td>
                        <td className={`py-2 px-2 tabular-nums ${(t.pct_1m ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                          {fmtPct(t.pct_1m)}
                        </td>
                        <td className={`py-2 px-2 tabular-nums ${(t.pct_3m ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                          {fmtPct(t.pct_3m)}
                        </td>
                        <td className={`py-2 px-2 tabular-nums ${(t.pct_ytd ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                          {fmtPct(t.pct_ytd)}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {fmtNum(t.forward_pe)}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {fmtNum(t.peg_ratio)}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {t.next_fy_eps_estimate != null ? String(t.next_fy_eps_estimate) : "—"}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-emerald-600 dark:text-emerald-400">
                          {t.eps_revision_up_30d != null ? String(t.eps_revision_up_30d) : "—"}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-red-600 dark:text-red-400">
                          {t.eps_revision_down_30d != null ? String(t.eps_revision_down_30d) : "—"}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {t.eps_growth_pct != null ? (
                            <span title="(Next FY EPS estimate − sum of last 4 reported) / sum of last 4 reported × 100">{t.eps_growth_pct}%</span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {t.quarterly_earnings_growth_yoy != null ? `${t.quarterly_earnings_growth_yoy}%` : "—"}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-zinc-600 dark:text-zinc-400">
                          {fmtNum(t.latest_rsi)}
                        </td>
                        <td className="py-2 pl-3">
                          <span className="flex flex-wrap gap-x-1.5 gap-y-0.5">
                            {t.theme_ids.map((themeId, i) => (
                              <Link
                                key={themeId}
                                href={`/themes/${themeId}`}
                                className="font-medium text-zinc-700 hover:underline dark:text-zinc-300"
                              >
                                {t.theme_labels[i] || `Theme ${themeId}`}
                              </Link>
                            ))}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            )}
          </>
        ) : (
          <>
            {loading && (
              <p className="mt-6 text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
            )}
            {!loading && error && (
              <p className="mt-6 text-sm text-red-600 dark:text-red-400">{error}</p>
            )}
            {!loading && !error && items.length === 0 && (
              <p className="mt-6 text-sm text-zinc-500 dark:text-zinc-400">
                Your basket is empty. Follow themes from the Themes page to add them here.
              </p>
            )}
            {!loading && !error && items.length > 0 && (
              <div className="mt-6 space-y-4">
                {items.map((item) => (
                  <ThemeSection
                    key={item.id}
                    item={item}
                    onUnfollowRefetch={fetchBasket}
                    metricsLoading={metricsLoading.has(item.id)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
