import Link from "next/link";
import { ThemeTimelineClient } from "./ThemeTimelineClient";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export type MegathemeNode = {
  id: string;
  label: string;
  theme_ids: number[];
  mention_count_by_date: Record<string, number>;
};

export type DiscussionsTimeline = {
  start_date: string;
  end_date: string;
  nodes: MegathemeNode[];
};

/** Full history: fetch enough days for the slider to cover all available data. */
const TIMELINE_DAYS = 730;

async function getDiscussionsTimeline(days: number): Promise<DiscussionsTimeline | null> {
  try {
    const res = await fetch(`${API_BASE}/themes/network/discussions/snapshots?days=${days}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function ThemeNetworkPage() {
  const timeline = await getDiscussionsTimeline(TIMELINE_DAYS);

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <main className="mx-auto w-full max-w-6xl px-6 py-10">
        <div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400">
            <Link href="/" className="hover:underline">
              Themes
            </Link>{" "}
            / Timeline
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">
            What the market is trading
          </h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Narratives getting attention — what&apos;s breaking, what&apos;s fading. Drag the slider to scrub by day; chart shows 60 days ending on the selected date.
          </p>
        </div>

        <div className="mt-8">
          {!timeline ? (
            <div className="flex h-[400px] items-center justify-center rounded-xl border border-zinc-200 bg-white p-8 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950">
              Could not load timeline. Is the backend running?
            </div>
          ) : (
            <ThemeTimelineClient timeline={timeline} />
          )}
        </div>
      </main>
    </div>
  );
}
