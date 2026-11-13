// A WINDOW OF TWO DAYS ON THE PRACTICE'S PROFITABILITY SCREEN IS ASKED FOR ONLY WHEN IT CAN EXIST, AND A BOX THAT IS BLANK IS NOT A DAY NOBODY CHOSE (POST-A-427, the screen half).
//   node --experimental-strip-types --test scripts/the-practice-analytics-window-is-asked-for-only-when-it-can-exist.test.ts
//
// THE DEFECT THIS KEEPS OUT
//   The server answers `period=custom` with `date_from` and `date_to` (routers/analytics._period_range). The screen that offers it has two date boxes, and a box that holds nothing, a day
//   that is not a day, two days in the wrong order or an end after today is a window that cannot exist. A screen that asked for it anyway would be answered with a refusal, or worse (a
//   screen that filled a blank box with a guess, the first of the month, would answer for a window nobody chose and head it with that window's name). The boxes start blank, nothing is asked
//   until the two days are a window, the figures of the window before are not left under the new one's name, and a slow answer to an earlier window is not shown over a newer one.
//
// THE RULES (each read from the source as a rule; each EXECUTED by the browser drive, scripts/drive/scenarios/dates.mjs, whose scenario ids the last test requires)
//   1. The page asks the helper what stops the window (`customWindowProblem`) and the read returns BEFORE any of the three requests when something does, after taking its place in the
//      queue of requests (`++requestId.current`), so an answer still on its way to an earlier window is dropped, and it clears the figures it had.
//   2. The page builds the window only through `analyticsWindowOf`; it names no `period: "custom"` and no `date_from` of its own, and the API client sends the two days only for the custom window.
//   3. The two boxes are the product's date box, named to a screen reader, bounded by India's today (`notAfter={todayIstISO()}`), the last one anchored on the first, and start blank.
//   4. The sentence that stands in place of the figures is the helper's, and the page's "could not be read" panel is not shown over it.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const PAGE = "app/practice/profitability/page.tsx";
const HELPER = "lib/practice/analyticsWindow.ts";
const CLIENT = "lib/api/index.ts";
const DRIVE = "scripts/drive/scenarios/dates.mjs";

/** The body of the page's `load` callback, from its opening to the dependency list that closes it. */
function loadBody(src: string): string {
  const start = src.indexOf("const load = useCallback(async () => {");
  assert.ok(start >= 0, "the page's load callback was not found");
  const end = src.indexOf("}, [period, customFrom, customTo, customProblem]);", start);
  assert.ok(end > start, "the load callback does not depend on the period, both days and the problem that stops the window");
  return src.slice(start, end);
}

test("the read takes its place, clears what it had and returns before any request when something stops the window", () => {
  const body = loadBody(read(PAGE));
  const take = body.indexOf("++requestId.current");
  const stop = body.indexOf("if (customProblem)");
  const firstRequest = body.search(/api\.analytics\./);
  assert.ok(take >= 0 && stop > take, "the read does not take its place in the queue of requests before it decides to ask nothing");
  assert.ok(firstRequest > stop, "a request is made before the window is judged");
  const refusal = body.slice(stop, firstRequest);
  assert.ok(/\breturn;/.test(refusal), "a window that cannot exist does not return before the requests");
  for (const clear of ["setProfit(null)", "setRealization(null)", "setConcentration(null)", "setError(null)", "setUnread([])", "setLoading(false)"]) {
    assert.ok(refusal.includes(clear), `the figures of the window before are not cleared by ${clear}`);
  }
});

test("what stops the window is the helper's, asked of India's day, and only for the custom window", () => {
  const src = read(PAGE);
  assert.ok(/const customProblem = period === CUSTOM_WINDOW_ID \? customWindowProblem\(customFrom, customTo, todayIstISO\(\)\) : null;/.test(src),
    "the page does not ask customWindowProblem(from, to, India's day) for the custom window alone");
  assert.ok(/useState\(""\)/.test(src.slice(src.indexOf("const [customFrom"), src.indexOf("const [customFrom") + 140)), "the From box does not start blank");
  assert.ok(/const \[customTo, setCustomTo\] = useState\(""\)/.test(src), "the To box does not start blank");
  assert.equal(/new Date\(\)/.test(src.slice(src.indexOf("const [customFrom"), src.indexOf("const load"))), false, "a day is taken from the browser's clock for the window");
});

test("the page builds the window only through the helper, and the client sends the two days only for the custom window", () => {
  const page = read(PAGE);
  assert.equal(/period:\s*["']custom["']/.test(page), false, "the page builds a custom window by hand");
  assert.equal(/date_from|date_to|dateFrom|dateTo/.test(page), false, "the page names the server's day parameters itself");
  assert.equal((page.match(/analyticsWindowOf\(/g) ?? []).length, 1, "the window is built in more than one place");
  const helper = read(HELPER);
  assert.ok(/return days && ISO_DAY\.test\(days\.from\) && ISO_DAY\.test\(days\.to\)\s*\?\s*\{ period: "custom", dateFrom: days\.from, dateTo: days\.to \}\s*:\s*\{ period: "month" \};/.test(helper),
    "a custom window without two readable days is not the month");
  const client = read(CLIENT);
  const start = client.indexOf("function analyticsWindowQuery(");
  assert.ok(start >= 0, "the client's window query builder was not found");
  const builder = client.slice(start, client.indexOf("\n}\n", start));
  assert.ok(/if \(window\.period === "custom"\) \{\s*if \(window\.dateFrom\) q\.set\("date_from", window\.dateFrom\);\s*if \(window\.dateTo\) q\.set\("date_to", window\.dateTo\);\s*\}/.test(builder),
    "the client does not send the two days for the custom window alone");
  assert.equal(/q\.set\("date_(from|to)"/.test(builder.replace(/if \(window\.period === "custom"\) \{[\s\S]*?\n  \}/, "")), false, "the client sends a day for a window that is not the custom one");
});

test("the two boxes are the product's date box, named, bounded by India's today, the last anchored on the first", () => {
  const src = read(PAGE);
  // An element's text up to its closing `/>`: attributes carry `=>` arrows, so a pattern that stops at the first `>` would cut the box short.
  const box = (label: string) => {
    const at = src.indexOf(`aria-label="${label}"`);
    if (at < 0) return "";
    const open = src.lastIndexOf("<DateInput", at);
    return open < 0 ? "" : src.slice(open, src.indexOf("/>", at));
  };
  const from = box("Profitability from");
  const to = box("Profitability to");
  assert.ok(from && to, "the two named date boxes are not on the page");
  for (const [name, text] of [["From", from], ["To", to]] as const) {
    assert.ok(text.includes("notAfter={todayIstISO()}"), `the ${name} box is not bounded by India's today`);
  }
  assert.ok(to.includes("anchor={customFrom || null}") && to.includes("notBefore={customFrom || null}"), "the To box is not anchored on the From day");
  assert.equal(/type=["']date["']/.test(src), false, "a native date input is on the screen");
});

test("the sentence stands in place of the figures, and the 'could not be read' panel is not shown over it", () => {
  const src = read(PAGE);
  assert.ok(/\{period === CUSTOM_WINDOW_ID && \(\s*<div role="status">\s*\{customProblem && \(\s*<div[^>]*>\s*<p[^>]*>\{customProblem\}<\/p>/.test(src),
    "the helper's sentence is not drawn in place of the figures, inside a live region that is mounted before the sentence is");
  assert.ok(src.includes("{!loading && !error && !m && !customProblem && ("), "the 'could not be read' panel is shown over a window that was never asked for");
});

test("the helper's sentences are the ones the server's refusals mirror, and the drive executes each rule", () => {
  const helper = read(HELPER);
  for (const sentence of [
    "Choose the first and the last day of the window to see its figures.",
    "Choose the first day of the window.",
    "Choose the last day of the window.",
    "The To day is before the From day, so there is nothing to show. Put the two days in order.",
    "The To day is after today in India.",
  ]) {
    assert.ok(helper.includes(sentence), `the helper no longer says: ${sentence}`);
  }
  const drive = fs.readFileSync(path.join(WEB, DRIVE), "utf8");
  for (const id of ["profitability-custom-window", "profitability-custom-window-a-late-answer-to-an-earlier-window-is-not-shown"]) {
    assert.ok(drive.includes(`id: "${id}"`), `the drive no longer executes ${id}`);
  }
});

// ── the detectors, tried on the spellings that would evade a looser reading ───────────────────────────────────────────

test("the read-order detector sees a request made before the window is judged", () => {
  const bad = `const load = useCallback(async () => {
    const mine = ++requestId.current;
    api.analytics.profitability(asked);
    if (customProblem) { return; }
  }, [period, customFrom, customTo, customProblem]);`;
  const body = loadBody(bad);
  assert.ok(body.search(/api\.analytics\./) < body.indexOf("if (customProblem)"), "the detector does not see a request ahead of the judgement");
});
