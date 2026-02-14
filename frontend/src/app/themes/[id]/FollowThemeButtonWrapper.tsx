"use client";

import { useEffect, useState } from "react";
import { FollowThemeButton } from "../../components/FollowThemeButton";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function FollowThemeButtonWrapper({ themeId }: { themeId: number }) {
  const [followed, setFollowed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/themes/followed/ids`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((ids: number[]) => {
        setFollowed(Array.isArray(ids) && ids.includes(themeId));
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [themeId]);

  if (!loaded) return null;

  return (
    <FollowThemeButton
      themeId={themeId}
      followed={followed}
      onToggle={() => setFollowed(!followed)}
      variant="normal"
    />
  );
}
