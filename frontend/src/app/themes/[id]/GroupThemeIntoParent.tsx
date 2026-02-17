"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type ThemeOption = { id: number; canonical_label: string };

export function GroupThemeIntoParent({
  themeId,
  themeLabel,
  parentThemeId,
  parentThemeLabel,
  childThemeIds = [],
}: {
  themeId: number;
  themeLabel: string;
  parentThemeId?: number | null;
  parentThemeLabel?: string | null;
  childThemeIds?: number[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [themes, setThemes] = useState<ThemeOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(parentThemeId ?? null);

  const loadThemes = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/themes?sort=label`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data: ThemeOption[]) => {
        const list = Array.isArray(data) ? data : [];
        const exclude = new Set([themeId, ...childThemeIds]);
        setThemes(list.filter((t) => !exclude.has(t.id)));
      })
      .catch(() => {
        setError("Failed to load themes");
        setThemes([]);
      })
      .finally(() => setLoading(false));
  }, [themeId, childThemeIds]);

  useEffect(() => {
    if (open) {
      loadThemes();
      setSelectedId(parentThemeId ?? null);
    }
  }, [open, loadThemes, parentThemeId]);

  const submit = useCallback(() => {
    setSaving(true);
    setError(null);
    fetch(`${API_BASE}/themes/${themeId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent_theme_id: selectedId }),
    })
      .then((res) => {
        if (!res.ok) {
          return res.json().then((b: { detail?: string }) => {
            throw new Error(typeof b.detail === "string" ? b.detail : "Failed to update");
          });
        }
        return res.json();
      })
      .then(() => {
        setOpen(false);
        router.refresh();
      })
      .catch((err: Error) => {
        setError(err.message || "Failed to update");
      })
      .finally(() => setSaving(false));
  }, [themeId, selectedId, router]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
      >
        {parentThemeId ? `In: ${parentThemeLabel ?? "…"}` : "Group into bigger theme"}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div
            className="max-h-[80vh] w-full max-w-md overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900"
            role="dialog"
            aria-modal="true"
            aria-labelledby="group-theme-title"
          >
            <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
              <h2 id="group-theme-title" className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                Group theme into bigger theme
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                &ldquo;{themeLabel}&rdquo; will be a sub-theme of the selected parent. In My Basket, the parent will show all narratives and tickers from its children.
              </p>
            </div>
            <div className="max-h-[50vh] overflow-y-auto px-4 py-3">
              {loading && (
                <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading themes…</p>
              )}
              {error && (
                <p className="mb-2 text-sm text-red-600 dark:text-red-400">{error}</p>
              )}
              {!loading && (
                <>
                  <label className="mb-2 block">
                    <input
                      type="radio"
                      name="parent"
                      checked={selectedId === null}
                      onChange={() => setSelectedId(null)}
                      className="mr-2"
                    />
                    <span className="text-sm">Ungroup (no parent)</span>
                  </label>
                  {themes.map((t) => (
                    <label key={t.id} className="mb-1 flex items-center">
                      <input
                        type="radio"
                        name="parent"
                        checked={selectedId === t.id}
                        onChange={() => setSelectedId(t.id)}
                        className="mr-2"
                      />
                      <span className="text-sm">{t.canonical_label}</span>
                    </label>
                  ))}
                </>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-zinc-200 px-4 py-3 dark:border-zinc-700">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={saving || loading}
                className="rounded-lg bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
