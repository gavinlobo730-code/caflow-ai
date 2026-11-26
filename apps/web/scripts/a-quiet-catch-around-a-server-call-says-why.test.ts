// A catch around a server call tells the person, hands the failure on, or says in a comment why it does neither (POST-A-515 (d)). Run with:
//   node --experimental-strip-types --test scripts/a-quiet-catch-around-a-server-call-says-why.test.ts
//
// WHY THIS EXISTS
//     The first half of POST-A-515 stopped a button from ending a failure with no answer (scripts/silentHandlers.ts). The second half is the
//     READS: 97 catches around a server call told nobody anything, counted on 19-11-2026 and read one by one on 20-11-2026. Most were what
//     they said they were, a prefill or a lookup that leaves a screen as it was. Thirteen places were not, and each drew a failed read as a fact:
//       * the client accounting dashboard printed ₹0 for revenue, expenses, profit and cash when the profit-and-loss or the cash-flow report
//         did not answer (its own comment said a zero there would be a false claim; the two `.catch(() => null)` took the failure back out);
//       * the payroll Outputs tab said "No payroll runs yet" for a read of the runs that had failed, and drew no EPFO filing order and no reason;
//       * the Shared Reports list said "No reports shared yet" for a read that had failed (and read no `error` at all);
//       * the payroll declarations and statutory screens, the Schedule III screen and the receivables ageing offered an empty client picker for
//         a client list that could not be read (the shared pager hands a failure back as `error` and does not throw, so three of the four
//         catches never ran);
//       * the copilot kept a thumb lit for a rating that was never stored;
//       * the onboarding checklist stayed on the old state, with no word, after a step was saved and the re-read failed;
//       * the bank reconciliation statement, the payroll bank advice, the account-deletability answer and the retainer screen's services list
//         vanished when their read failed, which reads as "none";
//       * the firm calendar left out every MCA form when their read failed, which reads as "none due";
//       * the Team access grid drew a member whose own answer did not come against their ROLE's template, which since overrides became real
//         can show access the person does not have or hide access they do;
//       * the client-portal page told a person whose invitation failed to be accepted only to "ask your accountant to invite you".
//     Each is fixed and pinned below.
//
// THE RULE (scripts/quietCatches.ts holds it): a `catch` around a server call, or the handler of a `.catch(...)` on one, must make something
//     visible happen, throw, hand back a value, or record the failure for its caller, OR carry a comment inside it saying why it is quiet.
//     The comment is the review: it states what the screen then shows and why that is true. A bare `catch {}` or `.catch(() => {})` is a finding.
//
// WHAT IT DOES NOT SEE: a read whose failure never throws because the client hands it back in the answer, the shared pager's `{ error }`
//     most of all (sixteen browser list reads took `data` alone; scripts/a-pager-read-reads-its-error.test.ts holds that rule now), a catch
//     whose call is behind a name declared elsewhere, and what a screen does with the stand-in value a handler hands back.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { scanSource, scanTree } from "./quietCatches.ts";

const WEB = path.join(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
const flagged = (src: string) => scanSource("app/x/page.tsx", src).findings.map((f) => `${f.kind}:${f.fn}`);

// ═══ THE TREE ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

test("no catch around a server call is quiet without saying why", () => {
  const { findings } = scanTree(WEB);
  assert.deepEqual(
    findings.map((f) => `${f.file}:${f.line} (${f.kind}) ${f.fn}: ${f.detail}`),
    [],
    "A catch around a server call tells nobody anything and says nothing why. Tell the person (a setter, a toast), hand the failure on, or write the reason inside the catch.",
  );
});

test("the scan reads the tree it claims to", () => {
  const { filesScanned, examined } = scanTree(WEB);
  assert.ok(filesScanned > 700, `only ${filesScanned} files were scanned: the walk lost a directory`);
  assert.ok(examined > 600, `only ${examined} catches around a server call were examined: the scan stopped recognising them`);
});

// ═══ NEGATIVE CONTROLS: the scan finds what it says it finds ═══════════════════════════════════════════════════════════════════════

test("it flags a bare catch and a bare .catch around a server call", () => {
  assert.deepEqual(flagged("async function a(){ try { await api.x.y(); } catch {} }"), ["catch:a"]);
  assert.deepEqual(flagged("function b(){ api.x.y().catch(() => {}); }"), [".catch:b"]);
  assert.deepEqual(flagged("function c(){ api.x.y().catch(() => undefined); }"), [".catch:c"]);
  assert.deepEqual(flagged("function d(){ api.x.y().catch(() => null); }"), [".catch:d"]);
  assert.deepEqual(flagged("async function e(){ try { await supabase.from('t').select(); } catch (e) { console.error(e); } }"), ["catch:e"]);
  assert.deepEqual(flagged("async function f(){ try { return await api.x.y(); } catch { return null; } }"), ["catch:f"]);
  assert.deepEqual(flagged("function g(){ api.x.y().catch(() => reload()); }"), [".catch:g"]);
});

test("it does not flag a catch that tells, throws, records, hands back a value or says why", () => {
  assert.deepEqual(flagged("async function a(){ try { await api.x.y(); } catch (e) { setError(String(e)); } }"), []);
  assert.deepEqual(flagged("async function b(){ try { await api.x.y(); } catch (e) { toast({ title: 'no' }); } }"), []);
  assert.deepEqual(flagged("async function c(){ try { await api.x.y(); } catch (e) { throw new Error('x'); } }"), []);
  assert.deepEqual(flagged("async function d(){ const failures: string[] = []; try { await api.x.y(); } catch (e) { failures.push(String(e)); } }"), []);
  assert.deepEqual(flagged("async function e(){ let failed = 0; try { await api.x.y(); } catch { failed += 1; } }"), []);
  assert.deepEqual(flagged("async function f(){ try { return await api.x.y(); } catch { return { ok: false }; } }"), []);
  assert.deepEqual(flagged("async function g(){ try { await api.x.y(); } catch { /* the field stays as it was; the form still works */ } }"), []);
  assert.deepEqual(flagged("function h(){ api.x.y().catch(() => false); }"), []);
  assert.deepEqual(flagged("function i(){ api.x.y().catch(() => ({ ok: false })); }"), []);
  assert.deepEqual(flagged("function j(){ api.x.y().catch(() => setFailed(true)); }"), []);
  assert.deepEqual(flagged("function k(){ api.x.y().catch(() => { /* a usage count nobody waits for */ }); }"), []);
  assert.deepEqual(flagged("function l(){ api.x.y().catch(() => /* read as unknown below, never as zero */ null); }"), []);
});

test("a comment too short to be a reason does not count", () => {
  assert.deepEqual(flagged("async function a(){ try { await api.x.y(); } catch { /* skip */ } }"), ["catch:a"]);
  assert.deepEqual(flagged("function b(){ api.x.y().catch(() => { /* ignore */ }); }"), [".catch:b"]);
});

test("a catch that is not around a server call is not this rule's", () => {
  assert.deepEqual(flagged("function a(s: string){ try { return JSON.parse(s); } catch {} }"), []);
  assert.deepEqual(flagged("function b(){ localStorage.setItem('a', 'b'); try { window.print(); } catch {} }"), []);
});

// ═══ THE THIRTEEN PLACES: each is pinned to the thing that was wrong ══════════════════════════════════════════════════════════════════════

test("the accounting dashboard prints a dash, not ₹0, for a report that did not answer", () => {
  const page = read("app/clients/[id]/accounting/page.tsx");
  assert.match(page, /reportReading\(plRes,/, "the dashboard no longer asks what the profit-and-loss answer said");
  assert.match(page, /reportReading\(cfRes,/, "the dashboard no longer asks what the cash-flow answer said");
  assert.match(page, /figureText\(readings\.revenue, fmt\)/);
  assert.match(page, /figureText\(readings\.cash, fmt\)/);
  assert.match(page, /unreadReportsSentence\(/, "the page does not say which report did not answer");
  assert.doesNotMatch(page, /revenue = plRes\.data/, "the figures are taken off the answer without asking whether it was one");
});

test("the payroll Outputs tab says a failed read of the runs and does not call it an empty list", () => {
  const src = read("app/clients/[id]/payroll/page.tsx");
  const at = src.indexOf("function OutputsTab");
  assert.ok(at > 0);
  const tab = src.slice(at, at + 9000);
  assert.match(tab, /const \[runsFailed, setRunsFailed\]/);
  assert.ok(tab.indexOf("if (runsFailed)") > 0 && tab.indexOf("if (runsFailed)") < tab.indexOf('title="No payroll runs yet"'),
    "the failure is not said before the empty state is drawn");
  assert.match(tab, /const \[sequenceFailed, setSequenceFailed\]/);
  assert.match(tab, /The filing order could not be read/);
});

test("the Shared Reports list reads its error and says it", () => {
  const src = read("app/clients/[id]/accounting/page.tsx");
  assert.match(src, /const \{ data, error \} = await supabase\.from\("shared_reports"\)/);
  assert.match(src, /sharedFailed \? \(\s*<ErrorState/);
});

test("the four client pickers read the pager's error, and three of them say it", () => {
  for (const rel of ["app/payroll/declarations/page.tsx", "app/payroll/statutory/page.tsx", "app/accounting/schedule-iii/page.tsx", "app/accounting/receivables/page.tsx"]) {
    const src = read(rel);
    assert.match(src, /if \((error|readError)\) throw (error|readError);/, `${rel} drops the pager's error again`);
  }
  for (const rel of ["app/payroll/declarations/page.tsx", "app/payroll/statutory/page.tsx", "app/accounting/schedule-iii/page.tsx"]) {
    const src = read(rel);
    assert.match(src, /setClientsFailed\(true\)/, `${rel} does not say a client list that could not be read`);
    assert.match(src, /CLIENT_LIST_UNREAD/);
  }
});

test("a rating that was not stored is taken back and said", () => {
  const src = read("app/copilot/page.tsx");
  const at = src.indexOf("const rateMessage");
  assert.ok(at > 0);
  const body = src.slice(at, at + 1300);
  assert.match(body, /feedback_rating: before/, "the thumb stays lit after a failed save");
  assert.match(body, /Your rating was not saved/);
});

test("a saved onboarding step whose re-read failed says the screen may be out of date", () => {
  const src = read("app/clients/onboarding/page.tsx");
  assert.match(src, /async function refreshSelected\(workflowId: string\): Promise<boolean>/);
  assert.match(src, /if \(!\(await refreshSelected\(selected\.id\)\)\)/);
  assert.match(src, /could not be read again/);
});

test("a panel whose read failed says so instead of vanishing", () => {
  assert.match(read("components/banking/ReconcileTab.tsx"), /brsFailed \&\& \(/);
  assert.match(read("components/payroll/MonthlyReview.tsx"), /adviceUnread \&\& \(/);
  assert.match(read("components/banking/AccountsPanel.tsx"), /deletabilityUnread \? \(/);
  assert.match(read("app/accounting/retainer/page.tsx"), /serviceOptionsUnread \&\& \(/);
});

test("the firm calendar says when the MCA dates could not be read", () => {
  const src = read("app/calendar/page.tsx");
  assert.match(src, /mcaUnread \&\& \(/);
  assert.match(src, /This is not a calendar with no MCA forms due/);
});

test("the Team access grid names the members whose own answer did not come", () => {
  const src = read("app/team/page.tsx");
  assert.match(src, /setUnreadMembers\(ids\.filter/);
  assert.match(src, /unreadMembers\.length > 0 \&\& \(/);
});

test("a person whose invitation failed to be accepted is told so on the portal page", () => {
  const src = read("app/portal/dashboard/page.tsx");
  assert.match(src, /setInviteFailure\(failureSentence\(/);
  assert.match(src, /Your invitation was not accepted/);
});
