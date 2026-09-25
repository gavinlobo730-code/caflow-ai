"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ClientModuleGrid } from "@/components/client/ClientModuleGrid";

/**
 * The client workspace's FRONT DOOR.
 *
 * It used to be a spinner and a `router.replace` to `/overview/` — so there
 * was no front door at all, only a corridor you were pushed down. Arriving at
 * a client meant landing on the contact card, the health card, a task list and
 * a compliance list, with the module grid at line 133 of that page, below the
 * fold, where nobody scrolled to it. Overview is unchanged and is still one
 * click away; what changed is that it is no longer the only thing a client
 * workspace can open on.
 *
 * ⚠️ IT COSTS ZERO OF D10's REDIRECT BUDGET, which is why it is here rather
 * than at a new path. Cloudflare Pages caps dynamic `_redirects` rules at 100,
 * the cap FAILS SILENTLY, and 98 are in use — but `/clients/:id` is already
 * rule #1, because something had to serve the redirect this page replaces.
 * A `/clients/:id/modules/` would have cost two and left none.
 *
 * THE `_placeholder` BRANCH STAYS EXACTLY AS IT WAS. `output: export`
 * pre-renders this route once under that id and Cloudflare rewrites every real
 * client onto it; the literal string in the address bar means no client was
 * resolved, so the list is the honest destination. The smoke walk pins that
 * bounce as correct (`EXPECTED_LANDINGS["/clients/_placeholder"]`), and it
 * feeds every :id the placeholder, so removing this would fail the walk as
 * well as stranding the visitor.
 */
export default function ClientRootPage() {
  const router = useRouter();
  const [clientId, setClientId] = useState<string | null>(null);

  useEffect(() => {
    const m = window.location.pathname.match(/^\/clients\/([^/]+)/);
    const id = m ? decodeURIComponent(m[1]) : null;
    if (!id || id === "_placeholder") {
      router.replace("/clients");
      return;
    }
    setClientId(id);
  }, [router]);

  if (!clientId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-brand border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-ps-label">Loading workspace…</p>
        </div>
      </div>
    );
  }

  return <ClientModuleGrid clientId={clientId} />;
}
