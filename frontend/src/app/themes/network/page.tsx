import Link from "next/link";
import { ThemeNetworkClient } from "./ThemeNetworkClient";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type ThemeNetwork = {
  nodes: { id: number; canonical_label: string; mention_count: number }[];
  edges: { theme_id_a: number; theme_id_b: number; weight: number }[];
};

type SnapshotsResponse = {
  snapshots: { period_label: string; nodes: ThemeNetwork["nodes"]; edges: ThemeNetwork["edges"] }[];
};

async function getThemesNetwork(months: number): Promise<ThemeNetwork | null> {
  try {
    const res = await fetch(`${API_BASE}/themes/network?months=${months}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

async function getThemesNetworkSnapshots(months: number): Promise<SnapshotsResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/themes/network/snapshots?months=${months}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function ThemeNetworkPage({
  searchParams,
}: {
  searchParams: Promise<{ months?: string }>;
}) {
  const { months: monthsParam } = await searchParams;
  const months = monthsParam === "12" ? 12 : 6;

  const [data, snapshotsRes] = await Promise.all([
    getThemesNetwork(months),
    getThemesNetworkSnapshots(months),
  ]);

  const snapshots = snapshotsRes?.snapshots ?? null;

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <main className="mx-auto w-full max-w-6xl px-6 py-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs text-zinc-500 dark:text-zinc-400">
              <Link href="/" className="hover:underline">
                Themes
              </Link>{" "}
              / Network
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">
              Theme relationships
            </h1>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Which themes tend to appear together in the same documents, and how that changes over time.
            </p>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span>Range:</span>
            <Link
              href="/themes/network?months=6"
              className={`rounded px-2 py-1 ${months === 6 ? "bg-zinc-200 dark:bg-zinc-700" : "hover:underline"}`}
            >
              6 months
            </Link>
            <Link
              href="/themes/network?months=12"
              className={`rounded px-2 py-1 ${months === 12 ? "bg-zinc-200 dark:bg-zinc-700" : "hover:underline"}`}
            >
              1 year
            </Link>
          </div>
        </div>

        <div className="mt-8">
          {!data && !snapshots ? (
            <div className="flex h-[400px] items-center justify-center rounded-xl border border-zinc-200 bg-white p-8 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950">
              Could not load theme network. Is the backend running?
            </div>
          ) : (
            <ThemeNetworkClient
              initialData={data}
              snapshots={snapshots}
              months={months}
            />
          )}
        </div>
      </main>
    </div>
  );
}
