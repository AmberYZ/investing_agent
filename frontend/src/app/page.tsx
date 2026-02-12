import Link from "next/link";
import { ThemesPageClient } from "./components/ThemesPageClient";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ months?: string }>;
}) {
  const { months: monthsParam } = await searchParams;
  const months = monthsParam === "12" ? 12 : 6;

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <main className="mx-auto w-full max-w-5xl px-6 py-10">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Themes</h1>
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
              Click a theme to view narratives, time-series trends, and evidence
              quotes.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2 text-xs text-zinc-500 dark:text-zinc-400">
            <div className="flex items-center gap-2">
              <span>Volume range:</span>
              <Link
                href="/?months=6"
                className={`rounded px-2 py-1 ${months === 6 ? "bg-zinc-200 dark:bg-zinc-700" : "hover:underline"}`}
              >
                6 months
              </Link>
              <Link
                href="/?months=12"
                className={`rounded px-2 py-1 ${months === 12 ? "bg-zinc-200 dark:bg-zinc-700" : "hover:underline"}`}
              >
                1 year
              </Link>
            </div>
          </div>
        </div>

        <ThemesPageClient months={months} />
      </main>
    </div>
  );
}
