// The client's Compliance -> TDS tab reads and writes nothing itself: not its four dashboard figures, not the §197 certificates and not
// the suppliers the certificate form offers (POST-A-293).
//
// WHAT THE TAB DID
//   * `TDSDashboard` counted `tds_challans`, `tds_returns` and `tds_certificates` over PostgREST with `selectAll` and added the challans'
//     totals up in the browser, where `rbac()` and the caller's client assignment never run;
//   * the Lower-deduction tab read `tds_lower_deduction_certificates` and `vendors` the same way and INSERTED a certificate straight
//     into the table. A certificate lowers what is withheld from a real supplier, so the only checks on that figure were three CHECK
//     constraints and one policy, and the section list the form offered was the only thing asking whether §197(1) reaches the section.
//
// The backend half is `apps/api/tests/test_a_section_197_certificate_is_recorded_by_the_server.py`. This is the other end: a tab that went
// back to the database, or to adding challans up, would make the server's care pointless.
//
// Run with: node --experimental-strip-types --test scripts/the-tds-tab-reads-through-the-api.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const TAB = stripComments(fs.readFileSync(path.join(WEB, "app/clients/[id]/compliance/tds/page.tsx"), "utf8"));

test("the tab is where this guard thinks it is", () => {
  assert.ok(TAB.length > 30000, `the client's TDS tab read as ${TAB.length} chars`);
});

test("the tab reads no table and writes no table itself: no pager, no firm id, no .from()", () => {
  assert.ok(!/\bselectAll\b|getUserProfile|getFirmId|\.from\(\s*["'`]/.test(TAB),
    "the TDS tab reads or writes a table straight from the database again (rbac() and the client assignment never run there)");
  // The one database client left is the one that fetches the sign-in token for the API.
  assert.equal((TAB.match(/getSupabaseClient\(\)/g) ?? []).length, 1, "the tab uses the database client for more than the token");
  assert.ok(/auth\.getSession\(\)/.test(TAB));
});

test("the dashboard's four figures are the server's and a figure the server did not send is not shown as a zero", () => {
  const at = TAB.indexOf("function TDSDashboard");
  const body = TAB.slice(at, TAB.indexOf("// ── Deductions", at));
  assert.ok(/apiFetch\(`\/api\/tds-workspace\/\?client_id=/.test(body), "the dashboard does not ask the API for its summary");
  assert.ok(/r\?\.success \? r\.data\?\.summary : null/.test(body), "the dashboard does not read the summary of a successful answer");
  assert.ok(/typeof n === "number" && Number\.isFinite\(n\)/.test(body), "the dashboard shows a figure it did not check is a number");
  assert.ok(!/\.reduce\(|\.length\b.*total_/.test(body), "the dashboard adds up or counts rows itself");
  assert.ok(/Failed to load TDS dashboard\./.test(body), "a refused read is not said");
});

test("the §197 tab reads its window and its suppliers from one server read and records through the API", () => {
  const at = TAB.indexOf("function LowerDeductionTab");
  const body = TAB.slice(at);
  assert.ok(/loadTdsWindow\(clientId, "lower_deduction_certificates"\)/.test(body), "the tab does not read the certificates as a window");
  assert.ok(/lower_deduction_certificates: "\/api\/tds-workspace\/lower-deduction-certificates"/.test(TAB), "the window's path is not the API's");
  assert.ok(/certs\.payload\.vendors/.test(body) && /Array\.isArray\(offered\)/.test(body), "the suppliers are not the server's, read as a list");
  assert.ok(/apiFetch\("\/api\/tds-workspace\/lower-deduction-certificates", \{\s*method: "POST"/.test(body), "the certificate is not recorded through the API");
  assert.ok(/res\.detail/.test(body), "the server's sentence for a refusal (FastAPI's `detail`) is not shown");
  assert.ok(/<ListWindowNotice /.test(body), "the tab does not say when the server cut its list short");
});

test("the browser sends the figures as integers it parsed with the one parser, and nothing else decides them", () => {
  const body = TAB.slice(TAB.indexOf("async function saveNew", TAB.indexOf("function LowerDeductionTab")));
  assert.ok(/bpsFromPercentInput\(form\.rate_percent\)/.test(body) && /paiseFromRupeeInput\(form\.ceiling_rupees\)/.test(body));
  assert.ok(/rate_bps: rateBps/.test(body) && /ceiling_paise: ceiling/.test(body), "the request does not carry the parsed integers");
});
