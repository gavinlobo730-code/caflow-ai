// WHERE A PANEL LIVES, resolved by what it SAYS rather than by a path.
//
// Three guards read "the panel the CA sees" and each had the per-client GST
// page's path written into it. When the firm-level GSTR-3B screen needed the
// same three panels they moved into `components/gst/Gstr3bFindings.tsx`
// (GST-22) and all three guards failed — not because the rule broke, but
// because each stated one spelling of it. This resolves the file by a phrase
// only that panel contains, and asserts there is exactly ONE, which is the
// other half of the same rule.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[]): string[] {
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(e.name)) out.push(p);
  }
  return out;
}

/** The one file containing `phrase`, read raw. Fails if none or several do. */
export function panelSource(phrase: string): string {
  const files: string[] = [];
  for (const d of ["app", "components"]) walk(path.join(WEB, d), files);
  const hits = files.filter((f) => fs.readFileSync(f, "utf8").includes(phrase));
  assert.equal(hits.length, 1,
    `expected exactly one file to render "${phrase}", found ${hits.length}: ` +
    hits.map((h) => path.relative(WEB, h)).join(", "));
  return fs.readFileSync(hits[0], "utf8");
}
