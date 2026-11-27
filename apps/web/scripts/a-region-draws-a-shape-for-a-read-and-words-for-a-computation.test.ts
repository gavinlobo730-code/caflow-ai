// A loading region draws a SHAPE for a plain read, and keeps WORDS for a computation (POST-A-565). Run with:
//   node --experimental-strip-types --test scripts/a-region-draws-a-shape-for-a-read-and-words-for-a-computation.test.ts
//
// WHY THIS EXISTS
//     `LoadingRegion` (components/ui/skeleton.tsx) says when the server is slow, and since POST-A-449 every screen's wait sits in
//     one. A region whose only child was a line of words ("Loading…", "Reading the log…", "Checking the roster…") told the
//     person that something was coming and nothing about its shape, so a tab, a drawer or a panel jumped when its content arrived.
//     On 27-11-2026 seventy-nine such regions in 72 files became `SkeletonText` inside the same region (the label, the slow-server
//     notice and the guard that says so are unchanged).
//
// THE RULE
//     A `LoadingRegion` whose whole child is one waiting line that begins "Loading", "Reading", "Checking" or "Preparing" (with or
//     without a spinner, in a p, div or span) is a plain read and is refused: draw a shape (`SkeletonText`, a `TableSkeleton`, a
//     `FormSkeleton`). WORDS ARE KEPT WHERE THE WAIT IS A COMPUTATION: a line that begins "Building", "Computing" or "Laying out"
//     ("Building GSTR-1 from the books", "Computing the due date") tells a CA what the product is doing with their books, which is
//     the truthfulness the product trades on, and a skeleton would say nothing of it. A line with a dynamic part (`{month}`) is not
//     judged here: it is not a plain note.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const REGION = /<LoadingRegion\b([^>]*)>([\s\S]*?)<\/LoadingRegion>/g;
const PLAIN_READ = /^(?:Loading|Reading|Checking|Preparing)[^<{}]*(?:…|\.\.\.|&hellip;)\s*$/;

/** The text a region's whole child is, if the child is one waiting line (a p, div or span and a spinner around it are skipped). */
export function onlyChildIsAWaitingLine(inner: string): string | null {
  let t = inner.trim();
  t = t.replace(/^<(?:p|div|span)\b[^>]*>\s*/, "").replace(/\s*<\/(?:p|div|span)>$/, "");
  t = t.replace(/^<Loader2\b[^>]*\/>\s*/, "");
  return /^[A-Z][^<{}]*(?:…|\.\.\.|&hellip;)\s*$/.test(t) ? t : null;
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    const rel = `${dir}/${e.name}`;
    if (e.isDirectory()) { if (e.name !== "node_modules" && e.name !== ".next") walk(rel, out); }
    else if (/\.tsx$/.test(e.name) && !/\.test\.tsx$/.test(e.name)) out.push(rel);
  }
  return out;
}

const FILES = [...walk("app"), ...walk("components")];

/** Plain reads still drawn as words inside a region, as `file: line`. */
export function plainReads(rel: string, text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(REGION)) {
    const line = onlyChildIsAWaitingLine(m[2]);
    if (line !== null && PLAIN_READ.test(line)) out.push(`${rel}:${text.slice(0, m.index).split("\n").length}: ${line.slice(0, 60)}`);
  }
  return out;
}

/**
 * Lines left as words on purpose, as `file: how many`, each with why. A new one is a decision with a reason written here, and the
 * count is an equality, so a converted one removes its own row.
 *   app/accounting/receivables/page.tsx: the region is the ageing being BUILT ("Building the ageing"); its line says which books it reads
 *     to build it, the unpaid fee invoices.
 *   app/clients/[id]/tax/filing/page.tsx: the region is Part A being LAID OUT from the books; its line says that the books are being read.
 */
const KEPT_AS_WORDS: Record<string, number> = {
  "app/accounting/receivables/page.tsx": 1,
  "app/clients/[id]/tax/filing/page.tsx": 1,
};

test("no loading region draws a plain read as a line of words", () => {
  const found: Record<string, string[]> = {};
  for (const rel of FILES) {
    const hits = plainReads(rel, fs.readFileSync(path.join(ROOT, rel), "utf8"));
    if (hits.length) found[rel] = hits;
  }
  const counts = Object.fromEntries(Object.entries(found).map(([f, h]) => [f, h.length]));
  assert.deepEqual(counts, KEPT_AS_WORDS,
    "a region's whole child is a line of words for a read: draw a shape (SkeletonText, TableSkeleton, FormSkeleton) inside it, or, if a " +
    "computation, begin the line with Building, Computing or Laying out.\n" + Object.values(found).flat().join("\n"));
  assert.ok(FILES.length > 300, "the scan must actually be reading the tree");
});

test("the computations that keep their words still do, and are the ones the rule leaves alone", () => {
  const kept = FILES.flatMap((rel) => {
    const text = fs.readFileSync(path.join(ROOT, rel), "utf8");
    return [...text.matchAll(REGION)].map((m) => onlyChildIsAWaitingLine(m[2])).filter((l): l is string => l !== null && /^(?:Building|Computing|Laying out)/.test(l));
  });
  assert.ok(kept.length >= 6, `only ${kept.length} computations keep their words: either they were turned into shapes or the scan stopped seeing them`);
});

test("the rule tells a plain read from a computation and from a shape", () => {
  const read = '<LoadingRegion label="Loading the log" className="text-xs">Loading…</LoadingRegion>';
  const spin = '<LoadingRegion label="Loading"><p className="x"><Loader2 size={11} className="animate-spin" /> Reading the log…</p></LoadingRegion>';
  const build = '<LoadingRegion label="Building"><p className="x">Building GSTR-1 from the books…</p></LoadingRegion>';
  const shape = '<LoadingRegion label="Loading the log"><SkeletonText lines={3} /></LoadingRegion>';
  const dyn = '<LoadingRegion label="Loading"><p>Loading the register for {month}…</p></LoadingRegion>';
  assert.equal(plainReads("a.tsx", read).length, 1);
  assert.equal(plainReads("a.tsx", spin).length, 1);
  assert.equal(plainReads("a.tsx", build).length, 0, "a computation keeps its words");
  assert.equal(plainReads("a.tsx", shape).length, 0);
  assert.equal(plainReads("a.tsx", dyn).length, 0, "a line with a dynamic part is not a plain note");
});
