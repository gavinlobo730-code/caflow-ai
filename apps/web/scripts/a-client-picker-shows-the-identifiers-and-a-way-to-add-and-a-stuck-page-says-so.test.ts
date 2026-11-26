// The client pickers, the ways to add a client, and the entry pages that wait. Run with:
//   node --experimental-strip-types --test scripts/a-client-picker-shows-the-identifiers-and-a-way-to-add-and-a-stuck-page-says-so.test.ts
//
// WHAT WAS WRONG (POST-A-487, 488, 491; a tester's list of 18-11-2026 and the owner's photograph of 19:16 IST)
//   487  the client dropdown inside a client showed the name and the entity type and no PAN or GSTIN, and two firm-level
//        pickers (Receivables and Schedule III) read only `id, client_name`, so the lookup that searches PAN and GSTIN had
//        nothing to show or search.
//   488  "Add Client" was on the Clients page alone (and drawn for every role, though only a Manager or a Partner may add),
//        so a tester looking in the dropdown or the sidebar's Clients panel found no way to add a company.
//   491  a page sat on "Loading workspace…" with a spinner and no end until a hard reload.
//
// THE RULE, as the source states it: each picker names `clientIdentityLine` and `clientSearchFields`; each entry point to
// the form is offered only to `can("client", "write")`; the page answers `?add=1`; and both entry pages that draw
// "Loading workspace…" draw the notice with the Reload button, and the error boundary reloads a failed page-code load.
// It reads source, so what it cannot see is a picker drawn from a different component altogether.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

test("the switcher shows each client's PAN and GSTIN, searches them, and lists the way to add one only for a member who may", () => {
  const s = read("components/ClientSwitcher.tsx");
  assert.match(s, /getSecondary=\{clientIdentityLine\}/);
  assert.match(s, /getSearchFields=\{clientSearchFields\}/);
  assert.match(s, /const canAdd = can\("client", "write"\)/);
  assert.match(s, /onCreate=\{canAdd \? \(\) => router\.push\(ADD_CLIENT_HREF\) : undefined\}/);
  assert.match(s, /emptyCreateLabel=\{canAdd \? ADD_CLIENT_LABEL : undefined\}/);
  assert.match(s, /pinCreateAtTop=\{canAdd\}/);
});

test("the two firm-level pickers that read `id, client_name` now read the PAN and the GSTIN the lookup shows", () => {
  for (const f of ["app/accounting/receivables/page.tsx", "app/accounting/schedule-iii/page.tsx"]) {
    const s = read(f);
    assert.match(s, /\.select\("id, client_name, pan, gstin"\)/, `${f} reads the identifiers`);
    assert.doesNotMatch(s, /\.from\("clients"\)\s*\.select\("id, client_name"\)/, `${f} no longer reads the name alone`);
  }
});

test("the sidebar's Clients panel links to the form for a member who may add a client, and to nobody else", () => {
  const s = read("components/panels/ClientsPanel.tsx");
  assert.match(s, /const canAdd = can\("client", "write"\)/);
  const at = s.indexOf("{canAdd && (");
  assert.ok(at > 0, "the entry is inside the permission");
  assert.ok(s.indexOf("href={ADD_CLIENT_HREF}") > at, "the link is inside it");
});

test("the Clients page draws Add Client and Import only for a member who may, and answers ?add=1 once", () => {
  const s = read("app/clients/page.tsx");
  assert.match(s, /const canAdd = can\("client", "write"\)/);
  const addButtons = s.split("\n").filter((l) => l.trim() === "Add Client" || /<Plus size=\{15\} \/> Add Client/.test(l)).length;
  assert.equal(addButtons, 2, "the header button and the empty state's button");
  assert.match(s, /\{canAdd && \(\s*<button\s+onClick=\{openCreate\}/, "the header button is inside the permission");
  assert.match(s, /\{filter === "active" && canAdd && \(/, "the empty state's button is inside it");
  assert.match(s, /\{canAdd && \(\s*<button\s+onClick=\{\(\) => setImportOpen\(true\)\}/, "Import is the same permission");
  assert.match(s, /wantsToAddClient\(window\.location\.search\)/);
  assert.match(s, /window\.history\.replaceState\(null, "", window\.location\.pathname\)/, "the request leaves the address so a reload does not reopen the form");
  assert.match(s, /if \(!permissionsResolved\) return;/, "it waits for the permission map");
});

test("both pages that draw \"Loading workspace…\" say when it is taking longer and offer Reload", () => {
  for (const f of ["app/clients/[id]/page.tsx", "app/not-found.tsx"]) {
    const s = read(f);
    assert.match(s, /Loading workspace…/);
    assert.match(s, /<StuckLoadingNotice \/>/, `${f} draws the notice`);
  }
  const n = read("components/ui/stuck-loading-notice.tsx");
  assert.match(n, /window\.location\.reload\(\)/);
  assert.match(n, /STUCK_AFTER_MS/);
});

test("a page whose own files fail to load reloads once by itself, and the boundary says what happened the second time", () => {
  const b = read("components/ModuleErrorBoundary.tsx");
  assert.match(b, /isPageCodeFailure\(error\)/);
  assert.match(b, /mayReloadForPageCode\(browserMemory\(\), Date\.now\(\)\)/);
  assert.match(b, /PAGE_CODE_SENTENCE/);
  assert.match(b, /pageCode \? \(\) => window\.location\.reload\(\) : reset/);
});
