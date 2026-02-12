"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function RequeueErrorIngestButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setMessage(null);
    try {
      // API route runs the backend script directly so it works without the backend HTTP server
      const res = await fetch("/api/admin/ingest-jobs/requeue", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = Array.isArray(data?.detail) ? data.detail[0]?.msg : data?.detail;
        setMessage(typeof detail === "string" ? detail : `Error ${res.status}`);
        return;
      }
      const count = data?.requeued ?? 0;
      setMessage(count ? `Requeued ${count} job(s).` : "No error jobs to requeue.");
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
        className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-50 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200 dark:hover:bg-emerald-900"
      >
        {loading ? "Requeuing…" : "Requeue cancelled & error jobs"}
      </button>
      {message && (
        <span className="text-xs text-zinc-600 dark:text-zinc-400">{message}</span>
      )}
    </div>
  );
}
