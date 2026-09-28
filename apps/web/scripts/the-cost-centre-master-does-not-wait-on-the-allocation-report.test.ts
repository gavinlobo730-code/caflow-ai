/**
 * CostCentresTab awaited Promise.all([costCentres, costCentreAllocation])
 * before rendering the master list at all (apex-accounting-reports-13). The
 * allocation report used to page every posted Income/Expense line of the FY
 * (fixed server-side by migration 435), and even now it is a second,
 * independent question from "what departments has this client defined" — a
 * slow or failing report must not blank a screen whose main job, the master,
 * already loaded.
 *
 * THE RULE
 *
 *   The two loads are separate functions (loadCentres, loadReport), each
 *   with its own loading/error state, and neither is inside a Promise.all
 *   that blocks the other's render on mount.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const FILE = join(import.meta.dirname, "..", "components/accounting/CostCentresTab.tsx");

function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

test("costCentres and costCentreAllocation are not fetched inside one Promise.all on mount", () => {
  const src = code(readFileSync(FILE, "utf8"));
  assert.doesNotMatch(
    src, /Promise\.all\(\[\s*api\.accounting\.costCentres/,
    "the master list must not be fetched inside the same Promise.all as the " +
    "allocation report — a slow or failing report would otherwise block the " +
    "master list's render, which is the whole defect this item fixes.",
  );
});

test("the master list and the report each have their own loading state", () => {
  const src = code(readFileSync(FILE, "utf8"));
  assert.match(src, /const \[loading, setLoading\] = useState/, "expected the master's own loading state");
  assert.match(src, /const \[reportLoading, setReportLoading\] = useState/, "expected the report's own, separate loading state");
});

test("the master list renders without waiting on reportLoading", () => {
  const src = code(readFileSync(FILE, "utf8"));
  // The master's own gating condition (`!error && !loading && centres...`)
  // must not also test reportLoading — that would just reintroduce the
  // blocking under a different name.
  const masterGate = src.match(/\{!error && !loading && centres\.length [=>][^}]*&&/);
  assert.ok(masterGate, "expected to find the master list's render gate");
  assert.doesNotMatch(masterGate![0], /reportLoading/);
});

test("loadCentres and loadReport are independent callbacks, each with its own effect", () => {
  const src = code(readFileSync(FILE, "utf8"));
  assert.match(src, /const loadCentres = useCallback\(/);
  assert.match(src, /const loadReport = useCallback\(/);
  assert.match(src, /useEffect\(\(\) => \{ void loadCentres\(\); \}, \[loadCentres\]\)/);
  assert.match(src, /useEffect\(\(\) => \{ void loadReport\(\); \}, \[loadReport\]\)/);
});
