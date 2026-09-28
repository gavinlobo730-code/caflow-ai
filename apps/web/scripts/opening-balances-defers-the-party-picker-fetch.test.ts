/**
 * OpeningBalancesTab fetched the FULL customers/vendors list on mount, purely
 * to fill a picker inside the "Add a document" drawer that most visits never
 * open (apex-accounting-reports-17).
 *
 * THE RULE
 *
 *   The customers/vendors fetch's effect must guard on `showForm` (the
 *   drawer's own open state) and carry it in its dependency array, so it
 *   fetches only once the drawer is actually opened — never on tab mount.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const FILE = join(import.meta.dirname, "..", "components/accounting/OpeningBalancesTab.tsx");

function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

function partyFetchEffect(src: string): string {
  const marker = "api.customers.list(clientId)";
  const idx = src.indexOf(marker);
  assert.ok(idx >= 0, "expected to find the customers/vendors fetch");
  // The enclosing useEffect: walk back to its `useEffect(() => {` and forward
  // to its dependency array close.
  const start = src.lastIndexOf("useEffect(", idx);
  const end = src.indexOf("}, [", idx);
  const depEnd = src.indexOf(")", end);
  return src.slice(start, depEnd + 1);
}

test("the party-picker fetch is guarded on the drawer's own open state", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const block = partyFetchEffect(src);
  assert.match(
    block, /if\s*\(!showForm\)\s*return;/,
    "the customers/vendors effect must return early when the Add-a-document " +
    "drawer (`showForm`) is not open, so it never fetches on tab mount.",
  );
});

test("the effect's dependency array includes showForm", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const block = partyFetchEffect(src);
  assert.match(
    block, /\[clientId, kind, showForm\]/,
    "the effect must re-run when the drawer opens (or the receivable/payable " +
    "kind changes while it is open), so its dependency array must include showForm.",
  );
});
