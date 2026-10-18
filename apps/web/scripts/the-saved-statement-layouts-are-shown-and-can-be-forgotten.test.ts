// What a bank taught the importer is shown beside the import, and can be taken back. Run with:
//   node --experimental-strip-types --test scripts/the-saved-statement-layouts-are-shown-and-can-be-forgotten.test.ts
//
// WHY THIS EXISTS
//     A mapping drawn by hand for a bank's export is saved for that account and that exact header row, and until now no screen
//     listed them: a mapping that had gone wrong, or one for a layout the bank has since changed, could be neither seen nor
//     taken back. The panel reads the server's window through the one reader, keeps "could not be read" apart from "none saved",
//     asks before forgetting, offers Forget only to a person who may write banking, and refreshes after.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}
const PANEL = "components/banking/SavedColumnMappings.tsx";
const HOST = "components/banking/AccountsPanel.tsx";

test("the panel asks for this client's layouts in a window and reads it through the one reader", () => {
  const src = code(PANEL);
  assert.match(src, /api\.banking\.listColumnMappings\(\{ client_id: clientId, limit: String\(limit\) \}\)/);
  assert.match(src, /readSavedMappings\(res\.data, limit\)/);
  assert.doesNotMatch(src, /res\.data as/, "no cast stands in for reading the window");
});

test("a list that could not be read is not drawn as an empty one", () => {
  const src = code(PANEL);
  assert.match(src, /kind: "unreadable"/);
  assert.match(src, /could not be loaded\. This is not the same as none having been saved/);
  assert.match(src, /title="No statement layout has been saved yet"/);
  assert.match(src, /state\.kind === "ready" && state\.rows\.length === 0/);
});

test("forgetting asks first, names the account, is offered only with banking write, and refreshes", () => {
  const src = code(PANEL);
  assert.match(src, /<Can resource="banking" action="write">/);
  assert.match(src, /await confirmDialog\(/);
  assert.match(src, /Forget the saved layout for \$\{accountName\(m\.bank_account_id\)\}\?/);
  assert.match(src, /api\.banking\.deleteColumnMapping\(m\.id\)/);
  assert.match(src, /setReload\(\(k\) => k \+ 1\)/);
  assert.match(src, /if \(busy\) return;/, "a second click while a request is in flight does nothing");
});

test("an account that is no longer listed is said so and never given another account's name", () => {
  const src = code(PANEL);
  assert.match(src, /A bank account no longer listed/);
});

test("the accounts panel mounts it for a real client only", () => {
  const src = code(HOST);
  assert.match(src, /import \{ SavedColumnMappings \} from "@\/components\/banking\/SavedColumnMappings";/);
  assert.match(src, /clientId && clientId !== "_placeholder" && \(\s*<SavedColumnMappings clientId=\{clientId\} accounts=\{accounts\}/);
});
