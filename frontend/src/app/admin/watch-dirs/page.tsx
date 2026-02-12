"use client";

import { useCallback, useEffect, useState } from "react";

// Use relative /api so the Next.js API route is used (it proxies to backend, or falls back to file if backend returns 404)
const API_BASE =
  typeof window !== "undefined" ? "" : process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const WATCH_DIRS_URL = `${API_BASE}/api/settings/watch-dirs`;

type WatchDirEntry = { path: string; nickname: string; last_file_at?: string | null };

function defaultEntry(): WatchDirEntry {
  return { path: "", nickname: "" };
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

export default function WatchDirsPage() {
  const [formDirs, setFormDirs] = useState<WatchDirEntry[]>([]);
  const [serverDirs, setServerDirs] = useState<WatchDirEntry[]>([]);
  const [configUpdatedAt, setConfigUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(WATCH_DIRS_URL, { cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load: ${res.status}`);
      const data = await res.json();
      const raw = Array.isArray(data?.watch_dirs) ? data.watch_dirs : [];
      const dirs: WatchDirEntry[] = raw.map((e: { path?: string; nickname?: string; last_file_at?: string | null } | string) =>
        typeof e === "string"
          ? { path: e, nickname: "", last_file_at: null }
          : { path: e?.path ?? "", nickname: e?.nickname ?? "", last_file_at: e?.last_file_at ?? null }
      );
      setServerDirs(dirs);
      setFormDirs(dirs.length > 0 ? dirs.map((d) => ({ path: d.path, nickname: d.nickname })) : [defaultEntry()]);
      setConfigUpdatedAt(data?.config_updated_at ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load watch directories");
      setServerDirs([]);
      setFormDirs([defaultEntry()]);
      setConfigUpdatedAt(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const updateEntry = (index: number, field: "path" | "nickname", value: string) => {
    setFormDirs((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const addDir = () => {
    setFormDirs((prev) => [...prev, defaultEntry()]);
  };

  const removeDir = (index: number) => {
    setFormDirs((prev) => prev.filter((_, i) => i !== index));
  };

  const save = async () => {
    const toSave = formDirs
      .map((e) => ({ path: e.path.trim(), nickname: (e.nickname ?? "").trim() }))
      .filter((e) => e.path.length > 0);
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch(WATCH_DIRS_URL, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ watch_dirs: toSave }),
      });
      if (!res.ok) throw new Error(`Failed to save: ${res.status}`);
      const data = await res.json();
      const raw = Array.isArray(data?.watch_dirs) ? data.watch_dirs : [];
      const dirs: WatchDirEntry[] = raw.map((e: { path?: string; nickname?: string; last_file_at?: string | null }) => ({
        path: e?.path ?? "",
        nickname: e?.nickname ?? "",
        last_file_at: e?.last_file_at ?? null,
      }));
      setServerDirs(dirs);
      setFormDirs(dirs.length > 0 ? dirs.map((d) => ({ path: d.path, nickname: d.nickname })) : [defaultEntry()]);
      setConfigUpdatedAt(data?.config_updated_at ?? null);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const hasValidEntry = formDirs.some((e) => e.path.trim().length > 0);

  if (loading) {
    return <p className="text-zinc-500 dark:text-zinc-400">Loading…</p>;
  }

  return (
    <>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Watch directories</h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          These are the directories the ingest agent is watching for new PDFs. Save changes below; the watcher picks up the new list within a few seconds. Use a nickname to label each directory.
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
          {error}
        </div>
      )}

      {saved && (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark:border-green-900 dark:bg-green-950/50 dark:text-green-200">
          Watch directories saved. The ingest client will pick up the new list within a few seconds (no restart needed).
        </div>
      )}

      {/* Authoritative list: what is currently being watched (from server) */}
      <div className="mb-8 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">
          Currently watched ({serverDirs.length})
        </h2>
        {configUpdatedAt && (
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Config last saved: {formatDateTime(configUpdatedAt)}
          </p>
        )}
        {serverDirs.length === 0 ? (
          <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">
            No directories configured. Add paths below and click Save. The watcher will use the default folder until then.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {serverDirs.map((e, idx) => (
              <li
                key={idx}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-zinc-100 bg-zinc-50/50 py-2.5 px-3 text-sm dark:border-zinc-800 dark:bg-zinc-900/50"
              >
                <span className="font-medium text-zinc-800 dark:text-zinc-200 min-w-0">
                  {e.nickname.trim() || "(no nickname)"}
                </span>
                <span className="truncate font-mono text-zinc-600 dark:text-zinc-400" title={e.path}>
                  {e.path}
                </span>
                <span className="text-zinc-500 dark:text-zinc-400 text-xs shrink-0">
                  Last file: {formatDateTime(e.last_file_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Edit form */}
      <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">Edit directories</h2>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          Path is required; nickname is optional. Save to apply; the watcher will use the new list within a few seconds.
        </p>
        <div className="mt-4 space-y-4">
          {formDirs.map((entry, index) => (
            <div key={index} className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
              <input
                type="text"
                value={entry.nickname}
                onChange={(e) => updateEntry(index, "nickname", e.target.value)}
                placeholder="Nickname (e.g. WeChat downloads)"
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm sm:w-48 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
              <input
                type="text"
                value={entry.path}
                onChange={(e) => updateEntry(index, "path", e.target.value)}
                placeholder="/path/to/folder"
                className="min-w-0 flex-1 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
              <button
                type="button"
                onClick={() => removeDir(index)}
                disabled={formDirs.length <= 1}
                className="rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={addDir}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Add directory
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving || !hasValidEntry}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Reload
          </button>
        </div>
      </div>
    </>
  );
}
