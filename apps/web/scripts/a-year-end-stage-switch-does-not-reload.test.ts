// Switching between Year-End stages (Adjustments/Schedules/Checklist/…) is
// pure client-side React state — it must never ask next/navigation's router
// to navigate, because on this STATIC EXPORT there is no server to answer
// the RSC/Flight request a soft navigation needs for a real, non-static
// `engagementId` route (apex-payroll-yearend-06).
//
// Run with:
//   node --experimental-strip-types --test \
//     scripts/a-year-end-stage-switch-does-not-reload.test.ts
//
// WHAT WAS WRONG
//     openStage() called `router.replace(...)`, a real Next.js App Router
//     client navigation. On this deployment (Cloudflare Pages, `output:
//     "export"`) that silently fell back to a full browser reload on EVERY
//     stage click — re-fetching users, permissions, clients, health and the
//     engagement from scratch, 2-6 seconds each time.
//
// THE FIX
//     `stage` is local React state, seeded once from the URL's own `?tab=`
//     on the first render (for deep-linking and Back-button support), and
//     `openStage` only ever calls `window.history.replaceState` — which
//     updates the address bar cosmetically and triggers no Next.js
//     navigation machinery at all.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const FILE = "app/clients/[id]/year-end/[engagementId]/_workspace.tsx";

function read(): string {
  return stripComments(fs.readFileSync(path.join(WEB, FILE), "utf8"));
}

function openStageBody(src: string): string {
  const m = /function openStage\(next: StageId\) \{([\s\S]*?)\n  \}/.exec(src);
  assert.ok(m, "openStage() not found");
  return m[1];
}

test("openStage never calls the Next.js router", () => {
  const body = openStageBody(read());
  assert.doesNotMatch(body, /router\.(replace|push)\(/,
    "a router navigation inside openStage reproduces the full-reload defect");
});

test("openStage sets local state and updates the address bar cosmetically", () => {
  const body = openStageBody(read());
  assert.match(body, /setStage\(next\)/);
  assert.match(body, /window\.history\.replaceState\(/);
});

test("stage is local React state, seeded once from the URL on mount", () => {
  const src = read();
  assert.match(src,
    /const \[stage, setStage\] = useState<StageId>\(\(\) => \{/,
    "stage must be useState with a lazy initializer, not re-derived from searchParams every render");
  assert.match(src, /searchParams\.get\("tab"\)/,
    "the initial stage must still come off the URL, for deep links and Back");
});

test("the active stage component is still looked up from the state, not from searchParams", () => {
  const src = read();
  assert.match(src, /const ActiveStage = \(STAGES\.find\(\(s\) => s\.id === stage\)/);
});
