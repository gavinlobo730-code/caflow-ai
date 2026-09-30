"use client";

import { useEffect } from "react";
import { initMonitoring } from "@/lib/monitoring";

/**
 * Starts the browser error tracker once the app is on screen. Renders nothing.
 *
 * It is mounted in `app/layout.tsx`, outside the auth providers: a crash while signing in is exactly
 * the one somebody needs to hear about. `app/global-error.tsx` replaces the layout, so it calls
 * `reportClientError` itself rather than relying on this.
 */
export function MonitoringInit() {
  useEffect(() => {
    initMonitoring();
  }, []);
  return null;
}
