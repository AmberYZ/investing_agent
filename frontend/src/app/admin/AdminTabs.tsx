"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function AdminTabs() {
  const pathname = usePathname();
  const isIngest = pathname === "/admin" || pathname === "/admin/failures";
  const isThemes = pathname === "/admin/themes";
  const isReassign = pathname === "/admin/reassign";
  const isWatchDirs = pathname === "/admin/watch-dirs";
  const isSettings = pathname === "/admin/settings";

  return (
    <nav className="mb-8 flex items-center gap-1 border-b border-zinc-200 dark:border-zinc-800">
      <Link
        href="/admin/failures"
        className={`rounded-t-lg px-4 py-2.5 text-sm font-medium transition ${
          isIngest
            ? "border border-b-0 border-zinc-200 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
            : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        }`}
      >
        Ingest jobs
      </Link>
      <Link
        href="/admin/themes"
        className={`rounded-t-lg px-4 py-2.5 text-sm font-medium transition ${
          isThemes
            ? "border border-b-0 border-zinc-200 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
            : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        }`}
      >
        Themes & merge
      </Link>
      <Link
        href="/admin/reassign"
        className={`rounded-t-lg px-4 py-2.5 text-sm font-medium transition ${
          isReassign
            ? "border border-b-0 border-zinc-200 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
            : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        }`}
      >
        Reassign narratives
      </Link>
      <Link
        href="/admin/watch-dirs"
        className={`rounded-t-lg px-4 py-2.5 text-sm font-medium transition ${
          isWatchDirs
            ? "border border-b-0 border-zinc-200 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
            : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        }`}
      >
        Watch directories
      </Link>
      <Link
        href="/admin/settings"
        className={`rounded-t-lg px-4 py-2.5 text-sm font-medium transition ${
          isSettings
            ? "border border-b-0 border-zinc-200 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
            : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        }`}
      >
        Extraction prompt
      </Link>
    </nav>
  );
}
