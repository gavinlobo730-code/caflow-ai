/**
 * Two gaps FORM GST ITC-04 names about a job-work challan can be closed from the Delivery Challans tab (POST-A-431, POST-A-423). The server's half is
 * `apps/api/tests/test_the_itc_04_gaps_about_a_job_worker_state_and_a_back_day_are_closed_through_the_amendment_door.py`; this is the browser's:
 *
 *   * the whole-challan box is offered by ONE definition, `owesItsBackDay`, which includes every challan recorded as received back with no day, whatever its period;
 *   * the State box is offered for a job-work challan that is not cancelled and holds neither a GSTIN nor a State, writes the place of supply through the amendment door with an inline body that carries
 *     nothing else (no status, no spread), judges no code, and says a refusal in the server's sentence;
 *   * the tab reads its lists and the open detail again after the State is taken.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { jobWorkerHasNoGstin, owesItsBackDay } from "../lib/sales/challanOffers.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => readFileSync(path.join(WEB, p), "utf8");
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

const tab = strip(read("components/sales/SalesCycleTab.tsx"));
const boxRaw = read("components/sales/JobWorkerStateBox.tsx");
const box = strip(boxRaw);

test("the strip does not make the scan vacuous", () => {
  assert.ok(box.includes("JobWorkerStateBox") && tab.includes("owesItsBackDay"));
  assert.ok(boxRaw.length - box.length > 800, "there were comments to strip");
});

const vectors = JSON.parse(readFileSync(path.join(WEB, "..", "..", "shared", "challan-offer-vectors.json"), "utf8"));

test("the whole-challan box is offered by one definition, evaluated against the vectors the server's test reads too", () => {
  assert.ok(vectors.back_day.length >= 6, "the vectors were hollowed out");
  for (const v of vectors.back_day) {
    const offered = owesItsBackDay({ status: v.status, received_back_on: v.received_back_on, clock: { applies: v.clock_applies } });
    assert.equal(offered, v.offered, `${JSON.stringify(v)}: the screen offers ${offered}`);
  }
  assert.match(tab, /import \{ jobWorkerHasNoGstin, owesItsBackDay \} from "@\/lib\/sales\/challanOffers";/, "the tab does not use the pure module");
  assert.ok(!/const owesItsBackDay\b/.test(tab), "the tab defines a second owesItsBackDay");
  assert.equal((tab.match(/challans\.(some|filter)\(owesItsBackDay\)/g) ?? []).length, 2, "the box's condition and its list do not both ask the one definition");
});

test("the State box is offered by one definition, evaluated against the vectors, and only there", () => {
  assert.ok(vectors.job_worker_state.length >= 8, "the vectors were hollowed out");
  for (const v of vectors.job_worker_state) {
    const box = jobWorkerHasNoGstin({ reason: v.reason, status: v.status, consignee_gstin: v.consignee_gstin, place_of_supply: v.place_of_supply });
    assert.equal(box, v.box, `${JSON.stringify(v)}: the screen offers ${box}`);
  }
  assert.match(tab, /\{detail\.challan && jobWorkerHasNoGstin\(detail\.challan\) && \(\s*<JobWorkerStateBox key=\{detail\.challan\.id\} challan=\{detail\.challan\} clientId=\{clientId\} onSaved=\{stateRecorded\} \/>/, "the box is drawn for another condition, or is not keyed by the challan alone (a key that moves with the State remounts the box and drops the focus from its button)");
  assert.equal((tab.match(/<JobWorkerStateBox\b/g) ?? []).length, 1, "the box is drawn from more than one place");
});

test("the State box writes the place of supply and nothing else, offers States and not the place-of-supply list, judges no code and says the server's refusal", () => {
  const calls = box.match(/api\.salesCycle\.updateChallan\(/g) ?? [];
  assert.equal(calls.length, 1);
  assert.match(box, /api\.salesCycle\.updateChallan\(challan\.id, clientId, \{ place_of_supply: state \}\)/, "the body carries more than the place of supply");
  assert.ok(!/\bstatus\b\s*:/.test(box), "the box asks for a status");
  for (const banned of [/VALID_STATE_CODES/, /\^\\d/, /is not a state code/, /two-digit/]) assert.ok(!banned.test(box), `the box holds ${banned}`);
  assert.match(box, /res\.error \|\| "That was refused\."/);
  assert.match(box, /role="alert"/);
  assert.match(box, /if \(!state\) \{ setProblem\("Pick the State first\."\); return; \}/, "an empty pick is sent");
  assert.match(box, /if \(state === recorded\) \{ setProblem\("That is the State already recorded\."\); return; \}/, "an unchanged State is sent");
  assert.match(box, /<StateLookup value=\{state\}[\s\S]*?ariaLabel="State of the job worker"/);
  const picker = box.match(/<StateLookup\b[\s\S]*?\/>/)?.[0] ?? "";
  assert.ok(picker.includes("ariaLabel="), "the picker was not found, so the check below would be vacuous");
  assert.ok(!/\bplaceOfSupply\b/.test(picker), "a job worker's State is picked from the place-of-supply list, which adds Other Country and Other Territory");
  assert.match(box, /data-testid="job-worker-state-box"/);
});

test("after the State is taken the tab reads its lists and the open detail again, says so, and leaves the draft correction form alone", () => {
  const fn = /async function stateRecorded\(challanId: string\)[\s\S]*?\n  \}/.exec(tab)?.[0] ?? "";
  assert.ok(fn.length > 0, "the handler was not found, so the checks below would be vacuous");
  assert.match(fn, /setMsg\(\{ type: "ok", text: "The job worker's State was recorded\." \}\)/);
  assert.ok(fn.indexOf("await load()") > -1 && fn.indexOf("await load()") < fn.indexOf("await reopen(challanId)"), "the lists are not read before the detail");
  assert.ok(!/setCorrecting/.test(fn), "a State save closes whatever draft the person has since opened to correct and drops what they typed");
});

test("the State box says what it holds in words that follow the challan's status, shows a recorded value the picker cannot, and keeps focus on its button across a save", () => {
  assert.match(box, /import \{ INDIAN_STATES \} from "@\/lib\/constants\/indianStates";/);
  assert.match(box, /const listed = INDIAN_STATES\.some\(\(s\) => s\.code === recorded\);/, "a recorded value the picker cannot show is not told apart from one it can");
  assert.match(box, /const draft = challan\.status === "draft";/);
  assert.match(box, /Once this challan is issued, the FORM GST ITC-04 statement \$\{who\}/, "a draft is described as if it were already on the statement");
  assert.match(box, /so the statement names this challan until one is/, "an issued challan is not told that it is named");
  assert.match(box, /draft \? "will read" : "reads"/);
  assert.match(box, /is not on the list of States/, "a recorded 96 or 97 shows as an empty picker");
  assert.ok(!/\bclearable\b/.test(box), "the picker can be cleared, but a cleared State is never saved");
  assert.match(box, /useEffect\(\(\) => \{ setState\(shown\); \}, \[shown\]\);/, "the box follows the State the server now records");
  assert.match(box, /The Rule 55 table below shows a place of supply only for an inter-State movement\./);
  assert.ok(!/asks for the job worker's GSTIN/.test(box), "the box states the form's requirement as fact, which the statement's own caveat does not allow");
});
