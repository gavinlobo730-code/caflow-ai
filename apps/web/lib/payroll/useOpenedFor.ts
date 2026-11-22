"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import { usePracticeClient } from "@/lib/workspace/usePracticeClient";

/**
 * `?client=` as the screen was opened, read once, the practice's id where the caller is a Partner and something was
 * named, and whether that question has been answered. Read off `window.location` and not `useSearchParams`, as Attendance does: this is a static export, and
 * `useSearchParams` forces a Suspense boundary on a page that otherwise needs none.
 */
export function useOpenedFor(): { openedFor: string; practiceId: string | null; settled: boolean } {
  const [openedFor] = useState<string>(() =>
    typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("client") ?? "");
  const { userRole } = useAuth();
  const asks = openedFor !== "" && userRole === "Partner";
  const lookup = usePracticeClient(asks);
  return {
    openedFor,
    practiceId: lookup.state === "ready" ? lookup.practiceId : null,
    // False only while the question is out. A screen whose FIRST read depends on the answer (Reports reads one client's
    // rows or the firm's) waits for this; a screen that only adds a picker entry need not.
    settled: !asks || lookup.state === "ready" || lookup.state === "not-set-up" || lookup.state === "unavailable",
  };
}
