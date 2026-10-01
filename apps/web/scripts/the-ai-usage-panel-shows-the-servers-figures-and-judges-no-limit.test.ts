/**
 * The AI usage panel shows what the server summed and judges no limit (ai-17).
 *
 * WHAT WAS WRONG
 *   Every model attempt left a usage row (migration 465) and nothing summed it, so a firm
 *   could not see what its AI use came to and could not cap it. `/settings/ai` now carries
 *   the figures and one form; `components/settings/AiUsagePanel.tsx` is the panel.
 *
 * THE RULES, each one a way the panel could LIE
 *   * NO LIMIT IS NOT ZERO. A blank box is sent as `null`; the browser never turns "empty"
 *     into 0 and never sends a number the server did not get from the Partner's own text;
 *   * WHAT A LIMIT MAY BE IS THE SERVER'S. The panel holds no maximum, no minimum and no
 *     sentence for a refusal (`validate_limit` owns them), only text → whole number | null;
 *   * the sentence for a reached allowance is the server's (`standing.sentence`), never
 *     composed here, so the screen and the refused call say the same thing;
 *   * NOT READ IS NOT NONE: an `unread` usage is a sentence, not an empty table, and a
 *     figure nobody holds is a dash, never 0;
 *   * a month the server will not accept is never offered: the choices are the server's;
 *   * no figure is a rupee amount: no price lives here;
 *   * the allowance is measured against the CURRENT month and the panel says so;
 *   * a payload field is checked before it is read as a list; a timestamp goes through the
 *     IST helper.
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/the-ai-usage-panel-shows-the-servers-figures-and-judges-no-limit.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (...p: string[]) => fs.readFileSync(path.join(WEB, ...p), "utf8");

const PANEL = read("components", "settings", "AiUsagePanel.tsx");
const CODE = PANEL.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const API = read("lib", "api", "index.ts");

test("the panel is mounted on the AI status page, which is Partner-only", () => {
  const page = read("app", "settings", "ai", "page.tsx");
  assert.match(page, /<AiUsagePanel \/>/);
  assert.match(page, /<RoleGuard allowed=\{\["Partner"\]\}>/);
});

test("a blank box is no limit (null) and anything that is not a whole number is not sent", () => {
  assert.match(CODE, /if \(t === ""\) return \{ ok: true, value: null \}/);
  assert.match(CODE, /\/\^\[0-9\]\+\$\//);
  assert.match(CODE, /Number\.isSafeInteger\(n\)/);
  assert.match(CODE, /if \(!tokens\.ok \|\| !pages\.ok\)/);
  // empty text must never become 0: no `|| 0`, no `?? 0`, no Number("") / parseInt of the raw text
  assert.ok(!/\|\|\s*0\b/.test(CODE) && !/\?\?\s*0\b/.test(CODE),
    "a blank or missing limit must not default to zero");
  assert.ok(!/parseInt\(|parseFloat\(/.test(CODE), "a limit is parsed by the one strict rule");
});

test("the panel holds no maximum, no minimum and no refusal sentence of its own", () => {
  for (const spoken of [/10\s*\*\*\s*12/, /1_?000_?000_?000_?000/, /must be (at least|more than) /i,
                        /cannot be zero/i, /greater than zero/i, /too large/i]) {
    assert.ok(!spoken.test(CODE), `the panel judges a limit itself: ${spoken}`);
  }
  assert.match(CODE, /api\.aiStatus\.setBudget\(tokens\.value, pages\.value\)/);
  assert.match(CODE, /res\.error \|\| "The allowance could not be saved\."/);
});

test("the reached-allowance sentence is the server's", () => {
  assert.match(CODE, /standing\?\.sentence && <Callout tone="problem">\{standing\.sentence\}<\/Callout>/);
  assert.ok(!/used up|allowance for .* has been/i.test(CODE), "the panel composes its own refusal");
});

test("not read is a sentence and nothing held is a dash, never a zero", () => {
  assert.match(CODE, /data\.unread && <Callout tone="attention">\{data\.unread\}<\/Callout>/);
  assert.match(CODE, /typeof n === "number" && Number\.isFinite\(n\) \? COUNT\.format\(n\) : "—"/);
  assert.match(CODE, /usage && \(/, "the figures render only when the usage was read");
  assert.match(CODE, /usage\.truncated/);
});

test("the months offered are the server's, and the current month is the allowance's", () => {
  assert.match(CODE, /arrayOrEmpty<\{ key: string; label: string \}>\(data\.choices\)/);
  assert.match(CODE, /data\.current_month\?\.key/);
  assert.match(CODE, /measured against the current month, not the one chosen above/);
  assert.ok(!/new Date\(|getMonth\(|getFullYear\(/.test(CODE), "the panel works a month out itself");
});

test("no figure is a cost: nothing here prices a token or a page", () => {
  assert.ok(!/₹|\bRs\b|formatPaise|formatWhole|\bper 1[kM]\b|\bpric(e|es|ing)\b|\bcosts?\b/i.test(CODE),
    "the server holds no provider price; neither may this screen");
});

test("payload fields are checked before they are read as lists, and times go through the IST helper", () => {
  assert.match(CODE, /objectWithLists<AiUsage>\(data, "choices", "not_covered"\)/);
  for (const f of ["usage?.by_feature", "usage?.by_day", "data.not_covered", "f.models"]) {
    assert.ok(CODE.includes(`arrayOrEmpty<`) && CODE.includes(f), `${f} is read without a check`);
  }
  assert.match(CODE, /formatIstLabelled\(/);
  for (const raw of [/toLocale\w*String\(/, /\.toISOString\(/, /\.slice\(0,\s*16\)/]) {
    assert.ok(!raw.test(CODE), `a timestamp is formatted by hand: ${raw}`);
  }
});

test("saving is single-flight", () => {
  assert.match(CODE, /if \(saving\) return;/);
  assert.match(CODE, /disabled=\{saving\}/);
});

test("the api helper reads the usage with GET and writes the allowance with PUT, both keys always", () => {
  const block = API.slice(API.indexOf("aiStatus: {"), API.indexOf("gstCreditLedger: {"));
  assert.match(block, /\/api\/ai-status\/usage/);
  assert.match(block, /\/api\/ai-status\/budget/);
  assert.match(block, /method: "PUT"/);
  assert.match(block, /monthly_token_limit: monthlyTokenLimit/);
  assert.match(block, /monthly_page_limit: monthlyPageLimit/);
});
