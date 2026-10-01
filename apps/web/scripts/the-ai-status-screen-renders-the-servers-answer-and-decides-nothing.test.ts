/**
 * The AI status screen renders what the server said and decides nothing (ai-06).
 *
 * WHAT WAS WRONG
 *   Nobody could say whether the AI answered at all. The Groq default was changed
 *   after a live `model_not_found` to a name nobody had called, and production
 *   held no usage row and two canned assistant replies. `/settings/ai` is the one
 *   place a Partner reads the answer and presses the button that asks.
 *
 * THE RULES, each one a way the screen could LIE
 *   * every word is the server's: no label table, no tone table and no sentence for
 *     a failure lives in the page (the Schedule III caption lesson — a vocabulary
 *     the backend owns, kept twice, drifts);
 *   * an UNKNOWN status or tone is drawn as needing attention, never as ready: a
 *     frontend that is ahead of its backend must not turn "nobody has asked" green;
 *   * a history that could not be READ is not drawn as an empty history;
 *   * a timestamp is converted to IST through the one helper, never printed raw;
 *   * the check is Partner-only and is not offered for a provider with no key;
 *   * the screen is reachable: the screen list, the Settings rail and the Settings
 *     landing all link it.
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/the-ai-status-screen-renders-the-servers-answer-and-decides-nothing.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (...p: string[]) => fs.readFileSync(path.join(WEB, ...p), "utf8");

const PAGE = read("app", "settings", "ai", "page.tsx");
/** The page's code, with comments and string-free prose stripped of nothing it
 *  needs: the rules below look for tokens, and the header comment names them. */
const CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

test("the page is Partner-only", () => {
  assert.match(CODE, /<RoleGuard allowed=\{\["Partner"\]\}>/);
});

test("the page holds no status label table, no tone table and no failure sentence", () => {
  // The server serves `status_label`, `status_tone` and `result.sentence`.
  for (const word of ["Answering", "Last attempt failed", "Not asked since", "No key set"]) {
    assert.ok(!CODE.includes(word), `the page spells the server's label "${word}" itself`);
  }
  assert.match(CODE, /p\.status_label/);
  assert.match(CODE, /result\.sentence/);
  assert.match(CODE, /p\.status_tone/);
  assert.ok(!/model_gone|empty_reply|rate_limited|provider_error/.test(CODE),
    "the page must not translate the gateway's outcome words; it shows them as served");
});

test("an unknown tone is drawn as needing attention, never as ready", () => {
  assert.match(CODE, /CHIP\[p\.status_tone\]\s*\?\?\s*CHIP\.attention/);
  assert.match(CODE, /result\.tone\s*\?\?\s*"attention"/);
});

test("a history that could not be read is not drawn as an empty history", () => {
  assert.match(CODE, /this_firm_unread/);
  assert.match(CODE, /firm \? \(/, "the firm's rows render only when the history was read");
});

test("every timestamp goes through the IST helper", () => {
  assert.match(CODE, /formatIstLabelled\(/);
  for (const raw of [/toLocale\w*String\(/, /new Date\(/, /\.toISOString\(/, /\.slice\(0,\s*16\)/]) {
    assert.ok(!raw.test(CODE), `a timestamp is formatted by hand: ${raw}`);
  }
});

test("the check is not offered for a provider with no key, and is one request per provider", () => {
  assert.match(CODE, /disabled=\{busy \|\| !p\.configured\}/);
  assert.match(CODE, /api\.aiStatus\.probe\(provider\)/);
  assert.ok(!/Promise\.all\(/.test(CODE),
    "two providers in parallel would each spend the gateway's whole budget against one 45 s abort");
});

test("a payload field is checked before it is read as a list", () => {
  assert.match(CODE, /objectWithLists<AiStatus>\(data, "providers", "not_covered"\)/);
  assert.match(CODE, /arrayOrEmpty<string>\(p\.fallback_models\)/);
});

test("the screen is registered, in the rail, and linked from the Settings landing", () => {
  assert.match(read("lib", "navigation", "screens.ts"), /firm\("\/settings\/ai",/);
  assert.match(read("components", "panels", "SettingsPanel.tsx"), /href: "\/settings\/ai"/);
  assert.match(read("app", "settings", "page.tsx"), /href="\/settings\/ai"/);
});

test("the api helper asks the two routes and probes with POST", () => {
  const api = read("lib", "api", "index.ts");
  assert.match(api, /"\/api\/ai-status"/);
  assert.match(api, /\/api\/ai-status\/probe\?/);
  const probe = api.slice(api.indexOf("aiStatus: {"), api.indexOf("gstCreditLedger: {"));
  assert.match(probe, /method: "POST"/);
});
