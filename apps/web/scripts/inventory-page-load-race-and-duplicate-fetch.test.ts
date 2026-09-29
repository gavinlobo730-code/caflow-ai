/**
 * Three findings on the client Inventory page and its LocationsAndBatches
 * panel, all touched together (apex-bank-assets-inventory-06, -07, -11).
 *
 * -06  `load` fired again on every `asAt` change with NO request-sequencing —
 *      whichever response resolved LAST won, regardless of which date it was
 *      actually for, so switching the as-at date quickly could show an
 *      earlier, slower response's data under the CURRENTLY selected date.
 *      Fixed with a ref-based counter, bumped before each fetch and checked
 *      before every setState that would apply a result.
 *
 * -07  `/api/inventory/items` was fetched TWICE per page load — once by the
 *      page's own `load()`, and again independently inside
 *      `LocationsAndBatches`'s own effect. Fixed by having the parent pass
 *      its already-fetched `items` down as a prop.
 *
 * -11  Three panels' own inline comments all say the stock register answers
 *      "what do I hold" and that they sit BELOW it — but the register (the
 *      `<DataTable>`) was rendered LAST on the page, after all three. Fixed
 *      by moving the register to sit right after CostFormulaPanel and before
 *      LocationsAndBatches, matching what the comments already assert.
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/inventory-page-load-race-and-duplicate-fetch.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app", "clients", "[id]", "inventory", "page.tsx");
const LOCATIONS = path.join(WEB, "components", "inventory", "LocationsAndBatches.tsx");

function pageSrc(): string {
  return stripComments(fs.readFileSync(PAGE, "utf8"));
}

function locationsSrc(): string {
  return stripComments(fs.readFileSync(LOCATIONS, "utf8"));
}

/** The body of the page's own `load` useCallback, isolated so a check phrased
 *  against it cannot accidentally match some other function on the page. */
function loadBody(s: string): string {
  const at = s.indexOf("const load = useCallback(async () => {");
  assert.ok(at >= 0, "the page's load() declaration was not found");
  const decl = s.slice(at);
  const end = decl.indexOf("}, [clientId, asAt]);");
  assert.ok(end > 0, "load's own useCallback deps array was not found to close the body");
  const body = decl.slice(0, end);
  assert.ok(body.length > 500, "load's extracted body looks too short");
  return body;
}

// ── -06: request sequencing ─────────────────────────────────────────────────

test("useRef is imported", () => {
  assert.match(pageSrc(), /import \{[^}]*\buseRef\b[^}]*\} from "react";/);
});

test("load bumps a ref-based sequence number before fetching", () => {
  const body = loadBody(pageSrc());
  assert.match(body, /const seq = \+\+loadSeqRef\.current;/,
    "the sequence number must be captured locally at the start of the call");
});

test("every setItems(...) call in load is guarded by isCurrent() immediately before it", () => {
  const body = loadBody(pageSrc());
  const calls = [...body.matchAll(/setItems\(/g)];
  // The as-at branch, the current-position branch, and the catch branch's
  // own setItems([]) — three call sites, and a stale response must not win
  // any of them.
  assert.equal(calls.length, 3,
    `expected 3 setItems(...) call sites inside load, found ${calls.length}`);
  const GUARD = "if (!isCurrent()) return;";
  for (const m of calls) {
    const upToHere = body.slice(0, m.index);
    const guardAt = upToHere.lastIndexOf(GUARD);
    assert.ok(guardAt >= 0, `no isCurrent() guard found before the setItems(...) call at ${m.index}`);
    // Nothing but whitespace (a stripped comment leaves blank, indented
    // lines) may sit between the guard and the call it is guarding — that is
    // what proves it is guarding THIS call and not an earlier, unrelated one.
    const between = upToHere.slice(guardAt + GUARD.length);
    assert.match(between, /^\s*$/,
      `something other than whitespace sits between the isCurrent() guard and ` +
      `setItems(...): ${JSON.stringify(between)}`);
  }
});

test("a stale call also skips setLoadFailed and the trailing setLoading(false)", () => {
  const body = loadBody(pageSrc());
  const catchAt = body.indexOf("} catch {");
  assert.ok(catchAt >= 0, "load must still have a catch block");
  const catchBody = body.slice(catchAt, catchAt + 200);
  assert.match(catchBody, /if \(!isCurrent\(\)\) return;/,
    "the catch branch must not apply a stale failure over a newer, already-applied result");
  const finallyAt = body.indexOf("} finally {");
  assert.ok(finallyAt >= 0, "load must still have a finally block");
  const finallyBody = body.slice(finallyAt, finallyAt + 120);
  assert.match(finallyBody, /if \(isCurrent\(\)\) setLoading\(false\);/,
    "a superseded call must not flip the loading indicator off for the call still in flight");
});

// ── -07: no duplicate items() fetch ─────────────────────────────────────────

test("LocationsAndBatches takes items as a prop instead of fetching its own", () => {
  const s = locationsSrc();
  assert.match(s, /export function LocationsAndBatches\(\{ clientId, asOf, items \}: \{/,
    "items must be destructured as a prop");
  assert.doesNotMatch(s, /request<\{[^}]*data: StockItem\[\][^}]*\}>\(\s*`\/api\/inventory\/items/,
    "the component must no longer independently fetch /api/inventory/items");
  assert.doesNotMatch(s, /const \[items, setItems\] = useState/,
    "items must no longer be local state");
});

test("the other four Promise.all calls inside LocationsAndBatches survive", () => {
  const s = locationsSrc();
  const at = s.indexOf("const load = useCallback(async () => {");
  assert.ok(at >= 0);
  const body = s.slice(at, at + 1500);
  for (const endpoint of ["/api/inventory/godowns", "/api/inventory/position-detail",
                          "/api/inventory/expiry", "/api/inventory/batches"]) {
    assert.match(body, new RegExp(endpoint.replace(/\//g, "\\/")),
      `${endpoint} must still be fetched — only the duplicate items() call was removed`);
  }
});

test("the page passes its own already-fetched items down to LocationsAndBatches", () => {
  const s = pageSrc();
  assert.match(s, /<LocationsAndBatches clientId=\{clientId\} asOf=\{asAt \|\| todayLocalISO\(\)\} items=\{items\} \/>/,
    "the parent's items state must be handed down, not re-fetched by the child");
});

// ── -11: the register sits above the three panels, not after them ──────────

test("the DataTable register comes before LocationsAndBatches, StockAgeingPanel and ReorderPanel", () => {
  const s = pageSrc();
  const dataTableAt = s.indexOf("<DataTable");
  const costFormulaAt = s.indexOf("<CostFormulaPanel");
  const locationsAt = s.indexOf("<LocationsAndBatches");
  const ageingAt = s.indexOf("<StockAgeingPanel");
  const reorderAt = s.indexOf("<ReorderPanel");
  for (const [name, at] of [["CostFormulaPanel", costFormulaAt], ["DataTable", dataTableAt],
                            ["LocationsAndBatches", locationsAt], ["StockAgeingPanel", ageingAt],
                            ["ReorderPanel", reorderAt]] as const) {
    assert.ok(at >= 0, `${name} was not found on the page`);
  }
  assert.ok(costFormulaAt < dataTableAt, "CostFormulaPanel must still come before the register");
  assert.ok(dataTableAt < locationsAt, "the register must come before LocationsAndBatches");
  assert.ok(dataTableAt < ageingAt, "the register must come before StockAgeingPanel");
  assert.ok(dataTableAt < reorderAt, "the register must come before ReorderPanel");
});
