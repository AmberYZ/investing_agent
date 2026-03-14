"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function ThemeTrackItems({ themeId }: { themeId: string }) {
  const [items, setItems] = useState<string[]>([]);
  const [rawInput, setRawInput] = useState("");
  const [savedItems, setSavedItems] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const fetchTrackItems = useCallback(() => {
    setLoading(true);
    fetch(`${API_BASE}/themes/${themeId}/track-items`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : { items: [] }))
      .then((data: { items?: string[] }) => {
        const list = data?.items ?? [];
        setItems(list);
        setSavedItems(list);
        setRawInput(list.join("\n"));
      })
      .catch(() => {
        setItems([]);
        setSavedItems([]);
        setRawInput("");
      })
      .finally(() => setLoading(false));
  }, [themeId]);

  useEffect(() => {
    fetchTrackItems();
  }, [fetchTrackItems]);

  useEffect(() => {
    if (!expanded) return;
    function handleClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    }
    const t = setTimeout(() => document.addEventListener("mousedown", handleClickOutside), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [expanded]);

  /** Parse raw input into bullet items: split by newlines/commas, trim, filter empty. */
  const parseToItems = useCallback((raw: string): string[] => {
    return raw
      .replace(/,/g, "\n")
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }, []);

  const save = useCallback(() => {
    const newItems = parseToItems(rawInput);
    if (saving || JSON.stringify(newItems) === JSON.stringify(savedItems)) return;
    setSaving(true);
    fetch(`${API_BASE}/themes/${themeId}/track-items`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: newItems }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { items?: string[] } | null) => {
        if (data) {
          const list = data.items ?? [];
          setItems(list);
          setSavedItems(list);
          setRawInput(list.join("\n"));
        }
      })
      .finally(() => setSaving(false));
  }, [themeId, rawInput, savedItems, saving, parseToItems]);

  if (loading) {
    return (
      <button
        type="button"
        disabled
        className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-xs font-medium text-zinc-400 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-500"
      >
        Track…
      </button>
    );
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className={`inline-flex items-center gap-1.5 rounded border px-2 py-1.5 text-xs font-medium transition-colors ${
          expanded
            ? "border-zinc-400 bg-zinc-100 text-zinc-900 dark:border-zinc-500 dark:bg-zinc-700 dark:text-zinc-100"
            : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
        }`}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2m-6 9l2 2 4-4" />
        </svg>
        Track
        {items.length > 0 && (
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" title={`${items.length} item(s) to track`} aria-hidden />
        )}
      </button>
      {expanded && (
        <div className="absolute right-0 top-full z-20 mt-1.5 w-[min(90vw,28rem)] rounded-xl border border-zinc-200 bg-white p-4 shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          <div className="text-xs font-medium text-zinc-700 dark:text-zinc-300">Things to track</div>
          <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
            One per line or comma-separated. E.g. Q3 earnings, FDA decision, key data point.
          </p>
          <textarea
            value={rawInput}
            onChange={(e) => setRawInput(e.target.value)}
            onBlur={save}
            placeholder="Q3 earnings&#10;FDA decision for drug X&#10;GitHub stars for repo Y"
            rows={8}
            className="mt-2 min-h-[160px] w-full resize-y rounded-lg border border-zinc-300 bg-white px-3 py-2.5 text-sm leading-relaxed text-zinc-900 placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-200 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500 dark:focus:border-zinc-500 dark:focus:ring-zinc-700"
          />
          <div className="mt-3 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={save}
              disabled={saving || JSON.stringify(parseToItems(rawInput)) === JSON.stringify(savedItems)}
              className="rounded border border-zinc-300 bg-zinc-800 px-2 py-1 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-100"
            >
              {saving ? "Saving…" : JSON.stringify(parseToItems(rawInput)) === JSON.stringify(savedItems) ? "Saved" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
