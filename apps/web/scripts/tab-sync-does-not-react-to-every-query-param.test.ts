// apex-sales-purchases-09: a ?tab=/?doc= deep-link sync effect that depends on
// the WHOLE useSearchParams() object re-runs on every unrelated query-string
// write on the page (opening a document, changing a filter, a cross-tab
// navigation) — not only a change to ?tab= itself — and snaps the visible tab
// back to whatever ?tab= still says in the URL. Confirmed live on the Sales
// tab: navigating from Customers via "View Invoices" left a stale ?tab= in
// the URL (navigateTo only ever wrote ?cust=), so opening an invoice or
// changing the period later re-ran the effect and reverted to Customers. The
// same effect shape exists, currently latent, on Purchases, Payroll, Bank and
// Fixed Assets.
//
// THE FIX
//     Key the effect on the tab/doc PARAMETER VALUES (`params.get("tab")`,
//     `params.get("doc")`), not on the searchParams object itself, so it only
//     re-fires when one of those two actually changes. On the Sales page,
//     navigateTo and selectTab also now set/delete ?tab= (and drop the
//     transient ?doc=) so the URL never drifts from the visible tab.
//
// Run with:
//   node --experimental-strip-types --test scripts/tab-sync-does-not-react-to-every-query-param.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

const PAGES = [
  "app/clients/[id]/sales/page.tsx",
  "app/clients/[id]/purchases/page.tsx",
  "app/clients/[id]/payroll/page.tsx",
  "app/clients/[id]/bank/page.tsx",
  "app/clients/[id]/fixed-assets/page.tsx",
];

for (const rel of PAGES) {
  const SRC = stripComments(read(rel));

  test(`${rel}: the deep-link sync effect depends on tab/doc VALUES, not the searchParams object`, () => {
    // The effect body still calls openedAt(tabDeepLinkParams.toString()) —
    // that is fine, it just must not be what re-triggers the effect.
    const m = /const tabDeepLinkParams = useSearchParams\(\);([\s\S]*?)\}, \[([^\]]*)\]\);/.exec(SRC);
    assert.ok(m, "the ?tab=/?doc= sync effect was not found in its expected shape");
    const [, body, deps] = m;
    assert.match(body, /const tabParam = tabDeepLinkParams\.get\("tab"\);/);
    assert.match(body, /const docParam = tabDeepLinkParams\.get\("doc"\);/);
    assert.match(deps.trim(), /^tabParam, docParam$/, `dependency array is [${deps}], not [tabParam, docParam]`);
    // The negative control: the OLD dependency array read [tabDeepLinkParams]
    // directly, which this must no longer do.
    assert.doesNotMatch(deps.trim(), /^tabDeepLinkParams$/);
  });
}

test("sales/page.tsx: navigateTo keeps ?tab= in sync and drops the transient ?doc=", () => {
  const SRC = stripComments(read("app/clients/[id]/sales/page.tsx"));
  const m = /function navigateTo\(target: SalesTab, custId\?: string\) \{([\s\S]*?)\n  \}/.exec(SRC);
  assert.ok(m, "navigateTo not found");
  const body = m[1];
  assert.match(body, /if \(target === "invoices"\) p\.delete\("tab"\); else p\.set\("tab", target\);/);
  assert.match(body, /p\.delete\("doc"\);/);
  assert.match(body, /window\.history\.replaceState/);
});

test("sales/page.tsx: selectTab also drops the transient ?doc= on a manual tab click", () => {
  const SRC = stripComments(read("app/clients/[id]/sales/page.tsx"));
  const m = /function selectTab\(target: SalesTab\) \{([\s\S]*?)\n  \}/.exec(SRC);
  assert.ok(m, "selectTab not found");
  assert.match(m[1], /p\.delete\("doc"\);/);
});
