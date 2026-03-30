"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

function todayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function minIso(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 15);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function ThemePageRangeControls({
  themeId,
  months,
  chartStartIso,
}: {
  themeId: string;
  months: number;
  chartStartIso: string | null;
}) {
  const router = useRouter();
  const base = `/themes/${themeId}`;
  const [draft, setDraft] = useState(chartStartIso ?? "");

  useEffect(() => {
    setDraft(chartStartIso ?? "");
  }, [chartStartIso]);

  const presetActive6 = chartStartIso == null && months === 6;
  const presetActive12 = chartStartIso == null && months === 12;

  const applyHref = useMemo(() => {
    if (!draft || !/^\d{4}-\d{2}-\d{2}$/.test(draft)) return null;
    return `${base}?start=${encodeURIComponent(draft)}`;
  }, [base, draft]);

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span>Range:</span>
        <Link
          href={`${base}?months=6`}
          className={presetActive6 ? "font-medium text-zinc-900 dark:text-zinc-100" : "hover:underline"}
        >
          6 months
        </Link>
        <Link
          href={`${base}?months=12`}
          className={presetActive12 ? "font-medium text-zinc-900 dark:text-zinc-100" : "hover:underline"}
        >
          1 year
        </Link>
        <span className="text-zinc-300 dark:text-zinc-600">·</span>
        <label className="flex flex-wrap items-center gap-1.5">
          <span className="text-zinc-500 dark:text-zinc-400">From</span>
          <input
            type="date"
            value={draft}
            min={minIso()}
            max={todayIso()}
            onChange={(e) => setDraft(e.target.value)}
            className="rounded border border-zinc-300 bg-white px-2 py-1 font-mono text-[11px] text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
          <button
            type="button"
            disabled={!applyHref}
            onClick={() => applyHref && router.push(applyHref)}
            className="rounded border border-zinc-300 bg-zinc-50 px-2 py-1 text-[11px] font-medium text-zinc-700 hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
          >
            Apply
          </button>
        </label>
        {chartStartIso ? (
          <Link
            href={`${base}?months=${months}`}
            className="text-[11px] text-zinc-500 hover:underline dark:text-zinc-400"
          >
            Use preset range
          </Link>
        ) : null}
      </div>
      {chartStartIso ? (
        <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
          Custom start: <span className="font-mono text-zinc-700 dark:text-zinc-300">{chartStartIso}</span>
        </div>
      ) : null}
    </div>
  );
}
