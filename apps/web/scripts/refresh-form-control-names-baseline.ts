// Rewrites scripts/form-control-names-baseline.json from the tree as it is now. Run it after a fix that names controls (the file can only
// shrink, and the guard fails on a stale line), never to make a new unnamed control pass:
//   node --experimental-strip-types scripts/refresh-form-control-names-baseline.ts
import fs from "node:fs";
import path from "node:path";
import { WEB, unnamedByFile } from "./formControlSources.ts";

const file = path.join(WEB, "scripts", "form-control-names-baseline.json");
const old = fs.existsSync(file) ? (JSON.parse(fs.readFileSync(file, "utf8")).files as Record<string, string[]>) : {};
const now = unnamedByFile();
const added = Object.entries(now).flatMap(([f, keys]) => keys.filter((k) => !(old[f] ?? []).includes(k)).map((k) => `${f}: ${k}`));
if (added.length > 0 && Object.keys(old).length > 0) {
  console.error("Refused: the baseline may only shrink. These unnamed controls are not on it:");
  for (const a of added) console.error(`  ${a}`);
  process.exit(1);
}
fs.writeFileSync(file, JSON.stringify({
  comment: "The form-control name ratchet (POST-A-127). The unnamed native controls of each file, by tag and what each is bound to; it may only shrink: a fix deletes its own entry in the same commit, and a control added or edited into the list is refused. See scripts/formControlNames.ts.",
  files: now,
}, null, 2) + "\n");
console.log(`${Object.keys(now).length} files, ${Object.values(now).reduce((a, b) => a + b.length, 0)} unnamed controls`);
