"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

function AdminIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v2" />
      <path d="M12 21v2" />
      <path d="M4.22 4.22l1.42 1.42" />
      <path d="M18.36 18.36l1.42 1.42" />
      <path d="M1 12h2" />
      <path d="M21 12h2" />
      <path d="M4.22 19.78l1.42-1.42" />
      <path d="M18.36 5.64l1.42-1.42" />
    </svg>
  );
}

function HomeIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  );
}

export function AppHeader() {
  const pathname = usePathname();
  const isThemes = pathname === "/";
  const isBasket = pathname?.startsWith("/basket") ?? false;
  const isNetwork = pathname?.startsWith("/themes/network") ?? false;
  const isAdmin = pathname?.startsWith("/admin") ?? false;

  return (
    <header className="sticky top-0 z-10 border-b border-zinc-200 bg-zinc-50/95 backdrop-blur dark:border-zinc-800 dark:bg-black/95">
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-6 px-6">
        <Link
          href="/"
          className="flex items-center justify-center rounded-md p-2 text-zinc-600 transition hover:bg-zinc-200 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
          title="Home"
          aria-label="Home"
        >
          <HomeIcon />
        </Link>
        <nav className="flex items-center gap-1">
          <Link
            href="/"
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              isThemes
                ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
                : "text-zinc-600 hover:bg-zinc-200 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            }`}
          >
            Themes
          </Link>
          <Link
            href="/basket"
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              isBasket
                ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
                : "text-zinc-600 hover:bg-zinc-200 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            }`}
          >
            My Basket
          </Link>
          <Link
            href="/themes/network"
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              isNetwork
                ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
                : "text-zinc-600 hover:bg-zinc-200 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            }`}
          >
            Theme network
          </Link>
        </nav>
        <Link
          href="/admin"
          className={`ml-auto flex size-9 shrink-0 items-center justify-center rounded-lg transition ${
            isAdmin
              ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
              : "text-zinc-600 hover:bg-zinc-200 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
          }`}
          title="Admin"
          aria-label="Admin"
        >
          <AdminIcon />
        </Link>
      </div>
    </header>
  );
}
