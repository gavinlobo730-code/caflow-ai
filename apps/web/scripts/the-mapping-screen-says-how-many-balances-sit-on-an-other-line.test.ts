// The Schedule III mapping screen says how many balances sit on an "Other" line because nobody decided (POST-A-097).
//
// WHAT THE SCREEN SAID
//   "37 of 53 active accounts mapped" -- a count of the chart. It measured nothing about the books: an account with no balance counted
//   the same as the one holding the year's deposits, and a CA could not see "N balances, Rs X, present on Other Current Assets
//   because no one chose that". The server now counts it off the lines the statements present (`residual_balances` on
//   `GET /api/accounting/schedule-iii`, from `schedule_iii.residual_balances`), and the screen shows the server's count.
//
// THE RULES HELD HERE, from the browser's side of a figure:
//   * the figure is the server's: the screen does no arithmetic on balances and reads no basis off a line;
//   * a count that could not be read is said to be unread and is never drawn as a nil, and a nil that WAS read is a reading and is said;
//   * lines the server could not judge are named beside the count and are not folded into the nil;
//   * the answer sits in an always-mounted live region and the heavy read does not hold up the mapping itself.
//
// The backend half is `apps/api/tests/test_a_balance_that_sits_on_an_other_line_by_default_is_counted.py`.
//
// Run with: node --experimental-strip-types --test scripts/the-mapping-screen-says-how-many-balances-sit-on-an-other-line.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const PAGE = stripComments(fs.readFileSync(path.join(WEB, "app/accounting/schedule-iii-mapping/page.tsx"), "utf8"));

test("the file is where this guard thinks it is", () => {
  assert.ok(PAGE.length > 5000, `the mapping page read as ${PAGE.length} chars`);
  assert.ok(PAGE.includes("export default function ScheduleIIIMappingPage"), "the page's component was renamed");
});

test("the figure is the server's: asked of the statements endpoint, read off residual_balances, and no sum is made here", () => {
  assert.ok(/api\.accounting\.scheduleIii\(clientId \? \{ client_id: clientId \} : undefined\)/.test(PAGE),
    "the screen does not ask the statements endpoint, for the client chosen or for all");
  assert.ok(/res\.data\?\.residual_balances/.test(PAGE), "the screen does not read residual_balances");
  assert.ok(!/schedule_iii_basis/.test(PAGE), "the screen reads a line's basis itself instead of the server's count");
  assert.ok(!/\.reduce\(|absolute_paise\s*\+|balance_paise|amount_paise/.test(PAGE), "the screen does arithmetic on balances");
});

test("a count that could not be read is said so and is never a nil, and a nil that was read is said", () => {
  assert.ok(/useState<[^>]*\| null \| undefined>\(undefined\)/.test(PAGE), "not-asked, unread and read are not three states");
  assert.ok(/onOther === null/.test(PAGE) && PAGE.includes("so no figure is shown"), "an unread count is not said to be unread");
  assert.ok(PAGE.includes("No balance sits on an “Other” line by default"), "a read nil is not said");
  // The nil's sentence is only reachable from a READ count: it hangs off `onOther &&`, which is false for null and undefined.
  assert.ok(/\{onOther && \(/.test(PAGE), "the nil is reachable without a count having been read");
});

test("lines the server could not judge are named beside the count and not folded into it", () => {
  assert.ok(/onOther\.counts\.unjudged_lines > 0/.test(PAGE) && PAGE.includes("could not be judged either way"),
    "unjudged lines are not named");
});

test("a new client is a new question: the last answer is dropped and the read depends on the client", () => {
  assert.ok(/setOnOther\(undefined\);/.test(PAGE), "the last client's answer is kept while the next is read");
  assert.ok(/return \(\) => \{ live = false; \};\s*\}, \[clientId\]\);/.test(PAGE), "the read does not depend on the client chosen");
});

test("the answer is announced from an always-mounted live region and the read does not hold up the mapping", () => {
  assert.ok(/<div role="status" className="[^"]*">\s*\{onOther === null/.test(PAGE), "the answer is not in an always-mounted live region");
  // A separate effect, with a guard against a late answer for an unmounted page.
  assert.ok(/let live = true;[\s\S]*?return \(\) => \{ live = false; \};/.test(PAGE), "the heavy read is not its own effect with a cancel");
});

test("the tone is attention only when the server counted something", () => {
  assert.ok(/tone=\{onOther\.counts\.accounts > 0 \? "attention" : "note"\}/.test(PAGE), "the tone is not drawn from the count");
});
