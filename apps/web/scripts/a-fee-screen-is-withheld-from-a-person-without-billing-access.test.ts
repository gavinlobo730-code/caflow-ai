// A screen over the practice's own fee tables sits behind the fee access gate. Run with:
//   node --experimental-strip-types --test scripts/a-fee-screen-is-withheld-from-a-person-without-billing-access.test.ts
//
// WHY THIS EXISTS (POST-B-024)
//     fee_engagements, fee_invoices and fee_receipts are the practice's own economics, reserved by
//     core/permissions to `billing:read`. The database returns those rows only to a person who holds it and returns
//     NOTHING, without an error, to everyone else. A fee-receivables screen over nothing prints "Rs 0.00
//     outstanding" and "No unpaid fee invoices found": a statement about the practice that is really a statement
//     about the person looking. So a person without billing access is told so in words by
//     components/billing/FeeAccessGate, mounted as the layout of each place a staff screen shows the fee figures.
//
// THE RULE, NOT A SPELLING
//     A file that reads one of those tables from the browser must be under a gated route, and each gated route's
//     layout must render the gate. The profitability screen reads no fee table itself (it asks /api/analytics) but
//     shows the revenue the fee invoices give, so it is listed by name.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const FEE_TABLES = ["fee_engagements", "fee_invoices", "fee_receipts"];
const GATED_ROUTES = ["app/billing/", "app/accounting/receivables/", "app/practice/profitability/"];

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(e.name)) out.push(p);
  }
  return out;
}
const rel = (p: string) => path.relative(WEB, p).split(path.sep).join("/");
const read = (p: string) => fs.readFileSync(p, "utf8");
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

const FROM = new RegExp(`\\.from\\(\\s*["'](?:${FEE_TABLES.join("|")})["']`);
const READERS = [
  ...walk(path.join(WEB, "app")), ...walk(path.join(WEB, "components")), ...walk(path.join(WEB, "lib")),
].filter((p) => FROM.test(code(read(p)))).map(rel);

test("the scan finds the fee readers at all", () => {
  assert.ok(READERS.length >= 2, `only ${READERS.length} readers found: the scan stopped seeing them`);
});

test("every browser read of a fee table is under a gated route", () => {
  const ungated = READERS.filter((f) => !GATED_ROUTES.some((g) => f.startsWith(g)));
  assert.deepEqual(
    ungated, [],
    "a screen reads a fee table from the browser outside the gated routes: a person without billing access " +
    "would see an empty list that reads as 'nothing owed'. Put it under app/billing or app/accounting/receivables, " +
    "or wrap it in FeeAccessGate. If the figure it needs can be served by the API, ask the API instead.");
});

test("every gated route mounts the gate as its layout", () => {
  for (const dir of GATED_ROUTES) {
    const layout = path.join(WEB, dir, "layout.tsx");
    assert.ok(fs.existsSync(layout), `${dir}layout.tsx is missing: the screen under it is not gated`);
    const src = code(read(layout));
    assert.match(src, /FeeAccessGate/, `${dir}layout.tsx does not render FeeAccessGate`);
    assert.match(src, /\{children\}/, `${dir}layout.tsx does not pass its children through`);
  }
});

test("the gate asks billing:read, withholds in words, and renders the page until permissions have loaded", () => {
  const src = code(read(path.join(WEB, "components/billing/FeeAccessGate.tsx")));
  assert.match(src, /can\(\s*"billing"\s*,\s*"read"\s*\)/, "the gate does not ask billing:read");
  assert.match(src, /resolved\s*&&\s*!can\(/, "the gate must act only once permissions are known (resolved)");
  assert.match(src, /You do not have access to the practice's fees/, "the withheld state says nothing");
  assert.match(src, /not the same as there being nothing\s+owed/, "the withheld state must say it is not 'nothing owed'");
});

test("negative control: an ungated reader would be found", () => {
  const sample = `const x = sb.from("fee_invoices").select("*");`;
  assert.match(code(sample), FROM, "the reader pattern no longer matches a plain fee_invoices read");
});
