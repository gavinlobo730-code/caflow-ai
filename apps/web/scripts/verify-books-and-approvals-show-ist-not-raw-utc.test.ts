/**
 * The Verify Books run-history chips and the Approvals "Posted At" column
 * rendered raw UTC timestamps with `String(x).slice(0, 16).replace("T", " ")`
 * and no timezone label (apex-accounting-reports-18) — silently showing the
 * wrong calendar DATE for anything in the 00:00-05:30 IST window.
 *
 * THE RULE
 *
 *   Neither `j.posted_at` nor `r.started_at` is ever formatted with the raw
 *   slice-and-replace; both go through `formatIstLabelled`.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const FILE = join(import.meta.dirname, "..", "app/clients/[id]/accounting/page.tsx");

function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

test("no raw slice(0, 16).replace(\"T\", \" \") timestamp formatting remains", () => {
  const src = code(readFileSync(FILE, "utf8"));
  assert.doesNotMatch(
    src, /\.slice\(0,\s*16\)\.replace\(\s*"T"\s*,\s*" "\s*\)/,
    "a raw UTC timestamp slice with no timezone conversion or label reintroduces " +
    "apex-accounting-reports-18: it silently shows the wrong calendar date from " +
    "18:30 to 24:00 UTC (00:00-05:30 IST).",
  );
});

test("the Approvals Posted At column uses formatIstLabelled", () => {
  const src = code(readFileSync(FILE, "utf8"));
  assert.match(src, /formatIstLabelled\(j\.posted_at\)/);
});

test("the Verify Books run-history chip uses formatIstLabelled", () => {
  const src = code(readFileSync(FILE, "utf8"));
  assert.match(src, /formatIstLabelled\(r\.started_at\)/);
});

test("formatIstLabelled is imported from the shared helper", () => {
  const src = code(readFileSync(FILE, "utf8"));
  assert.match(src, /import \{ formatIstLabelled \} from "@\/lib\/dates\/formatIst"/);
});
