"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Props = {
  themeId: number;
  followed: boolean;
  onToggle?: (themeId: number, newFollowed: boolean) => void;
  /** Compact for card, normal for detail page */
  variant?: "compact" | "normal";
};

export function FollowThemeButton({ themeId, followed, onToggle, variant = "compact" }: Props) {
  const [loading, setLoading] = useState(false);
  const [optimistic, setOptimistic] = useState<boolean | null>(null);
  const displayFollowed = optimistic ?? followed;

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (loading) return;
    setLoading(true);
    setOptimistic(!displayFollowed);
    try {
      if (displayFollowed) {
        const res = await fetch(`${API_BASE}/themes/${themeId}/follow`, { method: "DELETE" });
        if (!res.ok) throw new Error("Unfollow failed");
        onToggle?.(themeId, false);
      } else {
        const res = await fetch(`${API_BASE}/themes/${themeId}/follow`, { method: "POST" });
        if (!res.ok) throw new Error("Follow failed");
        onToggle?.(themeId, true);
      }
    } catch {
      setOptimistic(null);
    } finally {
      setLoading(false);
    }
  };

  if (variant === "compact") {
    return (
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className="rounded p-1.5 text-zinc-500 hover:bg-zinc-200 hover:text-amber-500 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-700 dark:hover:text-amber-400"
        title={displayFollowed ? "Unfollow (remove from My Basket)" : "Follow (add to My Basket)"}
        aria-label={displayFollowed ? "Unfollow" : "Follow"}
      >
        {displayFollowed ? (
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
        )}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className="inline-flex items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
      title={displayFollowed ? "Remove from My Basket" : "Add to My Basket"}
    >
      {displayFollowed ? (
        <>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
          In basket
        </>
      ) : (
        <>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
          Add to basket
        </>
      )}
    </button>
  );
}
