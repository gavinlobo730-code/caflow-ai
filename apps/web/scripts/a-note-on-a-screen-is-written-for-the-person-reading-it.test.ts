// A NOTE ON A SCREEN IS WRITTEN FOR THE PERSON READING IT (23-11-2026). Run with:
//   node --experimental-strip-types --test scripts/a-note-on-a-screen-is-written-for-the-person-reading-it.test.ts
//
// Two kinds of sentence were found on screens while the hand-built dialogs were being converted, and neither was true for its reader.
//
// 1. "THIS ENVIRONMENT". Four notes that say a figure has not been checked against its primary source said why in the words of the
//    container the code was written in: "this environment cannot reach incometax.gov.in", "not independently verified ... in this
//    environment". A CA reading that on the live product is in no such environment, and the sentence reads as a fault in their own
//    set-up. What the note is for is one fact, that nobody has read the figure against the Act, the rule or the portal, and one
//    instruction, to check it before relying on it. The rule: no text a screen draws talks about an environment, a container, a proxy
//    or egress. Its list of exceptions is empty.
//
// 2. "PARTNER ONLY". Since 21 November 2026 the permissions a Partner ticks decide what each member of staff can open and do, and a
//    role is only what a person starts with. Five sentences still said a role decides: the year lock ("Partner-only", "Only Partners
//    can lock or unlock", and its tile on Accounting), the audit log ("Partner-only view") and login history ("visible to Managers and
//    Partners only"). Each of those screens is opened by a permission in the one access table, so the sentence was false for anybody a
//    Partner had ticked. The rule: a screen says "only a Partner" (in any of the spellings below) only where it is on the list in this
//    file, and the list says of each entry whether the claim is TRUE (the server asks the role and no tick opens it) or NOT YET CHECKED
//    against what the server asks. The list only shrinks: a new claim fails here until somebody has read the server's rule for it.
//    The five entries that began as NOT YET CHECKED were read against the server the same day: one is true (the staff links of the
//    firm's own payroll, which the server answers by role) and four were not (the move between amortisation ledgers and changing
//    assignments ask a permission a Partner can tick for somebody else, so each now names the permission; and the payroll switch's
//    fallback gave "only a Partner" as the reason for a refusal that had come without one, so it now says only what happened). No
//    entry is unchecked, and a test holds that.
//
// What this does not see: a sentence the SERVER writes and a screen shows as it came (those are apps/api's, and its own are on the
// ledger as POST-A-554), and a sentence assembled from pieces at run time.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

function walk(dir: string): string[] {
  return fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true }).flatMap((e) => {
    const rel = `${dir}/${e.name}`;
    if (e.isDirectory()) return walk(rel);
    return /\.tsx?$/.test(e.name) && !/\.test\.ts$/.test(e.name) ? [rel] : [];
  });
}

/** Every screen and component, comments removed, as [file, line number, line]. `lib/` draws nothing by itself and is not read. */
const LINES: Array<[string, number, string]> = ["app", "components"].flatMap(walk).sort().flatMap((file) =>
  stripComments(fs.readFileSync(path.join(ROOT, file), "utf8")).split("\n").map((line, i): [string, number, string] => [file, i + 1, line]));

const hits = (re: RegExp) => LINES.filter(([, , line]) => re.test(line));

/** The container's words. `sandbox=""` on the signing page's frame is an HTML attribute and not a sentence, so the word is not on this list. */
const BUILD_WORDS = /\bthis environment\b|\bthis container\b|\begress\b|\benvironment(?:'s|&apos;s)? proxy\b/i;

/** Every spelling found of "a role decides this". "the firm's only Partner" (the one Partner a firm has) is a different sentence and does not match. */
const ROLE_CLAIM = /\bPartners?[- ]only\b|\bOnly (?:a )?Partners?\b(?! of\b)|\bManagers and Partners only\b|\bPartners and Managers only\b|\bonly a Partner (?:can|sees|may)\b/;

/**
 * Where a screen may say "only a Partner", and why. `true`: the server asks the ROLE and no tick opens it. `unchecked`: the sentence was
 * there before this rule and nobody has yet read what the server asks for it (POST-A-554). Remove an entry when its sentence goes.
 */
const ROLE_CLAIMS_ALLOWED: Record<string, { claim: "true" | "unchecked"; why: string }> = {
  "app/practice/page.tsx": { claim: "true", why: "My practice is the Partner's alone (guardrail G1); the access table's rule for it is the role, which no tick opens" },
  "components/practice/PartnerGuard.tsx": { claim: "true", why: "the notice of the same rule (G1)" },
  "components/onboarding/FirstRunChecklist.tsx": { claim: "true", why: "the first-day steps that live in My practice (G1)" },
  "components/payroll/StaffLinksPanel.tsx": { claim: "true", why: "the members linked to the firm's own payroll (G4): the server answers a non-Partner 404 by ROLE on both routes (`practice_staff` asks `is_partner`, the link asks `assert_practice_payroll_is_the_partners`), read 23-11-2026" },
};

/**
 * THE SOFTER SPELLINGS OF THE SAME CLAIM (found 23-11-2026, after the list above held no unchecked entry). A sentence can name a role as
 * the one who may without the word "only": "Payroll is open to Partners and Managers", "a PIN that Partners will use", "A Manager or
 * Partner can remove it". Where the server asks a permission, that is a role's DEFAULT and not the rule: it is false for a member a
 * Partner has ticked, and for a Manager whose tick was taken away. Four were read against the server that day and corrected (the payroll
 * side panel, which also sent the reader to "Settings → Team", a place the Team screen has not been since it moved into My practice;
 * the year-lock PIN prompt; and the two "a Partner switches it on" sentences of the payroll switch). The rest are counted here, per file,
 * as NOT YET READ against the server (POST-A-556). The counts are an equality in both directions: a new one fails, and so does a
 * corrected one whose count is left behind, so the list only shrinks.
 */
const ROLE_NAMED = /\b(?:open|visible|available|limited|restricted) to (?:Partners?|Managers?)\b|\bthat Partners will use\b|\b[Aa] Partner (?:switches|turns|sets|locks|unlocks|approves|posts)\b|\bPartners? and Managers?\b(?! are asked)|\bManagers? and Partners?\b|\bfor Partners\b|\bPartners can\b|\bPartner or Manager\b|\bManager or (?:a )?Partner\b/;

/** True by role: My practice is the Partner's alone (G1), which no tick opens. */
const ROLE_NAMED_TRUE: Record<string, number> = { "components/practice/PartnerGuard.tsx": 1 };

const ROLE_NAMED_UNREAD: Record<string, number> = {
  "app/accounting/loans/page.tsx": 2,
  "app/approvals/page.tsx": 1,
  "app/clients/[id]/purchases/page.tsx": 1,
  "app/income-tax/tax-audit/page.tsx": 2,
  "app/knowledge/page.tsx": 1,
  "app/payroll/page.tsx": 2,
  "app/practice/profitability/page.tsx": 1,
  "app/settings/journal-approval/page.tsx": 2,
  "app/tds/page.tsx": 1,
  "components/banking/RulesTab.tsx": 3,
  "components/payroll/StatutoryHandoff.tsx": 1,
  "components/security/MyDevicesCard.tsx": 1,
  "components/tds/RetractChallanModal.tsx": 1,
};

test("a sentence that names a role as the one who may, in softer words, is counted on a list that only shrinks", () => {
  const found: Record<string, number> = {};
  for (const [file] of hits(ROLE_NAMED)) found[file] = (found[file] ?? 0) + 1;
  assert.deepEqual(found, { ...ROLE_NAMED_TRUE, ...ROLE_NAMED_UNREAD },
    "read what the server asks before naming a role: where it asks a permission, name the permission (or say nothing about who); " +
    "where it asks the role, add the file to ROLE_NAMED_TRUE with the reason. A corrected sentence lowers its file's count here.");
  assert.deepEqual(Object.keys(ROLE_NAMED_TRUE).filter((f) => f in ROLE_NAMED_UNREAD), []);
});

test("the four softer sentences read on 23 November no longer name a role, and the pattern would have caught each", () => {
  for (const file of ["components/panels/PayrollPanel.tsx", "app/accounting/lock-year/page.tsx", "app/clients/[id]/payroll/page.tsx",
    "app/payroll/attendance/page.tsx"]) {
    assert.equal(hits(ROLE_NAMED).some(([f]) => f === file), false, `${file} names a role as the one who may`);
  }
  for (const was of ["Payroll is open to Partners and Managers. Ask a Partner to grant", "Create a PIN that Partners will use to lock or unlock financial years.",
    " A Partner switches it on here.", "be created for them until a Partner turns it on; anything"]) {
    assert.match(was, ROLE_NAMED, `not caught: ${was}`);
  }
  // The stale menu path went with the first of them: the Team screen is in My practice, not in Settings.
  assert.equal(hits(/Settings → Team/).length, 0, "a screen still sends its reader to Settings → Team");
  for (const fine of ["a Partner and a Manager are asked for a second factor", "A Partner decides which parts of PracticeSync each person can open, on the Team screen."]) {
    assert.doesNotMatch(fine, ROLE_NAMED, `caught a sentence that names no rule: ${fine}`);
  }
});

test("no text a screen draws talks about the environment the code was written in", () => {
  const found = hits(BUILD_WORDS).map(([file, n, line]) => `${file}:${n}: ${line.trim().slice(0, 160)}`);
  assert.deepEqual(found, [],
    "say what the reader needs: that the figure has not been checked against its source, and to check it before relying on it");
});

test("a screen says only a Partner may do something only where it is on the list, and the list holds no entry that has gone", () => {
  const files = [...new Set(hits(ROLE_CLAIM).map(([file]) => file))];
  const unlisted = files.filter((f) => !(f in ROLE_CLAIMS_ALLOWED));
  assert.deepEqual(unlisted, [],
    "the permissions a Partner ticks decide what a member can open and do; a sentence that names a role is true only where the server asks the role. " +
    "Read what the server asks, then either name the permission or add the file here as `true` with the reason");
  const gone = Object.keys(ROLE_CLAIMS_ALLOWED).filter((f) => !files.includes(f));
  assert.deepEqual(gone, [], "these files no longer make the claim; remove them from the list so it only shrinks");
});

test("no entry on the list is still unchecked, and the four sentences a tick makes false are gone", () => {
  assert.deepEqual(Object.entries(ROLE_CLAIMS_ALLOWED).filter(([, e]) => e.claim !== "true").map(([f]) => f), [],
    "an entry is added as `true` once the server's rule has been read and it is the role; there is no 'later'");
  for (const file of ["components/fixed-assets/AmortisationReclassification.tsx", "app/team/assignments/page.tsx",
    "app/clients/[id]/payroll/page.tsx", "app/payroll/attendance/page.tsx"]) {
    assert.equal(hits(ROLE_CLAIM).some(([f]) => f === file), false, `${file} says a role decides`);
  }
  // What makes the two permission sentences true: the screens decide on the permission, and say so.
  const amort = fs.readFileSync(path.join(ROOT, "components/fixed-assets/AmortisationReclassification.tsx"), "utf8");
  assert.match(amort, /const canPost = can\("accounting", "approve"\);/);
  assert.match(amort, /needs the permission to approve the books/);
  const assign = fs.readFileSync(path.join(ROOT, "app/team/assignments/page.tsx"), "utf8");
  assert.match(assign, /const canAssign = can\("assignment", "write"\);/);
  assert.match(assign, /needs the permission to change who is assigned to which client/);
  // The fallback for a refusal with no words says what happened and gives no reason of its own.
  for (const file of ["app/clients/[id]/payroll/page.tsx", "app/payroll/attendance/page.tsx"]) {
    assert.match(fs.readFileSync(path.join(ROOT, file), "utf8"), /Payroll could not be switched /, `${file} lost its fallback sentence`);
  }
});

test("the five screens a permission opens no longer say a role does", () => {
  for (const file of ["app/accounting/lock-year/page.tsx", "app/accounting/page.tsx", "app/settings/audit-log/page.tsx", "app/team/login-history/page.tsx"]) {
    assert.equal(hits(ROLE_CLAIM).some(([f]) => f === file), false, `${file} says a role decides`);
  }
  // Each is opened by a permission in the one table, which is what makes the old sentences false and not merely blunt.
  const table = fs.readFileSync(path.join(ROOT, "lib/access/screenAccess.ts"), "utf8");
  for (const [route, pair] of [["/accounting/lock-year", '["accounting", "approve"]'], ["/settings/audit-log", 'read("audit")'], ["/team/login-history", 'read("team")']] as const) {
    const at = table.indexOf(`["${route}",`);
    assert.ok(at > 0, `${route} is no longer in the access table`);
    const rule = table.slice(at, table.indexOf("\n", at));
    assert.ok(rule.includes(pair), `${route} is no longer opened by ${pair}: read its sentence again`);
    assert.doesNotMatch(rule, /partnerOnly/, `${route} became a Partner-only rule: its sentence may name the role again`);
  }
});

test("the rule's two patterns catch the sentences that were on the screens, and let the nearby true ones through", () => {
  for (const was of ["off the bare Act — this environment cannot reach incometax.gov.in.", "against a primary source in this environment.",
    "refused at this environment&apos;s proxy", "the egress rule"]) {
    assert.match(was, BUILD_WORDS, `not caught: ${was}`);
  }
  assert.doesNotMatch('<iframe sandbox="" title="Engagement letter" />', BUILD_WORDS);
  for (const was of ["Partner-only — lock closed years", "Only Partners can lock or unlock.", "accidental edits — Partner only", "Partner-only view — immutable trail",
    "Login history is visible to Managers and Partners only.", "View only — only a Partner can change assignments.", "Only a Partner sees these."]) {
    assert.match(was, ROLE_CLAIM, `not caught: ${was}`);
  }
  for (const fine of ["you are the firm&apos;s only Partner, you approve it yourself.", "a Partner and a Manager are asked for a second factor"]) {
    assert.doesNotMatch(fine, ROLE_CLAIM, `caught a sentence that names no rule: ${fine}`);
  }
});
