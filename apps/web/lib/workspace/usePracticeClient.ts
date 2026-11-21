"use client";

/**
 * THE PRACTICE'S OWN CLIENT ID, FOR A SCREEN THAT IS NOT INSIDE ITS WORKSPACE (POST-A-532).
 *
 * Inside `/clients/<id>/…` the shell already knows which client is open and whether it is the practice. On a fixed address
 * (`/practice/billing/`, the firm menu) nothing in the address names it, and the links to the practice's books need it. The
 * server answers (`GET /api/practice`, Partner-only); this hook asks once per mount, and only when it is told to.
 *
 * FOUR ANSWERS, NOT TWO. `ready` has the id. `not-set-up` is a firm whose practice record has not been created (it needs the
 * firm's PAN; the Practice home says so and offers to set it up). `unavailable` is a read that failed or was refused. A
 * screen must not treat either of the last two as the other: "set it up" said to a Partner whose read failed sends them to
 * create something that exists.
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { readPracticeLookup, type PracticeLookup } from "@/lib/workspace/practiceWorkspace";

export type { PracticeLookup } from "@/lib/workspace/practiceWorkspace";

export function usePracticeClient(enabled: boolean): PracticeLookup {
  const [lookup, setLookup] = useState<PracticeLookup>({ state: "idle", practiceId: null });
  useEffect(() => {
    if (!enabled) { setLookup({ state: "idle", practiceId: null }); return; }
    let live = true;
    setLookup({ state: "resolving", practiceId: null });
    api.practice.get()
      .then((res) => { if (live) setLookup(readPracticeLookup(res)); })
      .catch(() => { if (live) setLookup({ state: "unavailable", practiceId: null }); });
    return () => { live = false; };
  }, [enabled]);
  return lookup;
}
