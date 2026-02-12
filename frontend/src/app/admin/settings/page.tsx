"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type PromptState = {
  prompt_template: string;
  hint: string;
};

export default function SettingsPage() {
  const [prompt, setPrompt] = useState<PromptState | null>(null);
  const [edited, setEdited] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/extraction-prompt`, { cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load: ${res.status}`);
      const data = await res.json();
      setPrompt(data);
      setEdited(data.prompt_template ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load prompt");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch(`${API_BASE}/settings/extraction-prompt`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_template: edited }),
      });
      if (!res.ok) throw new Error(`Failed to save: ${res.status}`);
      const data = await res.json();
      setPrompt(data);
      setEdited(data.prompt_template ?? "");
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-zinc-500 dark:text-zinc-400">Loading…</p>;
  }

  return (
    <>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Extraction prompt</h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Edit the prompt used by the LLM to extract themes and narratives from documents. Use{" "}
          <code className="rounded bg-zinc-200 px-1 dark:bg-zinc-800">{"{{schema}}"}</code> and{" "}
          <code className="rounded bg-zinc-200 px-1 dark:bg-zinc-800">{"{{text}}"}</code> as placeholders.
        </p>
      </div>

        {prompt?.hint && (
          <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
            {prompt.hint}
          </p>
        )}

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
            {error}
          </div>
        )}

        {saved && (
          <div className="mb-4 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark:border-green-900 dark:bg-green-950/50 dark:text-green-200">
            Prompt saved. Future ingest jobs will use the new prompt.
          </div>
        )}

        <textarea
          className="mb-4 w-full rounded-xl border border-zinc-200 bg-white p-4 font-mono text-sm leading-relaxed dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
          rows={18}
          value={edited}
          onChange={(e) => setEdited(e.target.value)}
          placeholder="Prompt template with {{schema}} and {{text}}..."
          spellCheck={false}
        />

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={save}
            disabled={saving || edited === (prompt?.prompt_template ?? "")}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            {saving ? "Saving…" : "Save prompt"}
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
    </>
  );
}
