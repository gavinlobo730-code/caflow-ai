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

/** `{ file: unnamed controls }` for every file that has any, in path order. */
export function unnamedByFile(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const f of SOURCES) {
    const n = findControls(fs.readFileSync(path.join(WEB, f), "utf8"), f).filter((c) => c.verdict === "unnamed").length;
    if (n > 0) out[f] = n;
  }
  return out;
}
