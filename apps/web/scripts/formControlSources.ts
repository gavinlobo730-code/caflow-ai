// The source files the form-control name rule reads, and the count of unnamed controls in each (POST-A-127). Shared by the guard and by the
// script that rewrites the baseline, so the two cannot read different populations.
import fs from "node:fs";
import path from "node:path";
import { findControls } from "./formControlNames.ts";

export const WEB = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "out") continue;
      walk(rel, out);
    } else if (/\.tsx$/.test(e.name) && !/\.test\.tsx$/.test(e.name)) {
      out.push(rel);
    }
  }
  return out;
}

/** The product's own pages and components. The primitives in `components/ui/` are read too: a primitive that forwards its props is a spread. */
export const SOURCES = ["app", "components", "lib"].flatMap((d) => walk(d)).sort();

/**
 * `{ file: [key, ...] }` for every file that has an unnamed control, in path order, each file's keys sorted (a repeated key is numbered
 * `key #2`). The keys, not a count, are what the baseline records: with a count a fix and a new unnamed control in one file net out.
 */
export function unnamedByFile(): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const f of SOURCES) {
    const seen = new Map<string, number>();
    const keys = findControls(fs.readFileSync(path.join(WEB, f), "utf8"), f).filter((c) => c.verdict === "unnamed").map((c) => {
      const n = (seen.get(c.key) ?? 0) + 1;
      seen.set(c.key, n);
      return n === 1 ? c.key : `${c.key} #${n}`;
    }).sort();
    if (keys.length > 0) out[f] = keys;
  }
  return out;
}

/** Controls that forward their props, by file. A wrapper is named by whoever calls it, which is only true of the shared primitives. */
export function spreadByFile(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const f of SOURCES) {
    const n = findControls(fs.readFileSync(path.join(WEB, f), "utf8"), f).filter((c) => c.verdict === "spread").length;
    if (n > 0) out[f] = n;
  }
  return out;
}
