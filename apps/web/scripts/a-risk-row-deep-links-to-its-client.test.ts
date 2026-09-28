// sweep-reports-documents-07: /risks had no Link, href or row click handler
// anywhere in the file — every category card and the Consolidated Register
// table rendered client_id and a concrete "Recommended Action" as plain text,
// so a CA reading "File and pay the late fee..." had no click that took them
// to the client it was about.
//
// THE FIX
//     The client name, in both the per-category cards and the register
//     table, is now a Link to `/clients/{client_id}` wherever a row carries
//     one (every risk_type except "DSC Expiry" — a certificate is held by a
//     person, not a client, so `domain/risk/register.py::expiring_dscs`
//     stamps client_id "" and there is nothing client-scoped to open).
//     The register's "Recommended Action" cell links through
//     `riskActionHref`, which sends a filing-shaped risk to the client's own
//     GST/TDS/MCA compliance tab — by the SAME substrings
//     `app/clients/[id]/compliance/page.tsx` already tests `compliance_type`
//     against, so the two cannot silently disagree about which returns are
//     which — and everything else to the client's workspace.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-risk-row-deep-links-to-its-client.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const RISKS_PAGE = "app/risks/page.tsx";
const COMPLIANCE_PAGE = "app/clients/[id]/compliance/page.tsx";

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

function source(rel: string): string {
  return stripComments(read(rel));
}

test("the risks page imports next/link", () => {
  assert.match(source(RISKS_PAGE), /import Link from "next\/link"/);
});

test("a client name in the category cards is a Link to its workspace when a client_id exists", () => {
  const src = source(RISKS_PAGE);
  assert.match(
    src,
    /r\.client_id \? \(\s*<Link href=\{`\/clients\/\$\{r\.client_id\}`\}/,
    "CategoryCard no longer wraps the client name in a Link when client_id is present",
  );
});

test("a client name in the Consolidated Register is a Link to its workspace when a client_id exists", () => {
  const src = source(RISKS_PAGE);
  assert.match(
    src,
    /key: "clientName".*?render: \(r\) => r\.client_id\s*\?\s*<Link href=\{`\/clients\/\$\{r\.client_id\}`\}/s,
    "the register's clientName column no longer links to /clients/{client_id}",
  );
});

test("the Recommended Action column routes through riskActionHref rather than rendering plain text only", () => {
  const src = source(RISKS_PAGE);
  assert.match(
    src,
    /key: "action".*?riskActionHref\(r\)/s,
    'the "action" column no longer computes a link with riskActionHref',
  );
});

test("riskActionHref uses the same GST/TDS/MCA substrings the client compliance page tests compliance_type against", () => {
  const risksSrc = source(RISKS_PAGE);
  const complianceSrc = source(COMPLIANCE_PAGE);

  for (const pattern of ["GSTR", "TDS|24Q|26Q", "MCA|ROC|DIR"]) {
    assert.ok(
      risksSrc.includes(pattern),
      `riskActionHref in ${RISKS_PAGE} does not test against /${pattern}/i`,
    );
    assert.ok(
      complianceSrc.includes(pattern),
      `${COMPLIANCE_PAGE} no longer tests compliance_type against /${pattern}/i — the mirrored rule in ` +
        `${RISKS_PAGE} would then be citing a pattern the page it mirrors has abandoned`,
    );
  }
});

// Extract riskActionHref's own body (not a re-typed copy of it) and run real
// RiskRow-shaped objects through it, the way the browser will.
function loadRiskActionHref(): (r: Record<string, unknown>) => string | null {
  const src = source(RISKS_PAGE);
  const m = /function riskActionHref\(r: RiskRow\): string \| null \{([\s\S]*?)\n\}/.exec(src);
  assert.ok(m, "riskActionHref not found in " + RISKS_PAGE);
  // eslint-disable-next-line no-new-func
  return new Function("r", m![1]) as (r: Record<string, unknown>) => string | null;
}

test("a firm-wide risk with no client_id (DSC Expiry) has nowhere client-scoped to open", () => {
  const riskActionHref = loadRiskActionHref();
  assert.equal(
    riskActionHref({ client_id: "", risk_type: "DSC Expiry", particulars: { "DSC Holder": "A Partner" } }),
    null,
  );
});

test("an overdue GSTR filing opens the client's own GST compliance tab", () => {
  const riskActionHref = loadRiskActionHref();
  assert.equal(
    riskActionHref({
      client_id: "c1",
      risk_type: "Overdue Filing",
      particulars: { "Filing Type": "GSTR1", "Due Date": "2026-08-11" },
    }),
    "/clients/c1/compliance/gst",
  );
});

test("a TDS default opens the client's own TDS compliance tab", () => {
  const riskActionHref = loadRiskActionHref();
  assert.equal(
    riskActionHref({
      client_id: "c2",
      risk_type: "TDS Default",
      particulars: { "Return Type": "TDS24Q", "Due Date": "2026-07-31" },
    }),
    "/clients/c2/compliance/tds",
  );
});

test("an overdue MCA filing opens the client's own MCA compliance tab", () => {
  const riskActionHref = loadRiskActionHref();
  assert.equal(
    riskActionHref({
      client_id: "c3",
      risk_type: "Overdue Filing",
      particulars: { "Filing Type": "MCA_AOC4", "Due Date": "2026-05-30" },
    }),
    "/clients/c3/compliance/mca",
  );
});

test("an overdue filing this page cannot place on GST/TDS/MCA still opens the client's general compliance tab", () => {
  const riskActionHref = loadRiskActionHref();
  assert.equal(
    riskActionHref({
      client_id: "c4",
      risk_type: "Overdue Filing",
      particulars: { "Filing Type": "ITR", "Due Date": "2026-07-31" },
    }),
    "/clients/c4/compliance",
  );
});

test("an advance tax default opens the client's general compliance tab", () => {
  const riskActionHref = loadRiskActionHref();
  assert.equal(
    riskActionHref({ client_id: "c5", risk_type: "Advance Tax Default", particulars: {} }),
    "/clients/c5/compliance",
  );
});

test("a risk about the client's own record (GSTIN, PAN) opens the client's workspace, not a return tab", () => {
  const riskActionHref = loadRiskActionHref();
  assert.equal(
    riskActionHref({ client_id: "c6", risk_type: "GSTIN Mismatch", particulars: { GSTIN: "27AAAAA0000A1Z5" } }),
    "/clients/c6",
  );
  assert.equal(
    riskActionHref({ client_id: "c7", risk_type: "Missing PAN", particulars: {} }),
    "/clients/c7",
  );
});

test("a loan or deposit risk still opens the client's workspace, the nearest screen this page can name", () => {
  const riskActionHref = loadRiskActionHref();
  assert.equal(
    riskActionHref({ client_id: "c8", risk_type: "Loan Overdue", particulars: { Lender: "HDFC Bank" } }),
    "/clients/c8",
  );
  assert.equal(
    riskActionHref({ client_id: "c9", risk_type: "FD Maturing Soon", particulars: { Bank: "SBI" } }),
    "/clients/c9",
  );
});
