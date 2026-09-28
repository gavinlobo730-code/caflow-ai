// "Draft Engagement" on a pipeline lead carries the lead's own already-
// captured Estimated Monthly Fee and Recipient Email into the New Engagement
// Letter form, instead of dropping them and making the CA retype data the
// product already has.
//
// Run with:
//   node --experimental-strip-types --test scripts/draft-engagement-prefills-from-the-lead.test.ts
//
// WHAT WAS WRONG (sweep-clients-admin-07)
//     app/pipeline/page.tsx built the "Draft Engagement" link with only
//     lead_id and name; app/engagements/page.tsx read only those two out of
//     the query string, and CreateEngagementModal's reset effect always
//     seeded fee_rupees and recipient_email as "". The Lead itself carries
//     both (estimatedMonthlyFee in paise, email), so the CA had to retype
//     both on every conversion.
//
// THE FIX
//     The link now also carries fee_paise and email. The engagements page
//     reads them, and CreateEngagementModal seeds fee_rupees through the one
//     paise->rupees-string formatter (lib/money/rupeeInput.ts), never a float
//     division typed into the field — matching the CLAUDE.md rule that money
//     crosses in integer paise. A lead with no fee recorded (0, same as the
//     pipeline's own LeadCard "> 0" test) still leaves the field blank.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

test("the pipeline's Draft Engagement link carries the lead's fee and email", () => {
  const src = read("app/pipeline/page.tsx");
  assert.match(src, /Draft Engagement/);
  const linkMatch = /href={`\/engagements\?new=1&lead_id=\$\{lead\.id\}[^`]*`}/.exec(src);
  assert.ok(linkMatch, "Draft Engagement href not found");
  assert.match(linkMatch[0], /fee_paise=\$\{lead\.estimatedMonthlyFee\}/);
  assert.match(linkMatch[0], /email=\$\{encodeURIComponent\(lead\.email/);
});

test("the engagements page reads fee_paise and email off the query string", () => {
  const src = read("app/engagements/page.tsx");
  assert.match(src, /searchParams\.get\("fee_paise"\)/);
  assert.match(src, /searchParams\.get\("email"\)/);
  assert.match(src, /setIncomingFeePaise/);
  assert.match(src, /setIncomingEmail/);
});

test("CreateEngagementModal is passed the lead's fee and email, and seeds the form from them", () => {
  const src = read("app/engagements/page.tsx");
  assert.match(src, /initialFeePaise=\{incomingFeePaise\}/);
  assert.match(src, /initialEmail=\{incomingEmail\}/);
  // Through the shared formatter — never a bare `/100` or float division —
  // and only when a fee is actually recorded (> 0), matching the pipeline's
  // own LeadCard display rule.
  assert.match(src, /rupeeInputFromPaise\(initialFeePaise\)/);
  assert.match(src, /initialFeePaise != null && initialFeePaise > 0/);
  assert.match(src, /recipient_email: initialEmail \?\? ""/);
});
