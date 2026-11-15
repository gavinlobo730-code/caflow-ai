/**
 * THE PHYSICAL VERIFICATION OF A CLIENT'S FIXED ASSETS (POST-A-112, its second half), driven in a browser.
 *
 * Against a stubbed server, in Chromium, on the Physical Verification tab of a client's fixed-asset page:
 *
 *   1. with no count, the tab says so with Start a count; starting one sends the day, who counted and the client, says the count is
 *      open and reads its paper; two clicks in one tick open ONE count;
 *   2. an open count's paper lists each asset with what the register says, in words where there is none, and the tally in the
 *      server's words; a finding "found elsewhere" asks where, sends it once for a double click, and the paper is read again quietly
 *      (the table stays on screen) and shows the finding, with the reminder that a finding moves nothing;
 *   3. the server's refusal of a finding is said in its words beside the asset and the choice is kept;
 *   4. Close the count asks first, inline; the server's refusal (assets not yet counted) is said in its words; a close it accepts
 *      leaves a closed paper that shows what the register said when each finding was recorded and offers no way to change it;
 *   5. a list or a paper the server could not read is said with Try again, never as no counts, and Try again reads it;
 *   6. a member who may only read sees the counts and their findings and no control to open, record or close;
 *   7. a finding that answers after the person chose another count leaves the other count's paper on screen, never a blank.
 */
import assert from "node:assert/strict";
import { sameTickDouble, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "asset-verification";

const LIST = /\/api\/fixed-assets\/verifications\?client_id=/;
const PAPER = /\/api\/fixed-assets\/verifications\/v-1$/;
const FINDING = /\/api\/fixed-assets\/verifications\/v-1\/findings\/fa-2$/;
const CLOSE = /\/api\/fixed-assets\/verifications\/v-1\/close$/;
const WORDS = { found: "Found where the register has it", found_elsewhere: "Found elsewhere", not_found: "Not found",
                damaged: "Found damaged" };
const TALLY = { found: 1, found_elsewhere: 0, not_found: 0, damaged: 0, to_count: 1 };
const OPEN = { id: "v-1", verified_on: "2026-03-31", counted_by: "Stores team", note: null, status: "open", closed_on: null,
               closed_by_name: null, tally: TALLY };
const LINES = [
  { asset_id: "fa-1", asset_code: "FA-0001", asset_name: "Lathe", location: "Factory", custodian: null, held_on_the_day: true,
    finding: "found", found_in: null, register_location: "Factory", register_custodian: null, note: null, recorded_by: "Asha Rao" },
  { asset_id: "fa-2", asset_code: "FA-0002", asset_name: "Laptop", location: null, custodian: "R. Iyer", held_on_the_day: true,
    finding: null, found_in: null, register_location: null, register_custodian: null, note: null, recorded_by: null },
];

async function atTheTab(env, { list = () => ok({ counts: [OPEN], findings: WORDS }), paper = () => ok({ verification: OPEN,
  lines: LINES, findings: WORDS }), canWrite = true } = {}) {
  const { page, stub } = env;
  // Opening, recording and closing are offered to whoever may write the client's accounts, which the server's permission map says.
  stub.route({ method: "GET", re: /\/api\/identity\/permissions$/, reply: () => ok({ role: canWrite ? "Partner" : "Reviewer",
    permissions: { accounting: canWrite ? ["read", "write"] : ["read"] } }) });
  const reads = { list: 0, paper: 0 };
  stub.route({ method: "GET", re: LIST, reply: () => { reads.list += 1; return list(reads.list); } });
  stub.route({ method: "GET", re: PAPER, reply: () => { reads.paper += 1; return paper(reads.paper); } });
  await page.goto(env.at("/fixed-assets/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Physical Verification" }).click();
  await page.getByTestId("asset-verification").waitFor();
  return reads;
}

const tab = (page) => page.getByTestId("asset-verification");

export const scenarios = [
  {
    id: "no-count-says-so-and-start-a-count-opens-one-once",
    title: "no count: said with Start a count; starting sends the day, who counted and the client, once, and reads the paper",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      stub.route({ method: "POST", re: /\/api\/fixed-assets\/verifications$/, delay: 300, reply: (_req, raw) => {
        sent.push(JSON.parse(raw));
        return ok({ id: "v-1", ...OPEN });
      } });
      const reads = await atTheTab(env, { list: (n) => ok({ counts: n === 1 ? [] : [OPEN], findings: WORDS }) });
      await tab(page).getByText("No physical count recorded yet").waitFor();
      await tab(page).getByRole("button", { name: "Start a count" }).click();
      await page.locator("#count-verified-on").fill("31/03/2026");
      await page.locator("#count-verified-on").press("Tab");
      await page.getByLabel("Counted by", { exact: true }).fill("Stores team");
      await sameTickDouble(page.getByRole("button", { name: "Open the count" }));
      await tab(page).getByText("The count is open. Record what was found of each asset.").waitFor();
      assert.equal(sent.length, 1, `the count was opened ${sent.length} times`);
      assert.equal(sent[0].verified_on, "2026-03-31");
      assert.equal(sent[0].counted_by, "Stores team");
      assert.equal(sent[0].note, null);
      assert.ok(sent[0].client_id, "the count names its client");
      await until(async () => reads.paper >= 1, "the paper to be read");
      await page.getByTestId("count-paper-v-1").waitFor();
    },
  },
  {
    id: "a-finding-found-elsewhere-asks-where-and-is-sent-once-and-shown-from-the-papers-next-read",
    title: "an open paper in words; found elsewhere asks where, sent once, and the paper read again quietly shows it",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      stub.route({ method: "PUT", re: FINDING, delay: 300, reply: (_req, raw) => { sent.push(JSON.parse(raw)); return ok({ id: "f-2" }); } });
      const after = LINES.map((l) => (l.asset_id === "fa-2" ? { ...l, finding: "found_elsewhere", found_in: "Bay 3",
        recorded_by: "Asha Rao" } : l));
      const reads = await atTheTab(env, { paper: (n) => ok({ verification: n === 1 ? OPEN : { ...OPEN, tally: { ...TALLY,
        found_elsewhere: 1, to_count: 0 } }, lines: n === 1 ? LINES : after, findings: WORDS }) });
      await page.getByTestId("count-v-1").click();
      const row = page.getByTestId("count-line-fa-2");
      await row.waitFor();
      assert.match(await row.innerText(), /at no place recorded, kept by R\. Iyer/);
      assert.match(await page.getByTestId("count-paper-v-1").innerText(),
        /Found where the register has it: 1 · Found elsewhere: 0 · Not found: 0 · Found damaged: 0 · not yet counted: 1/);
      await page.getByLabel("Finding for FA-0002").selectOption("found_elsewhere");
      await row.getByText("The register had it at no place recorded on the day counted. If it has moved, record the movement on the Asset Register.").waitFor();
      await page.getByLabel("Found in for FA-0002").fill("  Bay 3 ");
      await sameTickDouble(row.getByRole("button", { name: "Record" }));
      await until(async () => reads.paper >= 2, "the paper to be read again");
      assert.equal(sent.length, 1, `the finding was sent ${sent.length} times`);
      assert.deepEqual(sent[0], { finding: "found_elsewhere", found_in: "  Bay 3 ", note: null });
      await row.getByText(/Found elsewhere · found in Bay 3 · recorded by Asha Rao/).waitFor();
      assert.equal(await page.getByTestId("count-paper-v-1").count(), 1, "the paper stayed on screen");
    },
  },
  {
    id: "the-servers-refusal-of-a-finding-is-said-beside-the-asset-and-the-choice-is-kept",
    title: "a finding the server refuses: its sentence beside the asset, and the choice kept",
    async run(env) {
      const { page, stub } = env;
      const sentence = "This asset was not held on 31 Mar 2026, the day counted (it was bought after it or disposed of by then), so the count has nothing to find of it.";
      stub.route({ method: "PUT", re: FINDING, ...refuse(sentence) });
      await atTheTab(env);
      await page.getByTestId("count-v-1").click();
      const row = page.getByTestId("count-line-fa-2");
      await row.waitFor();
      await page.getByLabel("Finding for FA-0002").selectOption("not_found");
      await row.getByRole("button", { name: "Record" }).click();
      await row.getByText(sentence).waitFor();
      assert.equal(await page.getByLabel("Finding for FA-0002").inputValue(), "not_found");
    },
  },
  {
    id: "closing-asks-first-says-the-servers-refusal-and-a-closed-paper-shows-what-the-register-said",
    title: "Close asks inline, the refusal is the server's, and a closed paper shows the register as it was and changes nothing",
    async run(env) {
      const { page, stub } = env;
      const sentence = "1 asset held on 31 Mar 2026 has no finding yet. Record what the count found of each before closing it.";
      let closes = 0;
      stub.route({ method: "POST", re: CLOSE, status: () => (closes === 1 ? 422 : 200), reply: () => {
        closes += 1;
        return closes === 1 ? { detail: sentence } : ok({ ...OPEN, status: "closed" });
      } });
      const closed = { ...OPEN, status: "closed", closed_on: "2026-04-02", closed_by_name: null, tally: { ...TALLY, to_count: null } };
      const closedLines = [{ ...LINES[0], location: "Warehouse", register_location: "Factory", recorded_by: null }];
      await atTheTab(env, { paper: (n) => ok(n <= 1 ? { verification: OPEN, lines: LINES, findings: WORDS }
        : { verification: closed, lines: closedLines, findings: WORDS }) });
      await page.getByTestId("count-v-1").click();
      const paper = page.getByTestId("count-paper-v-1");
      await paper.getByRole("button", { name: "Close the count" }).click();
      await paper.getByText("Close this count? A closed count cannot be reopened, and its findings cannot change.").waitFor();
      await paper.getByRole("button", { name: "Close it" }).click();
      await paper.getByText(sentence).waitFor();
      await paper.getByRole("button", { name: "Close it" }).click();
      await paper.getByText(/Closed on 02 Apr 2026 by a member no longer with the firm\. This is the working paper and does not change; an asset added to the register after it was closed is not on it\./).waitFor();
      const row = page.getByTestId("count-line-fa-1");
      assert.match(await row.innerText(), /at Factory, kept by nobody named/);          // the register when the finding was made
      assert.match(await row.innerText(), /recorded by a member no longer with the firm/);
      assert.equal(await paper.getByRole("button", { name: /Record|Change|Close the count/ }).count(), 0);
      assert.equal(await page.getByLabel(/Finding for/).count(), 0);
    },
  },
  {
    id: "a-list-or-a-paper-not-read-is-said-with-try-again-never-as-no-counts",
    title: "an unread list and an unread paper: said with Try again, not as no counts, and Try again reads each",
    async run(env) {
      const { page } = env;
      const reads = await atTheTab(env, {
        list: (n) => (n === 1 ? { success: false, data: null, error: "The counts could not be read." } : ok({ counts: [OPEN], findings: WORDS })),
        paper: (n) => (n === 1 ? { success: false, data: null, error: "The count could not be read." }
          : ok({ verification: OPEN, lines: LINES, findings: WORDS })),
      });
      await tab(page).getByText("The counts could not be read.").waitFor();
      assert.equal(await tab(page).getByText("No physical count recorded yet").count(), 0);
      await tab(page).getByRole("button", { name: "Try again" }).click();
      await page.getByTestId("count-v-1").click();
      await tab(page).getByText("The count could not be read.").waitFor();
      await tab(page).getByRole("button", { name: "Try again" }).click();
      await page.getByTestId("count-paper-v-1").waitFor();
      assert.ok(reads.list >= 2 && reads.paper >= 2);
    },
  },
  {
    id: "a-member-who-may-only-read-sees-the-counts-and-findings-and-no-control",
    title: "a member who may only read: the counts and findings, and nothing to open, record or close",
    async run(env) {
      const { page } = env;
      await atTheTab(env, { canWrite: false, list: () => ok({ counts: [{ ...OPEN, status: "closed", closed_on: "2026-04-02" }],
        findings: WORDS }) });
      await page.getByTestId("count-v-1").click();
      await page.getByTestId("count-paper-v-1").waitFor();
      await page.getByTestId("count-line-fa-1").getByText(/Found where the register has it · recorded by Asha Rao/).waitFor();
      assert.equal(await page.getByLabel(/Finding for/).count(), 0, "a finding editor was offered");
      assert.equal(await tab(page).getByRole("button", { name: /Start a count|Close the count|Record|Change/ }).count(), 0);
    },
  },
  {
    id: "a-finding-that-answers-after-another-count-was-chosen-leaves-that-counts-paper-on-screen",
    title: "a late finding after choosing another count: the other count's paper stays, never a blank",
    async run(env) {
      const { page, stub } = env;
      const CLOSED = { ...OPEN, id: "v-2", verified_on: "2025-03-31", status: "closed", closed_on: "2025-04-05", closed_by_name: "Asha Rao",
                       tally: { ...TALLY, to_count: null } };
      stub.route({ method: "GET", re: /\/api\/fixed-assets\/verifications\/v-2$/, reply: () => ok({ verification: CLOSED,
        lines: [LINES[0]], findings: WORDS }) });
      stub.route({ method: "PUT", re: FINDING, delay: 1500, reply: () => ok({ id: "f-2" }) });
      const reads = await atTheTab(env, { list: () => ok({ counts: [OPEN, CLOSED], findings: WORDS }) });
      await page.getByTestId("count-v-1").click();
      await page.getByTestId("count-line-fa-2").waitFor();
      await page.getByLabel("Finding for FA-0002").selectOption("not_found");
      await page.getByTestId("count-line-fa-2").getByRole("button", { name: "Record" }).click();
      await page.getByTestId("count-v-2").click();
      await page.getByTestId("count-paper-v-2").waitFor();
      const before = reads.paper;
      await page.waitForTimeout(2000);                                          // the finding answers meanwhile
      assert.equal(await page.getByTestId("count-paper-v-2").count(), 1, "the chosen count's paper is gone");
      assert.equal(reads.paper, before, "the old count's paper was read again after another was chosen");
    },
  },
];
