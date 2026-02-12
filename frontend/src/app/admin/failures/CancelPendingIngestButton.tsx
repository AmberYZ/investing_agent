"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function CancelPendingIngestButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleClick() {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch(`${apiBase}/admin/ingest-jobs/cancel-all`, {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setMessage(data?.detail ?? `Error ${res.status}`);
        return;
      }
      setMessage(data?.cancelled != null ? `Cancelled ${data.cancelled} job(s).` : "Done.");
      window.dispatchEvent(new Event("ingest-jobs-changed"));
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200 dark:hover:bg-amber-900"
      >
        {loading ? "Cancelling…" : "Cancel all pending ingest jobs"}
      </button>
      {message && (
        <span className="text-xs text-zinc-600 dark:text-zinc-400">{message}</span>
      )}
    </div>
  );
}
