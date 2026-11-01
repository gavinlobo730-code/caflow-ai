// Rewrites scripts/form-control-names-baseline.json from the tree as it is now. Run it after a fix that names controls (the file can only
// shrink, and the guard fails on a stale line), never to make a new unnamed control pass:
//   node --experimental-strip-types scripts/refresh-form-control-names-baseline.ts
import fs from "node:fs";
import path from "node:path";
import { WEB, unnamedByFile } from "./formControlSources.ts";

const file = path.join(WEB, "scripts", "form-control-names-baseline.json");
const old = fs.existsSync(file) ? (JSON.parse(fs.readFileSync(file, "utf8")).files as Record<string, number>) : {};
const now = unnamedByFile();
const grew = Object.entries(now).filter(([f, n]) => n > (old[f] ?? 0));
if (grew.length > 0 && Object.keys(old).length > 0) {
  console.error("Refused: the baseline may only shrink. These files hold more unnamed controls than the baseline allows:");
  for (const [f, n] of grew) console.error(`  ${f}: ${n} (baseline ${old[f] ?? 0})`);
  process.exit(1);
}
fs.writeFileSync(file, JSON.stringify({
  comment: "The form-control name ratchet (POST-A-127). Unnamed native controls per file; it may only shrink: a fix lowers or deletes its own line in the same commit. See scripts/formControlNames.ts.",
  files: now,
}, null, 2) + "\n");
console.log(`${Object.keys(now).length} files, ${Object.values(now).reduce((a, b) => a + b, 0)} unnamed controls`);
