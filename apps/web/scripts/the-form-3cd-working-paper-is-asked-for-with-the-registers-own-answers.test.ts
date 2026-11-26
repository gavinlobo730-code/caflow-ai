// POST-A-076: the Form 3CD register leaves as a working paper (PDF or spreadsheet) the server builds from the very function the register's own read
// calls. The file shows what the screen shows only if it is asked for with the same two optional answers the register was built with (the activity
// for clause 8 and the Bank Rate for clause 22), which the page now spells once and hands to both calls. This pins that, and that the file is asked
// for at the route the server serves it from, in the formats it offers. Run with:
//   node --experimental-strip-types --test scripts/the-form-3cd-working-paper-is-asked-for-with-the-registers-own-answers.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const web = path.join(import.meta.dirname, "..");
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
const page = strip(fs.readFileSync(path.join(web, "app/income-tax/tax-audit/form-3cd/page.tsx"), "utf8"));
const client = strip(fs.readFileSync(path.join(web, "lib/api/index.ts"), "utf8"));

test("the register and the working paper are asked for with the same options, spelled once", () => {
  assert.equal((page.match(/const registerOptions = useCallback/g) ?? []).length, 1);
  assert.match(page, /api\.incomeTax\.form3cd\(clientId, fy, registerOptions\(\)\)/);
  assert.match(page, /api\.incomeTax\.form3cdWorkingPaper\(clientId, fy, format, registerOptions\(\)\)/);
});

test("the page offers the PDF and the spreadsheet and says it is a working paper and not the portal's form", () => {
  assert.match(page, /formats=\{\["pdf", "xlsx"\]\}/);
  assert.match(page, /not the portal(&apos;|')s Form 3CD; nothing is filed/);
  assert.match(page, /what is saved on the register/);
});

test("the client asks the export route for the file, names the year in the download, and sends the format", () => {
  const body = client.slice(client.indexOf("form3cdWorkingPaper:"));
  const call = body.slice(0, body.indexOf("saveForm3cdManualClauses"));
  assert.match(call, /new URLSearchParams\(\{ client_id, fy, format \}\)/);
  assert.match(call, /downloadFile\(`\/api\/income-tax\/form-3cd\/export\?\$\{p\.toString\(\)\}`, `form-3cd-working-paper-\$\{fy\}\.\$\{format\}`\)/);
});
