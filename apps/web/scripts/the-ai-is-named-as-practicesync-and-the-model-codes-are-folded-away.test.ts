// POST-A-448. The AI features are presented as PracticeSync AI, the provider stays named, and the exact model code is
// shown only under a closed "Technical details". The owner asked on 16-11-2026 why the AI status page led with
// `openai/gpt-oss-120b`; a model code helps only the person diagnosing a failure, and `openai/...` reads as though a
// CA's content goes to OpenAI when Groq serves that model.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const read = (...p: string[]) => readFileSync(join(WEB, ...p), "utf8");
const STATUS = read("app", "settings", "ai", "page.tsx");
const USAGE = read("components", "settings", "AiUsagePanel.tsx");

/** The source with every <TechnicalDetails>…</TechnicalDetails> block cut out: what renders outside the fold. */
function outsideTheFold(code: string): string {
  return code.replace(/<TechnicalDetails\b[\s\S]*?<\/TechnicalDetails>/g, "");
}

/** Every expression that renders a model code. */
const MODEL_EXPRESSIONS = [/\bp\.model\b/, /\bfallbacks\.join\(/, /\bresult\.answered_by\}/, /\bresult\.model\}/,
                           /\bs\.model\b/, /\bf\.models\b/, /\bmodelOf\(/];

test("the fold is cut out of real code: each file holds a TechnicalDetails block", () => {
  for (const code of [STATUS, USAGE]) {
    assert.match(code, /<TechnicalDetails\b/);
    assert.notEqual(outsideTheFold(code), code);
  }
});

test("no model code renders outside Technical details on the status page or the usage table", () => {
  const status = outsideTheFold(STATUS);
  for (const rx of MODEL_EXPRESSIONS.filter((r) => r.source !== "\\bs\\.model\\b" && r.source !== "\\bmodelOf\\(")) {
    assert.ok(!rx.test(status), `the status page renders a model code outside the fold: ${rx}`);
  }
  // `modelOf` and `s.model` live in a helper; the helper is only CALLED inside the fold.
  assert.ok(!/\{modelOf\(/.test(status), "modelOf is called outside Technical details");
  const seenBody = STATUS.slice(STATUS.indexOf("function seen("), STATUS.indexOf("\n}\n", STATUS.indexOf("function seen(")));
  assert.ok(seenBody.length > 0 && !/\.model\b/.test(seenBody), "seen() still prints the model");
  const usage = outsideTheFold(USAGE);
  assert.ok(!/<Th>Models<\/Th>/.test(usage), "the usage table still has a Models column");
  assert.ok(!/f\.models\)\.join/.test(usage), "the usage table renders model codes outside the fold");
});

test("Technical details is a native details element, closed by default", () => {
  const c = read("components", "ai", "TechnicalDetails.tsx");
  assert.match(c, /<details\b/);
  assert.ok(!/\bopen\b(=|\s*>|\s)/.test(c.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "")),
    "the fold must start closed");
});

test("the provider stays named: the card heading, the probe answer and the usage table's provider column", () => {
  assert.match(STATUS, /<h2[^>]*>\{p\.label\}<\/h2>/);
  assert.match(STATUS, /\{p\.label\} answered in/);
  assert.match(USAGE, /f\.provider_label \?\? f\.provider/);
});

test("the features carry the product's name: the server's label, the page titles", () => {
  assert.match(USAGE, /f\.label \?\?/);
  assert.match(STATUS, /title="PracticeSync AI status"/);
  assert.match(read("app", "ai-assistant", "page.tsx"), /title="PracticeSync AI Assistant"/);
  assert.match(read("app", "copilot", "page.tsx"), /title="PracticeSync AI Copilot"/);
});
