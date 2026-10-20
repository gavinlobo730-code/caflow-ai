// Practice → Compliance filters the queue on whether an obligation is LATE, as the server says, and not on the stored status.
//
// The defect (found by opening the seeded firm): the tile above the queue counted 220 overdue obligations while the Status filter's
// "Overdue" option listed the handful somebody had moved to that status by hand, because nothing in apps/api sets "Overdue" when a due
// date passes. Deadlines had been fixed the same way (lib/compliance/overdue.ts). The queue rows now carry the server's `overdue`
// flag, computed by the one rule (domain/practice/compliance_overdue), and the page filters and colours on it.
//
// Run with: node --experimental-strip-types --test scripts/the-compliance-queue-filters-on-the-servers-overdue-and-not-the-stored-status.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = stripComments(fs.readFileSync(path.join(__dirname, "..", "app", "practice", "compliance", "page.tsx"), "utf8"));

test("a queue row carries the server's overdue flag", () => {
  assert.match(PAGE, /interface Obligation \{[^}]*\boverdue\?: boolean;/s);
});

test("the status filter has a late option of its own and offers no stored Overdue status beside it", () => {
  assert.match(PAGE, /<option value=\{OVERDUE_FILTER\}>/);
  assert.match(PAGE, /Object\.keys\(NEXT_STATUS\)\.filter\(\(st\) => st !== "Overdue"\)/);
});

test("the late filter and the red due date both ask isLate, which reads the server's flag", () => {
  assert.match(PAGE, /statusFilter === OVERDUE_FILTER\) \{ if \(!isLate\(o, today\)\) return false; \}/);
  assert.match(PAGE, /const overdue = isLate\(o, today\);/);
  assert.match(PAGE, /return o\.overdue \?\? /);
});

test("the date is compared in one place only: the fallback for a backend that does not send the flag", () => {
  const comparisons = PAGE.match(/\.due_date < today/g) ?? [];
  assert.equal(comparisons.length, 1, "the page decides lateness from the date in more than one place");
  const inFallback = PAGE.match(/function isLate\([^)]*\): boolean \{[^}]*\.due_date < today/s);
  assert.ok(inFallback, "the one date comparison is not inside isLate");
});
