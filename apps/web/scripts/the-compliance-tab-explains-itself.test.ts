// app/clients/[id]/compliance/page.tsx — the client Compliance overview's
// sub-tab filter and empty-state messaging.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-compliance-tab-explains-itself.test.ts
//
// THREE THINGS FIXED, all on this one screen:
//
// (1) THE GST SUB-TAB FILTER DROPPED PMT-06 ROWS. `toEntry()` in
//     lib/data/compliance.ts sets `compliance_type: obligation_type ??
//     compliance_type`, so a PMT-06 row's true category ("QRMP challan", a
//     GST obligation) was overwritten by `obligation_type`
//     ("PMT06_CHALLAN") — which carries no "GSTR" substring — so the GST
//     tab's `/GSTR/i` test silently excluded it. Widened to `/GSTR|PMT/i`.
//
// (2) THE MCA SUB-TAB PILL SHOWED FOR EVERY ENTITY TYPE, including a
//     Proprietorship or Partnership, which `lib/entityObligations.ts`
//     already knows can never have an MCA/ROC obligation — the same
//     `offerMcaWorkspace` check the MCA Workspace card on this very page
//     already uses.
//
// (3) INCOME TAX/TDS/MCA SHOWED "No compliance entries" WHATEVER THE REASON,
//     so a client with no fee_engagements row (nothing generates those
//     obligations at all — services/compliance_obligation_service.py's
//     `_ACTIVE_ENGAGEMENT_STATUSES`) looked identical to one with an
//     engagement and genuinely nothing due. The empty state now names the
//     missing engagement where that is the reason.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/compliance/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the GST sub-tab catches PMT-06 rows as well as GSTR ones", () => {
  const src = code(PAGE);
  assert.match(src, /if \(subTab === "gst"\) return \/GSTR\|PMT\/i\.test\(c\.compliance_type\)/,
    "the GST filter must also match PMT (PMT-06), not GSTR alone");
});

test("the MCA sub-tab pill is gated on the same offerMcaWorkspace check the MCA Workspace card uses", () => {
  const src = code(PAGE);
  assert.match(src, /\.\.\.\(offerMcaWorkspace \? \["mca"\] : \[\]\)/,
    "the pill list must conditionally include mca rather than listing it unconditionally");
  // NEGATIVE CONTROL: the old code always included "mca" in the fixed array.
  assert.doesNotMatch(src, /\["all", "gst", "tds", "income_tax", "mca"\]/,
    "mca must no longer be a fixed, unconditional member of the sub-tab list");
});

test("selecting a sub-tab that has become unavailable falls back to all", () => {
  const src = code(PAGE);
  assert.match(src, /subTab === "mca" && !entity\.loading && !offerMcaWorkspace.*setSubTab\("all"\)/s,
    "a deep link or client switch must not strand the screen on a pill that is no longer offered");
});

test("an empty ITR/TDS/MCA tab explains a missing engagement rather than saying only 'No compliance entries'", () => {
  const src = code(PAGE);
  assert.match(src, /ACTIVE_ENGAGEMENT_STATUSES\s*=\s*new Set\(\["Active", "In Progress", "Review"\]\)/,
    "must mirror services/compliance_obligation_service.py's own _ACTIVE_ENGAGEMENT_STATUSES");
  assert.match(src, /ENGAGEMENT_SCOPED_LABEL/,
    "income_tax/tds/mca must be named as the engagement-scoped sub-tabs — gst is NOT one of them, " +
    "since generate_default_for_client's no-engagement fallback still generates GST obligations off the GSTIN");
  assert.match(src, /hasActiveEngagement === false && ENGAGEMENT_SCOPED_LABEL\[subTab\]/,
    "the engagement-scoped empty state must only show once the read has genuinely resolved to false");
  // NEGATIVE CONTROL: the old code was one unconditional line with no branch.
  assert.doesNotMatch(src,
    /\{filtered\.length === 0 && \(\s*<div className="text-center py-12 text-ps-hint text-sm">No compliance entries<\/div>/,
    "the empty state must no longer be a single unconditional sentence");
});

test("the engagement check reads fee_engagements directly, the same pattern NoticesSection on this page already uses", () => {
  const src = code(PAGE);
  assert.match(src, /\.from\("fee_engagements"\)\s*\.select\("status"\)\s*\.eq\("client_id", clientId\)/,
    "a direct Supabase read, RLS-scoped, matching the house pattern for an explanatory (non-authoritative) signal");
});
