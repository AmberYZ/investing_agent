"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function ThemeNotes({ themeId }: { themeId: string }) {
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const fetchNotes = useCallback(() => {
    setLoading(true);
    fetch(`${API_BASE}/themes/${themeId}/notes`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : { content: null }))
      .then((data: { content?: string | null }) => {
        const text = data?.content ?? "";
        setContent(text);
        setSaved(text);
      })
      .catch(() => {
        setContent("");
        setSaved("");
      })
      .finally(() => setLoading(false));
  }, [themeId]);

  useEffect(() => {
    fetchNotes();
  }, [fetchNotes]);

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

  const save = useCallback(() => {
    if (saving || content === saved) return;
    setSaving(true);
    fetch(`${API_BASE}/themes/${themeId}/notes`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: content || null }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { content?: string | null } | null) => {
        if (data) {
          const text = data.content ?? "";
          setSaved(text);
          setContent(text);
        }
      })
      .finally(() => setSaving(false));
  }, [themeId, content, saved, saving]);

  if (loading) {
    return (
      <button
        type="button"
        disabled
        className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-xs font-medium text-zinc-400 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-500"
      >
        Notes…
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
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
        Notes
        {content.trim().length > 0 && (
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" title="Has notes" aria-hidden />
        )}
      </button>
      {expanded && (
        <div className="absolute right-0 top-full z-20 mt-1.5 w-80 rounded-xl border border-zinc-200 bg-white p-3 shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          <div className="text-xs font-medium text-zinc-700 dark:text-zinc-300">Your notes</div>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onBlur={save}
            placeholder="Add notes…"
            rows={3}
            className="mt-2 w-full resize-y rounded-lg border border-zinc-300 bg-white px-2.5 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={save}
              disabled={saving || content === saved}
              className="rounded border border-zinc-300 bg-zinc-800 px-2 py-1 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-100"
            >
              {saving ? "Saving…" : content === saved ? "Saved" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
