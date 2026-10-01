/**
 * A screen whose content no AI model reads or writes does not wear the AI label
 * (ai-10).
 *
 * WHAT WAS WRONG
 *   The client "AI Insights" tab lists sentences `generate_insights_for_client`
 *   assembles from records — an f-string with a figure interpolated — and the
 *   "AI memory" page lists aggregates of the firm's own rows with threshold rules
 *   over them ("Semantic memory", its subtitle said). Neither reads a model and
 *   nothing feeds either to a prompt. A buyer who opens a screen labelled AI and
 *   finds a rule table has been told something false, and it costs them the
 *   belief in the screens where a model does work (the assistant, document
 *   extraction).
 *
 * THE RULE
 *   Anywhere a rule-based module is NAMED to a user — its page heading, its
 *   navigation entry, its client-tab label, its error boundary — the name does
 *   not begin with "AI". The two modules are listed here by the routes that
 *   serve them, and the list is the claim: adding a module to it is saying "no
 *   model is involved", so it is a decision a reviewer sees.
 *
 *   `a rule-based screen says so` is asserted too: the page carries the words, so
 *   a CA reading it learns what it is rather than only what it is not called.
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/a-rule-based-screen-does-not-wear-the-ai-label.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

/** Comments carry the history of the old labels in the very words forbidden. */
function code(rel: string): string {
  return read(rel)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

test("the client Insights tab is not called AI anywhere a user reads it", () => {
  for (const rel of [
    "app/clients/[id]/ai-insights/page.tsx",
    "app/clients/[id]/ai-insights/error.tsx",
    "lib/workspace/ClientNavContext.tsx",
  ]) {
    const src = code(rel);
    assert.ok(!/\bAI Insights\b|\bAI insights\b/.test(src), `${rel} still says "AI insights"`);
  }
  assert.ok(!/client\("ai-insights", "AI/.test(code("lib/navigation/screens.ts")),
    "the navigation entry for the client Insights tab is labelled AI");
});

test("the client Insights tab says it is rule-based", () => {
  assert.ok(/rule-based/.test(read("app/clients/[id]/ai-insights/page.tsx")));
});

test("the memory page is not called AI and says what it is", () => {
  const src = code("app/memory/page.tsx");
  assert.ok(!/AI Memory|Semantic memory/i.test(src), "the memory page still claims AI or semantic memory");
  assert.ok(/rule-based/.test(read("app/memory/page.tsx")));
  assert.ok(!/firm\("\/memory", "AI/.test(code("lib/navigation/screens.ts")),
    "the navigation entry for /memory is labelled AI");
});

test("the screens where a model DOES work keep the label", () => {
  // The negative control for the rule: it must not have been satisfied by
  // stripping "AI" from everything. The assistant and the copilot are chat with
  // a model; the label is true there.
  assert.ok(/AI Copilot/.test(read("app/copilot/page.tsx")));
  assert.ok(/AI Assistant/.test(read("components/panels/AIPanel.tsx")));
});
