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

type ThemeInstrument = {
  id: number;
  theme_id: number;
  symbol: string;
  display_name?: string | null;
  type: string;
  source: string;
};

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
  next_fy_eps_estimate?: number | null;
  eps_revision_up_30d?: number | null;
  eps_revision_down_30d?: number | null;
  eps_growth_pct?: number | null;
  message?: string | null;
};

/** Read quote from sessionStorage if present and not expired. Survives page refresh. */
function getQuoteFromSessionStorage(cacheKey: string): InstrumentQuote | null {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  try {
    const raw = window.sessionStorage.getItem(`${QUOTE_STORAGE_KEY}:${cacheKey}`);
    if (!raw) return null;
    const { data, fetchedAt } = JSON.parse(raw) as { data: InstrumentQuote; fetchedAt: number };
    if (!data?.prices || Date.now() - fetchedAt >= PRICE_CACHE_TTL_MS) return null;
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
      JSON.stringify({ data, fetchedAt: Date.now() })
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
  const [overlaySpy, setOverlaySpy] = useState(false);
  const [spyQuote, setSpyQuote] = useState<InstrumentQuote | null>(null);
  const [spyQuoteLoading, setSpyQuoteLoading] = useState(false);
  const [overlayRsi, setOverlayRsi] = useState(true);

  const quoteCache = useRef<Map<string, { data: InstrumentQuote; fetchedAt: number }>>(new Map());

  const fetchInstruments = useCallback(async () => {
    const res = await fetch(`${API_BASE}/themes/${themeId}/instruments`, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      setInstruments(Array.isArray(data) ? data : []);
    }
  }, [themeId]);

  useEffect(() => {
    setLoading(true);
    fetchInstruments().finally(() => setLoading(false));
  }, [fetchInstruments]);

  // Debounced Alpha Vantage symbol search when user types in the Symbol box
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
    if (viewMode === "single" && instruments.length > 0 && !selectedSymbol) {
      setSelectedSymbol(instruments[0].symbol);
    }
    if (viewMode === "basket" && instruments.length === 0) {
      setSelectedSymbol(null);
      setQuote(null);
    }
  }, [viewMode, instruments, selectedSymbol]);

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

  // Fetch SPY prices when overlay is enabled (same Alpha Vantage endpoint, ticker SPY)
  useEffect(() => {
    if (!overlaySpy || viewMode !== "single") {
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

  // When overlay SPY: merged data with % return from first common date (0% = start)
  type ChartPointWithSpy = PricePoint & { closePctReturn?: number; spyPctReturn?: number; spyClose?: number };
  const chartDataWithSpy = useMemo((): ChartPointWithSpy[] => {
    if (!overlaySpy || chartData.length === 0 || !spyQuote?.prices?.length) return chartData as ChartPointWithSpy[];
    const spyByDate = new Map<string, number>();
    const spyDatesSorted: string[] = [];
    for (const p of spyQuote.prices) {
      const d = (p.date && String(p.date)).slice(0, 10);
      spyByDate.set(d, p.close);
      spyDatesSorted.push(d);
    }
    spyDatesSorted.sort();
    const firstChartDate = (chartData[0].date && String(chartData[0].date)).slice(0, 10);
    // Forward-fill: use first SPY date on or after first chart date so we have a value for the start
    let lastSpyClose: number | null = null;
    const firstSpyDateOnOrAfter = spyDatesSorted.find((sd) => sd >= firstChartDate);
    if (firstSpyDateOnOrAfter != null) lastSpyClose = spyByDate.get(firstSpyDateOnOrAfter) ?? null;
    if (lastSpyClose == null && spyDatesSorted.length > 0)
      lastSpyClose = spyByDate.get(spyDatesSorted[spyDatesSorted.length - 1]) ?? null;

    const merged: ChartPointWithSpy[] = [];
    let baseClose: number | null = null;
    let baseSpy: number | null = null;
    for (const p of chartData) {
      const d = (p.date && String(p.date)).slice(0, 10);
      const spyClose = spyByDate.get(d) ?? lastSpyClose;
      if (spyClose != null) lastSpyClose = spyClose;
      if (baseClose == null && spyClose != null) {
        baseClose = p.close;
        baseSpy = spyClose;
      }
      const closePctReturn = baseClose != null ? (p.close / baseClose - 1) * 100 : undefined;
      const spyPctReturn = baseSpy != null && spyClose != null ? (spyClose / baseSpy - 1) * 100 : undefined;
      merged.push({ ...p, closePctReturn, spyPctReturn, spyClose: spyClose ?? undefined });
    }
    return merged;
  }, [overlaySpy, chartData, spyQuote?.prices]);

  const hasOverlayData = overlaySpy && spyQuote?.prices?.length && (chartDataWithSpy as ChartPointWithSpy[]).some((p) => p.closePctReturn != null);

  // When SPY overlay is on and we have % return data, Y domain from those series only
  const priceChartYDomain = useMemo((): [number, number] | "auto" => {
    if (!hasOverlayData || chartDataWithSpy.length === 0) return "auto";
    let min = Infinity;
    let max = -Infinity;
    for (const p of chartDataWithSpy as ChartPointWithSpy[]) {
      if (p.closePctReturn != null) { min = Math.min(min, p.closePctReturn); max = Math.max(max, p.closePctReturn); }
      if (p.spyPctReturn != null) { min = Math.min(min, p.spyPctReturn); max = Math.max(max, p.spyPctReturn); }
    }
    if (min === Infinity || max === -Infinity) return "auto";
    const pad = Math.max((max - min) * 0.05, 0.5);
    return [Math.floor(min - pad), Math.ceil(max + pad)];
  }, [hasOverlayData, chartDataWithSpy]);

  const basketQuotes = useRef<Map<string, InstrumentQuote>>(new Map());
  const [basketLoading, setBasketLoading] = useState(false);
  const [basketSeries, setBasketSeries] = useState<{ date: string; value: number }[]>([]);

  useEffect(() => {
    if (viewMode !== "basket" || instruments.length === 0) {
      setBasketSeries([]);
      return;
    }
    const loadAll = async () => {
      setBasketLoading(true);
      const map = new Map<string, InstrumentQuote>();
      for (const inst of instruments) {
        const q = await loadQuote(inst.symbol);
        if (q?.prices?.length) map.set(inst.symbol, q);
      }
      basketQuotes.current = map;
      setBasketSeries(buildBasketSeries(map));
      setBasketLoading(false);
    };
    loadAll();
  }, [viewMode, instruments, loadQuote]);

  const hasInstruments = instruments.length > 0 || suggestions.length > 0 || fromDocSuggestions.length > 0;

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
            {instruments.map((inst) => (
              <button
                key={inst.id}
                type="button"
                onClick={() => handleTickerClick(inst.symbol)}
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition hover:opacity-90 ${SOURCE_STYLES[inst.source] ?? SOURCE_STYLES.manual} ${viewMode === "single" && selectedSymbol === inst.symbol ? "ring-2 ring-zinc-600 dark:ring-zinc-400" : ""}`}
                title={`${inst.symbol} (${SOURCE_LABELS[inst.source] ?? inst.source})`}
              >
                <span>{inst.symbol}</span>
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
            ))}
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
                <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Basket performance (normalized avg)</h3>
                {basketLoading ? (
                  <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
                ) : basketSeries.length > 0 ? (
                  <div className="mt-2 h-56 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={basketSeries} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v) => (v && String(v).slice(5)) || v} />
                        <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} tickFormatter={(v) => Number(v).toFixed(0)} />
                        <Tooltip content={({ active, payload }) => (active && payload?.[0] ? <div className="rounded border bg-white p-2 text-xs shadow dark:bg-zinc-900">{payload[0].payload.date}: {Number(payload[0].value).toFixed(1)}</div> : null)} />
                        <Line type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={2} dot={false} name="Basket (100 = start)" />
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
                    <div className="flex flex-wrap gap-4 text-xs text-zinc-600 dark:text-zinc-400">
                      {quote.trailing_pe != null && <span>Trailing P/E: <strong>{quote.trailing_pe}</strong></span>}
                      {quote.forward_pe != null && <span>Forward P/E: <strong>{quote.forward_pe}</strong></span>}
                      <span>PEG: <strong>{quote.peg_ratio != null ? quote.peg_ratio : "—"}</strong></span>
                      {quote.ev_to_ebitda != null && <span>EV/EBITDA: <strong>{quote.ev_to_ebitda}</strong></span>}
                      {quote.eps_growth_pct != null && <span>EPS growth (Fwd vs Trail 12M): <strong>{quote.eps_growth_pct}%</strong></span>}
                      {quote.next_fy_eps_estimate != null && <span>Next FY EPS: <strong>{quote.next_fy_eps_estimate}</strong></span>}
                      {quote.eps_revision_up_30d != null && <span className="text-emerald-600 dark:text-emerald-400">Rev ↑ 30d: <strong>{quote.eps_revision_up_30d}</strong></span>}
                      {quote.eps_revision_down_30d != null && <span className="text-red-600 dark:text-red-400">Rev ↓ 30d: <strong>{quote.eps_revision_down_30d}</strong></span>}
                      {histPe?.current_pe != null && <span>Current P/E (trailing): <strong>{histPe.current_pe}</strong></span>}
                      {histPe?.pe_percentile != null && <span>P/E percentile (hist.): <strong>{histPe.pe_percentile}%</strong></span>}
                    </div>
                  )}
                </div>
                {quote?.message && <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">{quote.message}</p>}
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                    <input type="checkbox" checked={overlayRsi} onChange={(e) => setOverlayRsi(e.target.checked)} className="rounded border-zinc-300" />
                    Overlay RSI (right axis)
                  </label>
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                    <input type="checkbox" checked={overlaySpy} onChange={(e) => setOverlaySpy(e.target.checked)} className="rounded border-zinc-300" />
                    Overlay SPY (S&P 500)
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
                        <ComposedChart data={chartDataWithSpy} margin={{ top: 8, right: overlayRsi ? 44 : 8, bottom: 8, left: 8 }}>
                          <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v) => (v && String(v).slice(5)) || v} />
                          {/* Left axis (default): price or % return; no yAxisId so Lines without yAxisId bind here */}
                          <YAxis
                            tick={{ fontSize: 10 }}
                            domain={priceChartYDomain === "auto" ? ["auto", "auto"] : priceChartYDomain}
                            tickFormatter={(v) => (hasOverlayData ? `${Number(v).toFixed(1)}%` : Number(v).toFixed(0))}
                          />
                          {overlayRsi && (
                            <YAxis
                              yAxisId="rsi"
                              orientation="right"
                              domain={[0, 100]}
                              tick={{ fontSize: 9 }}
                              width={36}
                              tickFormatter={(v) => String(v)}
                            />
                          )}
                          <Tooltip
                            content={({ active, payload }) => {
                              if (!active || !payload?.length) return null;
                              const p = payload[0]?.payload as ChartPointWithSpy | undefined;
                              if (!p) return null;
                              if (hasOverlayData && p.closePctReturn != null) {
                                return (
                                  <div className="rounded-lg border border-zinc-200 bg-white p-2 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                                    <div className="font-medium">{p.date}</div>
                                    <div>{selectedSymbol}: {p.closePctReturn >= 0 ? "+" : ""}{p.closePctReturn.toFixed(2)}% {p.close != null && <span className="text-zinc-500">(${p.close})</span>}</div>
                                    {p.spyPctReturn != null && (
                                      <div>SPY: {p.spyPctReturn >= 0 ? "+" : ""}{p.spyPctReturn.toFixed(2)}% {p.spyClose != null && <span className="text-zinc-500">(${p.spyClose.toFixed(2)})</span>}</div>
                                    )}
                                    {overlayRsi && p.rsi_14 != null && <div>RSI(14): <strong>{p.rsi_14.toFixed(1)}</strong></div>}
                                  </div>
                                );
                              }
                              return (
                                <div className="rounded-lg border border-zinc-200 bg-white p-2 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
                                  <div className="font-medium">{p.date}</div>
                                  <div>Close: {p.close}</div>
                                  {overlayRsi && p.rsi_14 != null && <div>RSI(14): <strong>{p.rsi_14.toFixed(1)}</strong></div>}
                                  <div>Volume: {p.volume.toLocaleString()}</div>
                                </div>
                              );
                            }}
                          />
                          {hasOverlayData ? (
                            <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="2 2" strokeOpacity={0.6} />
                          ) : null}
                          {overlayRsi && (
                            <>
                              <ReferenceLine yAxisId="rsi" y={70} stroke="#ef4444" strokeDasharray="2 2" strokeOpacity={0.7} />
                              <ReferenceLine yAxisId="rsi" y={30} stroke="#22c55e" strokeDasharray="2 2" strokeOpacity={0.7} />
                            </>
                          )}
                          {narrativeMarkers.map((n) => (
                            <ReferenceLine key={n.date} x={n.date} stroke={STANCE_COLORS[n.stance] ?? STANCE_COLORS.neutral} strokeDasharray="2 2" strokeOpacity={0.8} />
                          ))}
                          {hasOverlayData ? (
                            <>
                              <Line type="monotone" dataKey="closePctReturn" stroke="#3b82f6" strokeWidth={2} dot={false} name={selectedSymbol ?? "Price"} />
                              <Line type="monotone" dataKey="spyPctReturn" stroke="#f59e0b" strokeWidth={2} strokeDasharray="4 2" dot={false} name="SPY" />
                            </>
                          ) : (
                            <Line type="monotone" dataKey="close" stroke="#3b82f6" strokeWidth={2} dot={false} name="Price" />
                          )}
                          {overlayRsi && (
                            <Line type="monotone" dataKey="rsi_14" yAxisId="rsi" stroke="#a855f7" strokeWidth={1.5} dot={false} name="RSI(14)" />
                          )}
                          <Legend />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </div>
                    {overlaySpy && (
                      <p className="mt-1 text-[10px] text-zinc-500 dark:text-zinc-400">
                        {spyQuoteLoading ? "Loading SPY…" : hasOverlayData ? "Cumulative % return from first common date. SPY data from Alpha Vantage." : spyQuote?.prices?.length ? "Aligning dates…" : "No SPY data yet."}
                      </p>
                    )}
                    <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <div className="h-24 w-full">
                        <p className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400">RSI(14)</p>
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
                        <p className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400">MACD</p>
                        <ResponsiveContainer width="100%" height="80%">
                          <ComposedChart data={chartData} margin={{ top: 2, right: 4, bottom: 2, left: 4 }}>
                            <XAxis dataKey="date" hide />
                            <YAxis tick={{ fontSize: 9 }} width={36} />
                            <Bar dataKey="macd_hist" fill="#94a3b8" radius={0} name="Hist" />
                            <Line type="monotone" dataKey="macd_line" stroke="#3b82f6" strokeWidth={1} dot={false} name="MACD" />
                            <Line type="monotone" dataKey="macd_signal" stroke="#f59e0b" strokeWidth={1} strokeDasharray="2 2" dot={false} name="Signal" />
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
