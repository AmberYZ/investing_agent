"use client";

import { useEffect } from "react";
import {
  markThemeAsRead,
  markThemesReadAPI,
  READ_THEME_DATA_UPDATED_EVENT,
} from "../../lib/read-themes";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function MarkThemeAsRead({
  themeId,
}: {
  themeId: number;
  themeLastUpdated?: string | null;
}) {
  useEffect(() => {
    markThemesReadAPI(API_BASE, [themeId])
      .then(() => {
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent(READ_THEME_DATA_UPDATED_EVENT));
        }
      })
      .catch(() => {
        markThemeAsRead(themeId);
      });
  }, [themeId]);
  return null;
}
