// A return built for one of a client's several GST registrations says when its
// documents are not split by registration (GST-05), and both GSTR-3B screens
// render it.
//
// The caveat is the server's (`domain/gst/registrations.documents_not_split_caveat`)
// and this is the half that stops it being served and rendered by nothing — the
// defect GST-22 records for `table_4a_gaps`, which came back from the API for
// months and was shown by no screen. The rule: the field is carried through the
// shaper, handed to `Gstr3bFindings` by BOTH screens, and rendered by it.
//
// Run with: node --experimental-strip-types --test scripts/a-return-for-one-registration-says-so.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const FINDINGS = read("components/gst/Gstr3bFindings.tsx");
const DATA = read("lib/data/gst.ts");
const FIRM_SCREEN = read("app/gst/gstr3b/page.tsx");
const CLIENT_SCREEN = read("app/clients/[id]/compliance/gst/page.tsx");
const AMENDMENTS = read("components/gst/AmendmentsTab.tsx");

test("the component renders the caveat and renders nothing when there is none", () => {
  assert.match(FINDINGS, /export function Gstr3bRegistrationCaveat/);
  assert.match(FINDINGS, /if \(!caveat\) return null/);
  assert.match(FINDINGS, /<Gstr3bRegistrationCaveat caveat=\{registrationCaveat\} \/>/);
});

test("the shaper carries the field through instead of dropping it", () => {
  assert.match(DATA, /registration_caveat: result\.registration_caveat/);
});

test("both GSTR-3B screens hand it to the shared component", () => {
  assert.match(FIRM_SCREEN, /registrationCaveat=\{result\.registration_caveat\}/);
  assert.match(CLIENT_SCREEN, /registrationCaveat=\{computeResult\.registration_caveat/);
});

test("the exception report renders it and can be asked of one registration", () => {
  assert.match(AMENDMENTS, /exceptions\.registration_caveat/);
  const api = read("lib/api/index.ts");
  assert.match(api, /gstr1Exceptions: \(clientId: string, period: string, gstin\?: string\)/);
  assert.match(api, /&gstin=\$\{encodeURIComponent\(gstin\)\}/);
});

test("the sentence is not composed in the browser", () => {
  for (const [name, code] of Object.entries({ FINDINGS, AMENDMENTS })) {
    assert.doesNotMatch(code, /registrations that file GSTR-1/, `${name} must render the server's sentence`);
  }
});
