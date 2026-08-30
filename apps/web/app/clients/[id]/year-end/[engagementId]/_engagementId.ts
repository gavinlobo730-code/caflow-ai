"use client";

/**
 * The year-end engagement id, read from the browser URL rather than useParams().
 *
 * Under `output: export` plus Cloudflare's rewrite-to-_placeholder hosting, the
 * App Router's params are anchored to the build-time shell — and
 * scripts/generate-redirects.js substitutes "_placeholder" for EVERY dynamic
 * segment, so on this two-segment route useParams() yields
 * { id: "_placeholder", engagementId: "_placeholder" }. The client id has a
 * shared provider that already works around this (useClientNav, see
 * lib/workspace/ClientNavContext.tsx); this second segment has none, so it is
 * read here the same way — exactly as sales/invoices/[invoiceId]/edit and
 * accounting/journal/[entryId]/edit read theirs.
 */

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

// Static sibling routes that live at the same depth as an engagement id.
// /clients/<id>/year-end/xbrl is a page, not an engagement, and the bare
// pattern would hand it back as an id — so name them rather than leave the
// next sibling route to discover this the hard way.
const STATIC_SIBLINGS = new Set(["xbrl"]);

function getEngagementIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/^\/clients\/[^/]+\/year-end\/([^/]+)/);
  if (!m) return "";
  const seg = decodeURIComponent(m[1]);
  return STATIC_SIBLINGS.has(seg) ? "" : seg;
}

export function useEngagementId(): string {
  // usePathname() is only a re-run trigger (its own value is the build-time
  // placeholder segment) — the real id always comes from window.location.
  const pathname = usePathname();
  const [engagementId, setEngagementId] = useState<string>(getEngagementIdFromLocation);
  useEffect(() => { setEngagementId(getEngagementIdFromLocation()); }, [pathname]);
  return engagementId;
}
