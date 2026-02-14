"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function ThemeNotes({ themeId }: { themeId: string }) {
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

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
      <section className="mt-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">Notes</h2>
        <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
      </section>
    );
  }

  return (
    <section className="mt-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">Notes</h2>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        Your notes for this theme. Saved automatically on blur or when you click Save.
      </p>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onBlur={save}
        placeholder="Add notes…"
        rows={4}
        className="mt-3 w-full resize-y rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-500"
      />
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving || content === saved}
          className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {saving ? "Saving…" : content === saved ? "Saved" : "Save"}
        </button>
      </div>
    </section>
  );
}
