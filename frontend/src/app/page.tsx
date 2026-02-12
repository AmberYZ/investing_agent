import { ThemesPageClient } from "./components/ThemesPageClient";

export type ViewType =
  | "all"
  | "trending"
  | "sentiment_positive"
  | "sentiment_negative"
  | "inflections"
  | "debated"
  | "archived";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ months?: string; view?: string }>;
}) {
  const { months: monthsParam, view: viewParam } = await searchParams;
  const months = monthsParam === "12" ? 12 : 6;
  const view: ViewType =
    viewParam &&
    [
      "all",
      "trending",
      "sentiment_positive",
      "sentiment_negative",
      "inflections",
      "debated",
      "archived",
    ].includes(viewParam)
      ? (viewParam as ViewType)
      : "all";

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <main className="mx-auto w-full max-w-5xl px-6 py-10">
        <ThemesPageClient months={months} view={view} />
      </main>
    </div>
  );
}
