// Writes the list of screens the "Where is…?" guide may point at, for the server (POST-A-538).
//
//   node --experimental-strip-types scripts/write-guide-screens.mjs          writes apps/api/domain/guide/screens.json
//   node --experimental-strip-types scripts/write-guide-screens.mjs --print  prints it and writes nothing
//
// THE LIST IS `lib/navigation/screens.ts`, the one inventory of screens (the command palette reads the same one). The server
// builds the model's request from ITS copy, never from text the browser sends, so a request cannot put its own words where
// the screens' names go; and the server runs from an image that holds no web source, so it needs a file of its own. This
// script is the only writer of that file, and `scripts/the-guide-reads-the-one-list-of-screens.test.ts` fails when the two differ.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ALL_SCREENS } from "../lib/navigation/screens.ts";
import { screenId } from "../lib/guide/whereIs.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
export const CATALOGUE = path.join(here, "..", "..", "api", "domain", "guide", "screens.json");

/** The file's exact text for the list as it stands. */
export function catalogueText() {
  const rows = ALL_SCREENS.map((s) => ({ id: screenId(s), name: s.name, section: s.section, words: s.synonyms }));
  return JSON.stringify(rows, null, 1) + "\n";
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes("--print")) process.stdout.write(catalogueText());
  else {
    fs.writeFileSync(CATALOGUE, catalogueText());
    console.log(`wrote ${path.relative(path.join(here, "..", "..", ".."), CATALOGUE)}`);
  }
}
