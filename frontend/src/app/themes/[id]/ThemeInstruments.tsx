"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ComposedChart,
  Area,
  Bar,
  Legend,
} from "recharts";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const PRICE_CACHE_TTL_MS = 14 * 60 * 1000; // 14 min; match backend cache so refresh doesn't refetch
const QUOTE_STORAGE_KEY = "investing_quote";
/** Bump when API response schema changes (e.g. new metrics) to invalidate stale sessionStorage. */
const QUOTE_CACHE_VERSION = 2;

type ThemeInstrument = {
  id: number;
  theme_id: number;
  symbol: string;
  display_name?: string | null;
  type: string;
  source: string;
  /** When loaded with include_children, label of the theme this instrument belongs to (may be a child). */
  theme_label?: string | null;
};

/** One instrument per symbol; when both parent and child have the same ticker, prefer the current theme's row. */
function dedupeInstrumentsBySymbol(instruments: ThemeInstrument[], currentThemeId: string): ThemeInstrument[] {
  const bySymbol = new Map<string, ThemeInstrument[]>();
  for (const inst of instruments) {
    const key = (inst.symbol || "").toUpperCase();
    if (!bySymbol.has(key)) bySymbol.set(key, []);
    bySymbol.get(key)!.push(inst);
  }
  return Array.from(bySymbol.values()).map((group) => {
    const current = group.find((i) => String(i.theme_id) === currentThemeId);
    return current ?? group[0];
  });
}

type SuggestedItem = {
  symbol: string;
  display_name?: string | null;
  type: string;
};

type InstrumentSearchItem = {
  symbol: string;
  name?: string | null;
  type: string;
  region?: string | null;
  currency?: string | null;
  match_score?: number;
};

type PricePoint = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  sma_20?: number | null;
  rsi_14?: number | null;
  macd_line?: number | null;
  macd_signal?: number | null;
  macd_hist?: number | null;
};

type InstrumentQuote = {
  symbol: string;
  prices: PricePoint[];
  trailing_pe?: number | null;
  forward_pe?: number | null;
  peg_ratio?: number | null;
  ev_to_ebitda?: number | null;
  analyst_target_price?: number | null;
  analyst_strong_buy?: number | null;
  analyst_buy?: number | null;
  analyst_hold?: number | null;
  analyst_sell?: number | null;
  analyst_strong_sell?: number | null;
  eps_growth_0y_pct?: number | null;
  eps_growth_1y_pct?: number | null;
  price_sales_ttm?: number | null;
  price_book_mrq?: number | null;
  enterprise_value_ebitda?: number | null;
  message?: string | null;
};

/** Read quote from sessionStorage if present, not expired, and schema version matches. Survives page refresh. */
function getQuoteFromSessionStorage(cacheKey: string): InstrumentQuote | null {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  try {
    const raw = window.sessionStorage.getItem(`${QUOTE_STORAGE_KEY}:${cacheKey}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { data: InstrumentQuote; fetchedAt: number; version?: number };
    const { data, fetchedAt, version } = parsed;
    if (version !== QUOTE_CACHE_VERSION || !data?.prices || Date.now() - fetchedAt >= PRICE_CACHE_TTL_MS) return null;
    return data;
  } catch {
    return null;
  }
}

/** Write quote to sessionStorage so refresh can use it without refetch. */
function setQuoteInSessionStorage(cacheKey: string, data: InstrumentQuote): void {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  try {
    window.sessionStorage.setItem(
      `${QUOTE_STORAGE_KEY}:${cacheKey}`,
      JSON.stringify({ data, fetchedAt: Date.now(), version: QUOTE_CACHE_VERSION })
    );
  } catch {
    // ignore quota or parse errors
  }
}

type HistoricalPESeries = {
  date: string;
  pe: number;
  close: number;
  trailing_12m_eps: number;
};

type HistoricalPEResponse = {
  symbol: string;
  series: HistoricalPESeries[];
  current_pe: number | null;
  pe_percentile: number | null;
  message?: string | null;
};

type ThemeMetricsByStance = {
  date: string;
  bullish_count: number;
  bearish_count: number;
  mixed_count: number;
  neutral_count: number;
  total_count: number;
};

const SOURCE_LABELS: Record<string, string> = {
  manual: "Manual",
  from_documents: "Mentioned in documents",
  llm_suggested: "LLM suggested",
};

const SOURCE_STYLES: Record<string, string> = {
  manual: "bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200 border-blue-300 dark:border-blue-700",
  from_documents: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200 border-emerald-300 dark:border-emerald-700",
  llm_suggested: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200 border-amber-300 dark:border-amber-700",
};

// Keep this in sync with backend RSI_PERIOD in app/market_data.py
const RSI_PERIOD = 20;

// Keep these in sync with backend MACD_FAST / MACD_SLOW / MACD_SIGNAL in app/market_data.py
const MACD_FAST = 12;
const MACD_SLOW = 26;
const MACD_SIGNAL = 9;

const STANCE_COLORS: Record<string, string> = {
  bullish: "#22c55e",
  bearish: "#ef4444",
  mixed: "#f59e0b",
  neutral: "#94a3b8",
};

function dominantStance(m: ThemeMetricsByStance): string {
  if (!m.total_count) return "neutral";
  const counts = [
    ["bullish", m.bullish_count],
    ["bearish", m.bearish_count],
    ["mixed", m.mixed_count],
    ["neutral", m.neutral_count],
  ] as const;
  const best = counts.reduce((a, b) => (b[1] > a[1] ? b : a), ["neutral", 0]);
  return best[0];
}

function buildBasketSeries(
  symbolQuotes: Map<string, InstrumentQuote>
): { date: string; value: number }[] {
  const byDate: Record<string, number[]> = {};
  for (const [, q] of symbolQuotes) {
    if (!q.prices?.length) continue;
    const firstClose = q.prices[0].close;
    if (firstClose <= 0) continue;
    for (const p of q.prices) {
      const norm = (p.close / firstClose) * 100;
      if (!byDate[p.date]) byDate[p.date] = [];
      byDate[p.date].push(norm);
    }
  }
  return Object.entries(byDate)
    .map(([date, vals]) => ({ date, value: vals.reduce((a, b) => a + b, 0) / vals.length }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function ThemeInstruments({
  themeId,
  months = 6,
  compactLayout,
}: {
  themeId: string;
  /** Time range in months (6 or 12) — drives price and historical PE chart range */
  months?: number;
  /** When true, omit top margin for use in grid layout */
  compactLayout?: boolean;
}) {
  const [instruments, setInstruments] = useState<ThemeInstrument[]>([]);
  const [loading, setLoading] = useState(true);
  const [addSymbol, setAddSymbol] = useState("");
  const [adding, setAdding] = useState(false);
  const [fromDocsLoading, setFromDocsLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<SuggestedItem[]>([]);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [fromDocSuggestions, setFromDocSuggestions] = useState<SuggestedItem[]>([]);
  const [fromDocsSuggestLoading, setFromDocsSuggestLoading] = useState(false);
  const [searchMatches, setSearchMatches] = useState<InstrumentSearchItem[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const symbolSearchRef = useRef<HTMLDivElement>(null);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [viewMode, setViewMode] = useState<"single" | "basket">("single");
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [quote, setQuote] = useState<InstrumentQuote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [histPe, setHistPe] = useState<HistoricalPEResponse | null>(null);
  const [histPeLoading, setHistPeLoading] = useState(false);
  const [narrativeOverlay, setNarrativeOverlay] = useState(false);
  const [narrativeConfidenceFilter, setNarrativeConfidenceFilter] = useState<"all" | "fact" | "opinion">("all");
  const [stanceData, setStanceData] = useState<ThemeMetricsByStance[]>([]);
  const [overlaySpy, setOverlaySpy] = useState(true);
  const [spyQuote, setSpyQuote] = useState<InstrumentQuote | null>(null);
  const [spyQuoteLoading, setSpyQuoteLoading] = useState(false);
  const [overlayRsi, setOverlayRsi] = useState(false);

  const quoteCache = useRef<Map<string, { data: InstrumentQuote; fetchedAt: number }>>(new Map());

  const fetchInstruments = useCallback(async () => {
    const res = await fetch(`${API_BASE}/themes/${themeId}/instruments?include_children=true`, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      setInstruments(Array.isArray(data) ? data : []);
    }
  }, [themeId]);

  const dedupedInstruments = useMemo(
    () => dedupeInstrumentsBySymbol(instruments, themeId),
    [instruments, themeId]
  );

  useEffect(() => {
    setLoading(true);
    fetchInstruments().finally(() => setLoading(false));
  }, [fetchInstruments]);

  // Debounced EODHD symbol search when user types in the Symbol box
  useEffect(() => {
    const q = addSymbol.trim();
    if (searchDebounceRef.current) {
      clearTimeout(searchDebounceRef.current);
      searchDebounceRef.current = null;
    }
    if (q.length < 2) {
      setSearchMatches([]);
      setSearchOpen(false);
      return;
    }
    searchDebounceRef.current = setTimeout(async () => {
      searchDebounceRef.current = null;
      setSearchLoading(true);
      setSearchOpen(true);
      try {
        const res = await fetch(`${API_BASE}/instruments/search?q=${encodeURIComponent(q)}`, { cache: "no-store" });
        const data = await res.json().catch(() => ({}));
        setSearchMatches(data.matches ?? []);
        if (data.message) setSearchMatches((prev) => prev);
      } catch {
        setSearchMatches([]);
      } finally {
        setSearchLoading(false);
      }
    }, 300);
    return () => {
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    };
  }, [addSymbol]);

  // Close search dropdown when clicking outside
  useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (symbolSearchRef.current && !symbolSearchRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
      }
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  useEffect(() => {
    if (viewMode === "single" && dedupedInstruments.length > 0 && !selectedSymbol) {
      setSelectedSymbol(dedupedInstruments[0].symbol);
    }
    if (viewMode === "basket" && dedupedInstruments.length === 0) {
      setSelectedSymbol(null);
      setQuote(null);
    }
  }, [viewMode, dedupedInstruments, selectedSymbol]);

  const loadQuote = useCallback(
    async (symbol: string, useCache = true): Promise<InstrumentQuote | null> => {
      const cacheKey = `${symbol}-${months}`;
      const cached = quoteCache.current.get(cacheKey);
      if (useCache && cached && Date.now() - cached.fetchedAt < PRICE_CACHE_TTL_MS) {
        return cached.data;
      }
      const fromStorage = getQuoteFromSessionStorage(cacheKey);
      if (useCache && fromStorage) {
        quoteCache.current.set(cacheKey, { data: fromStorage, fetchedAt: Date.now() });
        return fromStorage;
      }
      const res = await fetch(`${API_BASE}/instruments/${encodeURIComponent(symbol)}/prices?months=${months}`);
      if (!res.ok) return null;
      const data = await res.json();
      const fetchedAt = Date.now();
      quoteCache.current.set(cacheKey, { data, fetchedAt });
      setQuoteInSessionStorage(cacheKey, data);
      return data;
    },
    [months]
  );

  const loadStance = useCallback(async () => {
    const params = new URLSearchParams({ months: String(months) });
    if (narrativeConfidenceFilter !== "all") {
      params.set("confidence", narrativeConfidenceFilter);
    }
    const res = await fetch(`${API_BASE}/themes/${themeId}/metrics-by-stance?${params.toString()}`);
    if (!res.ok) return [];
    return res.json();
  }, [themeId, months, narrativeConfidenceFilter]);

  useEffect(() => {
    if (viewMode !== "single" || !selectedSymbol) return;
    const cacheKey = `${selectedSymbol}-${months}`;
    const fromStorage = getQuoteFromSessionStorage(cacheKey);
    if (fromStorage) {
      quoteCache.current.set(cacheKey, { data: fromStorage, fetchedAt: Date.now() });
      setQuote(fromStorage);
      setQuoteLoading(false);
      loadStance().then((stance) => setStanceData(Array.isArray(stance) ? stance : []));
      return;
    }
    setQuoteLoading(true);
    setQuote(null);
    setHistPe(null);
    Promise.all([loadQuote(selectedSymbol), loadStance()]).then(([q, stance]) => {
      if (q) setQuote(q);
      setStanceData(Array.isArray(stance) ? stance : []);
      setQuoteLoading(false);
    });
  }, [viewMode, selectedSymbol, loadQuote, loadStance, months]);

  useEffect(() => {
    if (viewMode !== "single" || !selectedSymbol) {
      setHistPe(null);
      return;
    }
    setHistPeLoading(true);
    setHistPe(null);
    fetch(`${API_BASE}/instruments/${encodeURIComponent(selectedSymbol)}/historical-pe?months=${months}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: HistoricalPEResponse | null) => {
        setHistPe(data ?? null);
      })
      .finally(() => setHistPeLoading(false));
  }, [viewMode, selectedSymbol, months]);

  // Fetch SPY prices when overlay is enabled (same EODHD endpoint, ticker SPY)
  useEffect(() => {
    if (!overlaySpy || (viewMode !== "single" && viewMode !== "basket")) {
      setSpyQuote(null);
      return;
    }
    setSpyQuoteLoading(true);
    setSpyQuote(null);
    loadQuote("SPY")
      .then((q) => {
        setSpyQuote(q ?? null);
      })
      .finally(() => setSpyQuoteLoading(false));
  }, [overlaySpy, viewMode, loadQuote]);

  const handleTickerClick = (symbol: string) => {
    setViewMode("single");
    setSelectedSymbol(symbol);
  };

  const handleAdd = async () => {
    const symbol = addSymbol.trim().toUpperCase();
    if (!symbol) return;
    setAdding(true);
    try {
      const res = await fetch(`${API_BASE}/themes/${themeId}/instruments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, display_name: null, type: "stock", source: "manual" }),
      });
      if (res.ok) {
        setAddSymbol("");
        setSearchOpen(false);
        setSearchMatches([]);
        await fetchInstruments();
        if (instruments.length === 0) setSelectedSymbol(symbol);
      }
    } finally {
      setAdding(false);
    }
  };

  const handleAddFromSearch = async (match: InstrumentSearchItem) => {
    setAdding(true);
    try {
      const res = await fetch(`${API_BASE}/themes/${themeId}/instruments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: match.symbol,
          display_name: match.name ?? null,
          type: match.type || "stock",
          source: "manual",
        }),
      });
      if (res.ok) {
        setAddSymbol("");
        setSearchOpen(false);
        setSearchMatches([]);
        await fetchInstruments();
        if (instruments.length === 0) setSelectedSymbol(match.symbol);
      }
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, instrumentId: number) => {
    e.stopPropagation();
    const res = await fetch(`${API_BASE}/themes/${themeId}/instruments/${instrumentId}`, { method: "DELETE" });
    if (res.ok) await fetchInstruments();
  };

  const handleFindInDocuments = async () => {
    setFromDocsSuggestLoading(true);
    setFromDocSuggestions([]);
    try {
      const res = await fetch(`${API_BASE}/themes/${themeId}/instruments/from-documents/suggest`);
      if (res.ok) {
        const data = await res.json();
        setFromDocSuggestions(data.suggestions ?? []);
      }
    } finally {
      setFromDocsSuggestLoading(false);
    }
  };

  const handleAddFromDocSuggested = async (e: React.MouseEvent, item: SuggestedItem) => {
    e.stopPropagation();
    const res = await fetch(`${API_BASE}/themes/${themeId}/instruments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: item.symbol,
        display_name: item.display_name ?? null,
        type: item.type || "stock",
        source: "from_documents",
      }),
    });
    if (res.ok) {
      setFromDocSuggestions((prev) => prev.filter((s) => s.symbol !== item.symbol));
      await fetchInstruments();
    }
  };

  const handleSuggest = async () => {
    setSuggestLoading(true);
    setSuggestions([]);
    try {
      const res = await fetch(`${API_BASE}/themes/${themeId}/instruments/suggest`);
      if (res.ok) {
        const data = await res.json();
        setSuggestions(data.suggestions ?? []);
      }
    } finally {
      setSuggestLoading(false);
    }
  };

  const handleAddSuggested = async (e: React.MouseEvent, item: SuggestedItem) => {
    e.stopPropagation();
    const res = await fetch(`${API_BASE}/themes/${themeId}/instruments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: item.symbol,
        display_name: item.display_name ?? null,
        type: item.type || "stock",
        source: "llm_suggested",
      }),
    });
    if (res.ok) {
      setSuggestions((prev) => prev.filter((s) => s.symbol !== item.symbol));
      await fetchInstruments();
    }
  };

  const narrativeMarkers = narrativeOverlay
    ? stanceData
        .filter((m) => m.total_count > 0)
        .map((m) => ({ date: m.date.slice(0, 10), stance: dominantStance(m) }))
    : [];

  const chartData = quote?.prices ?? [];

  // For single-ticker view we chart a normalized index (100 = start),
  // optionally overlaying SPY normalized the same way so the behavior
  // matches the basket view (basket of 1).
  type SingleIndexPoint = {
    date: string;
    value: number;
    rsi_14?: number | null;
    volume: number;
    spyIndex?: number;
  };

  const singleIndexSeriesWithSpy = useMemo((): SingleIndexPoint[] => {
    if (!chartData.length) return [];

    // Build symbol index series (100 = first close)
    const firstClose = chartData[0].close;
    if (!Number.isFinite(firstClose) || firstClose <= 0) {
      return [];
    }

    const baseSymbol = Number(firstClose);

    // If SPY overlay is disabled or no SPY data yet, just return symbol index.
    if (!overlaySpy || !spyQuote?.prices?.length) {
      return chartData.map((p) => ({
        date: (p.date && String(p.date)).slice(0, 10),
        value: (p.close / baseSymbol) * 100,
        rsi_14: p.rsi_14,
        volume: p.volume,
      }));
    }

    // Build SPY normalized index (100 = first SPY close on/after symbol start)
    const spyByDate = new Map<string, number>();
    for (const p of spyQuote.prices) {
      const d = (p.date && String(p.date)).slice(0, 10);
      const c = Number(p.close);
      if (!Number.isFinite(c)) continue;
      spyByDate.set(d, c);
    }
    if (!spyByDate.size) {
      return chartData.map((p) => ({
        date: (p.date && String(p.date)).slice(0, 10),
        value: (p.close / baseSymbol) * 100,
        rsi_14: p.rsi_14,
        volume: p.volume,
      }));
    }

    const firstDate = (chartData[0].date && String(chartData[0].date)).slice(0, 10);
    const firstSpyOnOrAfter = [...spyByDate.keys()].sort().find((d) => d >= firstDate) ?? null;
    if (!firstSpyOnOrAfter) {
      return chartData.map((p) => ({
        date: (p.date && String(p.date)).slice(0, 10),
        value: (p.close / baseSymbol) * 100,
        rsi_14: p.rsi_14,
        volume: p.volume,
      }));
    }
    const baseSpy = spyByDate.get(firstSpyOnOrAfter);
    if (baseSpy == null || baseSpy === 0) {
      return chartData.map((p) => ({
        date: (p.date && String(p.date)).slice(0, 10),
        value: (p.close / baseSymbol) * 100,
        rsi_14: p.rsi_14,
        volume: p.volume,
      }));
    }

    const out: SingleIndexPoint[] = [];
    let lastSpy: number | null = baseSpy;
    for (const p of chartData) {
      const d = (p.date && String(p.date)).slice(0, 10);
      const rawSpy = spyByDate.get(d);
      if (rawSpy != null) lastSpy = rawSpy;
      const spyIndex = lastSpy != null ? (lastSpy / baseSpy) * 100 : undefined;
      out.push({
        date: d,
        value: (p.close / baseSymbol) * 100,
        rsi_14: p.rsi_14,
        volume: p.volume,
        spyIndex,
      });
    }
    return out;
  }, [chartData, overlaySpy, spyQuote?.prices]);

  const basketQuotes = useRef<Map<string, InstrumentQuote>>(new Map());
  const [basketLoading, setBasketLoading] = useState(false);
  const [basketSeries, setBasketSeries] = useState<{ date: string; value: number }[]>([]);

  useEffect(() => {
    if (viewMode !== "basket" || dedupedInstruments.length === 0) {
      setBasketSeries([]);
      return;
    }
    const loadAll = async () => {
      setBasketLoading(true);
      const map = new Map<string, InstrumentQuote>();
      for (const inst of dedupedInstruments) {
        const q = await loadQuote(inst.symbol);
        if (q?.prices?.length) map.set(inst.symbol, q);
      }
      basketQuotes.current = map;
      setBasketSeries(buildBasketSeries(map));
      setBasketLoading(false);
    };
    loadAll();
  }, [viewMode, dedupedInstruments, loadQuote]);

  type BasketPointWithSpy = { date: string; value: number; spyIndex?: number };

  const basketSeriesWithSpy = useMemo((): BasketPointWithSpy[] => {
    if (!overlaySpy || basketSeries.length === 0 || !spyQuote?.prices?.length) return basketSeries as BasketPointWithSpy[];
    const spyByDate = new Map<string, number>();
    for (const p of spyQuote.prices) {
      const d = (p.date && String(p.date)).slice(0, 10);
      const c = Number(p.close);
      if (!Number.isFinite(c)) continue;
      spyByDate.set(d, c);
    }
    if (!spyByDate.size) return basketSeries as BasketPointWithSpy[];
    const firstDate = basketSeries[0].date;
    const firstSpyOnOrAfter = [...spyByDate.keys()].sort().find((d) => d >= firstDate) ?? null;
    if (!firstSpyOnOrAfter) return basketSeries as BasketPointWithSpy[];
    const baseSpy = spyByDate.get(firstSpyOnOrAfter);
    if (baseSpy == null || baseSpy === 0) return basketSeries as BasketPointWithSpy[];
    const out: BasketPointWithSpy[] = [];
    let lastSpy: number | null = baseSpy;
    for (const p of basketSeries) {
      const d = (p.date && String(p.date)).slice(0, 10);
      const rawSpy = spyByDate.get(d);
      if (rawSpy != null) lastSpy = rawSpy;
      const spyIndex = lastSpy != null ? (lastSpy / baseSpy) * 100 : undefined;
      out.push({ ...p, spyIndex });
    }
    return out;
  }, [overlaySpy, basketSeries, spyQuote?.prices]);

  const hasBasketOverlayData =
    overlaySpy && spyQuote?.prices?.length && (basketSeriesWithSpy as BasketPointWithSpy[]).some((p) => p.spyIndex != null);

  const hasInstruments = dedupedInstruments.length > 0 || suggestions.length > 0 || fromDocSuggestions.length > 0;

  return (
    <section
      className={`rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950 ${compactLayout ? "" : "mt-8"}`}
    >
      <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">Related stocks & ETFs</h2>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        Add tickers, then view a single symbol or the basket (simple average of normalized prices). Data is cached to limit API calls.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <div ref={symbolSearchRef} className="relative inline-block">
          <input
            type="text"
            placeholder="Symbol (e.g. AAPL)"
            value={addSymbol}
            onChange={(e) => setAddSymbol(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              if (searchOpen && searchMatches.length > 0) {
                e.preventDefault();
                handleAddFromSearch(searchMatches[0]);
              } else {
                handleAdd();
              }
            }}
            className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
          {searchOpen && (searchMatches.length > 0 || searchLoading) && (
            <ul
              className="absolute left-0 top-full z-50 mt-1 max-h-48 w-72 overflow-auto rounded-lg border border-zinc-300 bg-white py-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
              role="listbox"
            >
              {searchLoading ? (
                <li className="px-3 py-2 text-sm text-zinc-500 dark:text-zinc-400">Searching…</li>
              ) : (
                searchMatches.map((m) => (
                  <li
                    key={`${m.symbol}-${m.region ?? ""}`}
                    role="option"
                    className="cursor-pointer px-3 py-2 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      handleAddFromSearch(m);
                    }}
                  >
                    <span className="font-medium text-zinc-900 dark:text-zinc-100">{m.symbol}</span>
                    {m.name ? <span className="ml-2 text-zinc-500 dark:text-zinc-400">{m.name}</span> : null}
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
        <button
          type="button"
          onClick={handleAdd}
          disabled={adding || !addSymbol.trim()}
          className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          Add
        </button>
        <button
          type="button"
          onClick={handleFindInDocuments}
          disabled={fromDocsSuggestLoading}
          className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {fromDocsSuggestLoading ? "Scanning…" : "Find in documents"}
        </button>
        <button
          type="button"
          onClick={handleSuggest}
          disabled={suggestLoading}
          className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {suggestLoading ? "Suggesting…" : "Suggest with AI"}
        </button>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-zinc-500 dark:text-zinc-400">
        <span className="flex items-center gap-1">
          <span className={`inline-block h-2.5 w-2.5 rounded border ${SOURCE_STYLES.manual}`} /> {SOURCE_LABELS.manual}
        </span>
        <span className="flex items-center gap-1">
          <span className={`inline-block h-2.5 w-2.5 rounded border ${SOURCE_STYLES.from_documents}`} /> {SOURCE_LABELS.from_documents}
        </span>
        <span className="flex items-center gap-1">
          <span className={`inline-block h-2.5 w-2.5 rounded border ${SOURCE_STYLES.llm_suggested}`} /> {SOURCE_LABELS.llm_suggested}
        </span>
      </div>

      {loading ? (
        <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
      ) : !hasInstruments ? (
        <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">
          No tickers yet. Add one above or run &quot;Find in documents&quot; / &quot;Suggest with AI&quot;.
        </p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">View:</span>
            <button
              type="button"
              onClick={() => setViewMode("single")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium ${viewMode === "single" ? "bg-zinc-200 dark:bg-zinc-700" : "bg-zinc-100 dark:bg-zinc-800"}`}
            >
              Single
            </button>
            <button
              type="button"
              onClick={() => setViewMode("basket")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium ${viewMode === "basket" ? "bg-zinc-200 dark:bg-zinc-700" : "bg-zinc-100 dark:bg-zinc-800"}`}
            >
              Basket (avg)
            </button>
          </div>

          <div className="mt-2 flex flex-wrap gap-1.5">
            {dedupedInstruments.map((inst) => {
              const fromChild = inst.theme_label && String(inst.theme_id) !== themeId;
              return (
              <button
                key={inst.id}
                type="button"
                onClick={() => handleTickerClick(inst.symbol)}
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition hover:opacity-90 ${SOURCE_STYLES[inst.source] ?? SOURCE_STYLES.manual} ${viewMode === "single" && selectedSymbol === inst.symbol ? "ring-2 ring-zinc-600 dark:ring-zinc-400" : ""}`}
                title={fromChild ? `${inst.symbol} (from ${inst.theme_label})` : `${inst.symbol} (${SOURCE_LABELS[inst.source] ?? inst.source})`}
              >
                <span>{inst.symbol}</span>
                {fromChild && <span className="text-zinc-400 dark:text-zinc-500">({inst.theme_label})</span>}
                <span
                  role="button"
                  tabIndex={-1}
                  onClick={(e) => handleDelete(e, inst.id)}
                  className="ml-0.5 rounded-full p-0.5 hover:bg-black/10 dark:hover:bg-white/10"
                  aria-label={`Remove ${inst.symbol}`}
                >
                  ×
                </span>
              </button>
              );
            })}
            {suggestions.map((s) => (
              <div
                key={`llm-${s.symbol}`}
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${SOURCE_STYLES.llm_suggested}`}
              >
                <span>{s.symbol}</span>
                <button type="button" onClick={(e) => handleAddSuggested(e, s)} className="ml-0.5 rounded-full p-0.5 hover:bg-black/10 dark:hover:bg-white/10">
                  Add
                </button>
              </div>
            ))}
            {fromDocSuggestions.map((s) => (
              <div
                key={`doc-${s.symbol}`}
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${SOURCE_STYLES.from_documents}`}
              >
                <span title={s.display_name ?? undefined}>{s.symbol}</span>
                <button type="button" onClick={(e) => handleAddFromDocSuggested(e, s)} className="ml-0.5 rounded-full p-0.5 hover:bg-black/10 dark:hover:bg-white/10">
                  Add
                </button>
              </div>
            ))}
          </div>

          {/* Inline chart */}
          <div className="mt-4 border-t border-zinc-200 pt-4 dark:border-zinc-800">
            {viewMode === "basket" ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Basket performance (normalized avg)
                  </h3>
                  <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-600 dark:text-zinc-400">
                    <label className="flex cursor-pointer items-center gap-1.5">
                      <input
                        type="checkbox"
                        checked={overlaySpy}
                        onChange={(e) => setOverlaySpy(e.target.checked)}
                        className="rounded border-zinc-300"
                      />
                      <span>Overlay with SPY (100 = start)</span>
                    </label>
                    {overlaySpy && spyQuoteLoading && (
                      <span className="text-[11px] text-zinc-500 dark:text-zinc-400">Loading SPY…</span>
                    )}
                  </div>
                </div>
                {basketLoading ? (
                  <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
                ) : basketSeries.length > 0 ? (
                  <div className="mt-2 h-56 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={basketSeriesWithSpy} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v) => (v && String(v).slice(5)) || v} />
                        <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} tickFormatter={(v) => Number(v).toFixed(0)} />
                        <Tooltip
                          content={({ active, payload }) => {
                            if (!active || !payload?.length) return null;
                            const p = payload[0]?.payload as BasketPointWithSpy | undefined;
                            if (!p) return null;
                            return (
                              <div className="rounded border bg-white p-2 text-xs shadow dark:bg-zinc-900">
                                <div className="font-medium">{p.date}</div>
                                <div>Basket: {Number(p.value).toFixed(1)}</div>
                                {overlaySpy && p.spyIndex != null && (
                                  <div>SPY: {p.spyIndex.toFixed(1)}</div>
                                )}
                              </div>
                            );
                          }}
                        />
                        <Line
                          type="monotone"
                          dataKey="value"
                          stroke="#3b82f6"
                          strokeWidth={2}
                          dot={false}
                          name="Basket (100 = start)"
                        />
                        {overlaySpy && hasBasketOverlayData && (
                          <Line
                            type="monotone"
                            dataKey="spyIndex"
                            stroke="#f59e0b"
                            strokeWidth={2}
                            strokeDasharray="4 2"
                            dot={false}
                            name="SPY (100 = start)"
                          />
                        )}
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">No price data for basket yet. Data loads from cache or API.</p>
                )}
              </>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    {selectedSymbol ?? "Select a ticker"}
                  </h3>
                  {quote && (
                    <div className="flex flex-wrap items-center gap-4 text-xs text-zinc-600 dark:text-zinc-400">
                      {quote.trailing_pe != null && (
                        <span>
                          Trailing P/E: <strong>{quote.trailing_pe.toFixed(1)}</strong>
                        </span>
                      )}
                      <span>
                        Fwd P/E:{" "}
                        <strong>
                          {quote.forward_pe != null ? quote.forward_pe.toFixed(1) : "—"}
                        </strong>
                      </span>
                      {quote.ev_to_ebitda != null && <span>EV/EBITDA: <strong>{quote.ev_to_ebitda.toFixed(1)}</strong></span>}
                      {quote.eps_growth_0y_pct != null && <span title="Current FY EPS est. growth">EPS gr 0y: <strong>{quote.eps_growth_0y_pct.toFixed(1)}%</strong></span>}
                      {quote.eps_growth_1y_pct != null && <span title="Next FY EPS est. growth">EPS gr +1y: <strong>{quote.eps_growth_1y_pct.toFixed(1)}%</strong></span>}
                      {quote.price_sales_ttm != null && <span>P/S: <strong>{quote.price_sales_ttm.toFixed(2)}</strong></span>}
                      {quote.price_book_mrq != null && <span>P/B: <strong>{quote.price_book_mrq.toFixed(2)}</strong></span>}
                      {histPe?.current_pe != null && <span>Current P/E (trailing): <strong>{histPe.current_pe}</strong></span>}
                      {histPe?.pe_percentile != null && <span>P/E percentile (hist.): <strong>{histPe.pe_percentile}%</strong></span>}
                      {/* Analyst ratings: target + bar */}
                      {(() => {
                        const sb = quote.analyst_strong_buy ?? 0, b = quote.analyst_buy ?? 0, h = quote.analyst_hold ?? 0, s = quote.analyst_sell ?? 0, ss = quote.analyst_strong_sell ?? 0;
                        const total = sb + b + h + s + ss;
                        if (total === 0 && quote.analyst_target_price == null) return null;
                        const parts = [
                          { n: sb, label: "SB", color: "bg-emerald-500" },
                          { n: b, label: "B", color: "bg-emerald-400" },
                          { n: h, label: "H", color: "bg-zinc-400" },
                          { n: s, label: "S", color: "bg-red-400" },
                          { n: ss, label: "SS", color: "bg-red-500" },
                        ];
                        return (
                          <div className="flex items-center gap-2" title="Analyst ratings: StrongBuy / Buy / Hold / Sell / StrongSell">
                            {quote.analyst_target_price != null && (
                              <span className="tabular-nums font-medium text-zinc-700 dark:text-zinc-300">${quote.analyst_target_price.toFixed(1)}</span>
                            )}
                            {total > 0 && (
                              <div className="flex items-center gap-0.5">
                                {parts.map(({ n, label, color }) => (
                                  <div key={label} className="flex items-center gap-0.5">
                                    <div className={`h-1.5 min-w-[2px] rounded-sm ${color}`} style={{ width: total ? `${Math.max(4, (n / total) * 40)}px` : 0 }} />
                                    {n > 0 && <span className="text-[10px] text-zinc-500 dark:text-zinc-400">{n}</span>}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                  )}
                </div>
                {quote?.message && <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">{quote.message}</p>}
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                    <input type="checkbox" checked={overlayRsi} onChange={(e) => setOverlayRsi(e.target.checked)} className="rounded border-zinc-300" />
                    Overlay RSI (RSI {RSI_PERIOD}, right axis)
                  </label>
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                    <input type="checkbox" checked={overlaySpy} onChange={(e) => setOverlaySpy(e.target.checked)} className="rounded border-zinc-300" />
                    Overlay with SPY (S&P 500)
                  </label>
                  {overlaySpy && spyQuoteLoading && <span className="text-xs text-zinc-500 dark:text-zinc-400">Loading SPY…</span>}
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                    <input type="checkbox" checked={narrativeOverlay} onChange={(e) => setNarrativeOverlay(e.target.checked)} className="rounded border-zinc-300" />
                    Overlay narratives (theme stance by date)
                  </label>
                  {narrativeOverlay && (
                    <span className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-400">
                      <span className="font-medium">Confidence:</span>
                      {(["all", "fact", "opinion"] as const).map((opt) => (
                        <button
                          key={opt}
                          type="button"
                          onClick={() => setNarrativeConfidenceFilter(opt)}
                          className={`rounded px-2 py-0.5 text-xs font-medium ${narrativeConfidenceFilter === opt ? "bg-zinc-200 dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100" : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200/80 dark:hover:bg-zinc-700/80"}`}
                        >
                          {opt === "all" ? "All" : opt === "fact" ? "Fact only" : "Opinion only"}
                        </button>
                      ))}
                    </span>
                  )}
                </div>

                {quoteLoading ? (
                  <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">Loading chart…</p>
                ) : chartData.length > 0 ? (
                  <>
                    <div className="mt-3 h-52 w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        {overlaySpy ? (
                          <ComposedChart
                            data={singleIndexSeriesWithSpy}
                            margin={{ top: 8, right: overlayRsi ? 52 : 8, bottom: 8, left: 8 }}
                          >
                            <XAxis
                              dataKey="date"
                              tick={{ fontSize: 10 }}
                              tickFormatter={(v) => (v && String(v).slice(5)) || v}
                            />
                            {/* Single index axis: both symbol and SPY share this normalized 100 = start scale */}
                            <YAxis
                              yAxisId="index"
                              tick={{ fontSize: 10 }}
                              domain={["auto", "auto"]}
                              tickFormatter={(v) => Number(v).toFixed(0)}
                            />
                            {/* Optional RSI axis on the right as well */}
                            {overlayRsi && (
                              <YAxis
                                yAxisId="rsi"
                                orientation="right"
                                domain={[0, 100]}
                                tick={{ fontSize: 9 }}
                                width={32}
                                tickFormatter={(v) => String(v)}
                              />
                            )}
                            <Tooltip
                              content={({ active, payload }) => {
                                if (!active || !payload?.length) return null;
                                const p = payload[0]?.payload as SingleIndexPoint | undefined;
                                if (!p) return null;
                                return (
                                  <div className="rounded-lg border border-zinc-200 bg-white p-2 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                                    <div className="font-medium">{p.date}</div>
                                    <div>
                                      {selectedSymbol}:{" "}
                                      {Number.isFinite(p.value) ? p.value.toFixed(1) : "—"}
                                    </div>
                                    {p.spyIndex != null && (
                                      <div>SPY: {p.spyIndex.toFixed(1)}</div>
                                    )}
                                    {overlayRsi && p.rsi_14 != null && (
                                      <div>
                                        RSI({RSI_PERIOD}): <strong>{p.rsi_14.toFixed(1)}</strong>
                                      </div>
                                    )}
                                    <div>Volume: {p.volume.toLocaleString()}</div>
                                  </div>
                                );
                              }}
                            />
                            {overlayRsi && (
                              <>
                                <ReferenceLine
                                  yAxisId="rsi"
                                  y={70}
                                  stroke="#ef4444"
                                  strokeDasharray="2 2"
                                  strokeOpacity={0.7}
                                />
                                <ReferenceLine
                                  yAxisId="rsi"
                                  y={30}
                                  stroke="#22c55e"
                                  strokeDasharray="2 2"
                                  strokeOpacity={0.7}
                                />
                              </>
                            )}
                            {narrativeMarkers.map((n) => (
                              <ReferenceLine
                                key={n.date}
                                x={n.date}
                                stroke={STANCE_COLORS[n.stance] ?? STANCE_COLORS.neutral}
                                strokeDasharray="2 2"
                                strokeOpacity={0.8}
                              />
                            ))}
                            {/* Selected symbol normalized index */}
                            <Line
                              yAxisId="index"
                              type="monotone"
                              dataKey="value"
                              stroke="#3b82f6"
                              strokeWidth={2}
                              dot={false}
                              name={
                                selectedSymbol
                                  ? `${selectedSymbol} (100 = start)`
                                  : "Index (100 = start)"
                              }
                            />
                            {/* SPY normalized index (same axis) */}
                            {spyQuote?.prices?.length ? (
                              <Line
                                yAxisId="index"
                                type="monotone"
                                dataKey="spyIndex"
                                stroke="#f59e0b"
                                strokeWidth={2}
                                strokeDasharray="4 2"
                                dot={false}
                                name="SPY"
                              />
                            ) : null}
                            {overlayRsi && (
                              <Line
                                type="monotone"
                                dataKey="rsi_14"
                                yAxisId="rsi"
                                stroke="#a855f7"
                                strokeWidth={1.5}
                                dot={false}
                                name={`RSI(${RSI_PERIOD})`}
                              />
                            )}
                            <Legend />
                          </ComposedChart>
                        ) : (
                          <ComposedChart
                            data={chartData}
                            margin={{ top: 8, right: overlayRsi ? 52 : 8, bottom: 8, left: 8 }}
                          >
                            <XAxis
                              dataKey="date"
                              tick={{ fontSize: 10 }}
                              tickFormatter={(v) => (v && String(v).slice(5)) || v}
                            />
                            {/* Left axis: raw price for selected symbol */}
                            <YAxis
                              yAxisId="price"
                              tick={{ fontSize: 10 }}
                              domain={["auto", "auto"]}
                              tickFormatter={(v) => Number(v).toFixed(0)}
                            />
                            {/* Optional RSI axis on the right */}
                            {overlayRsi && (
                              <YAxis
                                yAxisId="rsi"
                                orientation="right"
                                domain={[0, 100]}
                                tick={{ fontSize: 9 }}
                                width={32}
                                tickFormatter={(v) => String(v)}
                              />
                            )}
                            <Tooltip
                              content={({ active, payload }) => {
                                if (!active || !payload?.length) return null;
                                const p = payload[0]?.payload as PricePoint | undefined;
                                if (!p) return null;
                                return (
                                  <div className="rounded-lg border border-zinc-200 bg-white p-2 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                                    <div className="font-medium">
                                      {(p.date && String(p.date).slice(0, 10)) || ""}
                                    </div>
                                    <div>
                                      {selectedSymbol}:{" "}
                                      {Number.isFinite(p.close)
                                        ? p.close.toFixed(2)
                                        : "—"}
                                    </div>
                                    {overlayRsi && p.rsi_14 != null && (
                                      <div>
                                        RSI({RSI_PERIOD}):{" "}
                                        <strong>{p.rsi_14.toFixed(1)}</strong>
                                      </div>
                                    )}
                                    <div>Volume: {p.volume.toLocaleString()}</div>
                                  </div>
                                );
                              }}
                            />
                            {overlayRsi && (
                              <>
                                <ReferenceLine
                                  yAxisId="rsi"
                                  y={70}
                                  stroke="#ef4444"
                                  strokeDasharray="2 2"
                                  strokeOpacity={0.7}
                                />
                                <ReferenceLine
                                  yAxisId="rsi"
                                  y={30}
                                  stroke="#22c55e"
                                  strokeDasharray="2 2"
                                  strokeOpacity={0.7}
                                />
                              </>
                            )}
                            {narrativeMarkers.map((n) => (
                              <ReferenceLine
                                key={n.date}
                                x={n.date}
                                stroke={STANCE_COLORS[n.stance] ?? STANCE_COLORS.neutral}
                                strokeDasharray="2 2"
                                strokeOpacity={0.8}
                              />
                            ))}
                            {/* Selected symbol raw price */}
                            <Line
                              yAxisId="price"
                              type="monotone"
                              dataKey="close"
                              stroke="#3b82f6"
                              strokeWidth={2}
                              dot={false}
                              name={selectedSymbol ?? "Price"}
                            />
                            {overlayRsi && (
                              <Line
                                type="monotone"
                                dataKey="rsi_14"
                                yAxisId="rsi"
                                stroke="#a855f7"
                                strokeWidth={1.5}
                                dot={false}
                                name={`RSI(${RSI_PERIOD})`}
                              />
                            )}
                            <Legend />
                          </ComposedChart>
                        )}
                      </ResponsiveContainer>
                    </div>
                    {overlaySpy && !spyQuoteLoading && (
                      <p className="mt-1 text-[10px] text-zinc-500 dark:text-zinc-400">
                        Both {selectedSymbol} and SPY are shown as normalized indexes (100 = start) on a single axis.
                      </p>
                    )}
                    <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <div className="h-24 w-full">
                        <p className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400">RSI({RSI_PERIOD})</p>
                        <ResponsiveContainer width="100%" height="80%">
                          <ComposedChart data={chartData} margin={{ top: 2, right: 4, bottom: 2, left: 4 }}>
                            <XAxis dataKey="date" hide />
                            <YAxis domain={[0, 100]} tick={{ fontSize: 9 }} width={28} />
                            <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="2 2" />
                            <ReferenceLine y={30} stroke="#22c55e" strokeDasharray="2 2" />
                            <Area type="monotone" dataKey="rsi_14" fill="#a855f7" fillOpacity={0.3} stroke="#a855f7" strokeWidth={1} name="RSI" />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="h-24 w-full">
                        <p className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400">
                          MACD ({MACD_FAST}, {MACD_SLOW}, {MACD_SIGNAL})
                        </p>
                        <ResponsiveContainer width="100%" height="80%">
                          <ComposedChart data={chartData} margin={{ top: 2, right: 4, bottom: 2, left: 4 }}>
                            <XAxis dataKey="date" hide />
                            <YAxis tick={{ fontSize: 9 }} width={36} />
                            <Bar dataKey="macd_hist" fill="#94a3b8" radius={0} name="Hist" />
                            <Line
                              type="monotone"
                              dataKey="macd_line"
                              stroke="#3b82f6"
                              strokeWidth={1}
                              dot={false}
                              name={`MACD (${MACD_FAST}, ${MACD_SLOW}, ${MACD_SIGNAL})`}
                            />
                            <Line
                              type="monotone"
                              dataKey="macd_signal"
                              stroke="#f59e0b"
                              strokeWidth={1}
                              strokeDasharray="2 2"
                              dot={false}
                              name="Signal"
                            />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                    {narrativeOverlay && narrativeMarkers.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-3 text-[10px]">
                        <span style={{ color: STANCE_COLORS.bullish }}>Bullish</span>
                        <span style={{ color: STANCE_COLORS.bearish }}>Bearish</span>
                        <span style={{ color: STANCE_COLORS.mixed }}>Mixed</span>
                        <span style={{ color: STANCE_COLORS.neutral }}>Neutral</span>
                        <span className="text-zinc-500">(dashed lines = narrative dates)</span>
                      </div>
                    )}
                    {histPeLoading && <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">Loading historical P/E…</p>}
                    {!histPeLoading && histPe && (histPe.series?.length ?? 0) > 0 && (
                      <div className="mt-4 border-t border-zinc-200 pt-4 dark:border-zinc-700">
                        <p className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400">Historical trailing P/E (close ÷ trailing 4Q EPS)</p>
                        <div className="mt-2 h-32 w-full">
                          <ResponsiveContainer width="100%" height="100%">
                            <ComposedChart data={histPe.series} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                              <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(v) => (v && String(v).slice(5)) || v} />
                              <YAxis tick={{ fontSize: 9 }} width={32} domain={["auto", "auto"]} />
                              <Tooltip content={({ active, payload }) => (active && payload?.[0] ? <div className="rounded border bg-white p-2 text-xs shadow dark:bg-zinc-900">{payload[0].payload.date}: P/E {Number(payload[0].value).toFixed(1)}</div> : null)} />
                              <Line type="monotone" dataKey="pe" stroke="#8b5cf6" strokeWidth={2} dot={false} name="P/E" />
                            </ComposedChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">{quote?.message ?? "No price data for this symbol."}</p>
                )}
              </>
            )}
          </div>
        </>
      )}
    </section>
  );
}
