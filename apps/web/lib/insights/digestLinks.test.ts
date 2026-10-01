/**
 * The morning digest's links and the rules its panel holds (ai-25).
 *
 * The key vocabulary is the server's and is pinned FROM THE PYTHON SIDE
 * (`tests/test_the_practice_digest_is_built_from_the_existing_checks.py` reads
 * `digestLinks.ts`). What is held here is the browser's own half: the routes, and
 * the three things the panel must never do — print an unknown as a number, wear
 * the AI label over a sentence no model wrote, or read a payload's lists
 * unchecked.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { DIGEST_ROUTES, digestClientHref, digestSectionHref } from "./digestLinks.ts";

const WEB = join(import.meta.dirname, "../..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

/** Comments stripped first: a rule stated about SOURCE must not be satisfied, or
 *  broken, by prose describing it. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n").map((l) => l.replace(/(^|[^:])\/\/.*$/, "$1")).join("\n");
}

test("each section leads to the screen it is about", () => {
  assert.equal(digestClientHref("filings_overdue", "c1"), "/clients/c1/compliance");
  assert.equal(digestClientHref("filings_due_soon", "c1"), "/clients/c1/compliance");
  assert.equal(digestClientHref("tasks_overdue", "c1"), "/clients/c1/tasks");
  assert.equal(digestClientHref("books_findings", "c1"), "/clients/c1/accounting?tab=verify-books");
  assert.equal(digestSectionHref("filings_overdue"), "/deadlines");
  assert.equal(digestSectionHref("tasks_overdue"), "/tasks");
});

test("a section with no firm-level screen has no section link, rather than a dead one", () => {
  assert.equal(digestSectionHref("books_findings"), null);
});

test("a key the map does not know falls back to the client's overview and no section link", () => {
  assert.equal(digestClientHref("something_new", "c1"), "/clients/c1/overview");
  assert.equal(digestSectionHref("something_new"), null);
});

test("no client route adds a dynamic segment under /clients/[id]", () => {
  for (const [key, r] of Object.entries(DIGEST_ROUTES)) {
    // Decision D10: a new section there is a query parameter on an existing route.
    assert.match(r.client("x"), /^\/clients\/x\/(compliance|tasks|accounting|overview)(\?tab=[a-z-]+)?$/, key);
  }
});

// ── the panel ────────────────────────────────────────────────────────────────

const panel = code(read("components/insights/DigestPanel.tsx"));

test("the panel never prints a count, so an unknown cannot render as a zero", () => {
  assert.doesNotMatch(panel, /\{\s*it\.count\s*\}/, "a null count would print as nothing or as 0");
  assert.doesNotMatch(panel, /it\.count\s*\?\?\s*0/);
  assert.match(panel, /\{it\.headline\}/, "the server's own sentence is what is shown");
});

test("the AI wording is claimed only when a model wrote the sentence", () => {
  assert.match(panel,
    /digest\.summary_source === "model"\s*\?\s*"The sentence above was worded by AI/);
  const mentions = panel.match(/\bAI\b/g) ?? [];
  assert.equal(mentions.length, 1, "AI appears exactly once, inside the model-only branch");
  assert.match(panel, /Counts: rule-based\./, "the numbers carry the rule-based label either way");
});

test("the panel reads its payload through the shape guards", () => {
  assert.match(panel, /objectWithLists<PracticeDigestPayload>\(res\.data, "items", "gaps"\)/);
  assert.match(panel, /arrayOrEmpty</, "the nested client lists are checked at the read");
});

test("a failed load says so rather than rendering a blank panel", () => {
  assert.match(panel, /The digest could not be read just now\./);
});

test("what the digest does not cover is listed, not hidden", () => {
  assert.match(panel, /What this digest does not cover/);
  assert.match(panel, /<GapList gaps=\{digest\.gaps\}/, "through the shared list, not a hand-rolled one");
});

test("the Insights page shows the digest, and the digest's failure cannot blank the tables", () => {
  const page = code(read("app/insights/page.tsx"));
  assert.match(page, /<DigestPanel \/>/);
  assert.match(page, /import \{ DigestPanel \} from "@\/components\/insights\/DigestPanel"/);
});

test("the api client carries the digest at the route the server serves", () => {
  const api = read("lib/api/index.ts");
  assert.match(api, /digest: \(\) =>\s*request<ApiResp<PracticeDigestPayload>>\("\/api\/intelligence\/digest"\)/);
});
