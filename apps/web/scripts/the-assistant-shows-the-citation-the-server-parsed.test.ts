// The AI Assistant page shows the statutory citation the server parsed, and says
// so when there is none (ai-18).
//
// The defect: POST /api/assistant parses the trailing "Source: Act, Section n"
// line into its own `source` field and strips it from the answer, and the page
// read only `answer` — while telling the CA, in its own welcome text, that every
// answer cites its sections. The reference was worked out and thrown away before
// the CA saw it.
//
// Three states are kept apart on purpose, and this guard pins them: a citation
// (a string), none given ("" — the server also reports a malformed one this way)
// and unknown (`undefined`, a message saved before the field existed or a backend
// one deploy behind). Rendering unknown as "no citation" would accuse an old
// answer of something nobody checked.
//
// Run with: node --experimental-strip-types --test scripts/the-assistant-shows-the-citation-the-server-parsed.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PAGE = stripComments(fs.readFileSync(path.join(WEB, "app/ai-assistant/page.tsx"), "utf8"));

test("the page reads the source the server sends and keeps it with the message", () => {
  assert.match(PAGE, /json\.data\.source/);
  assert.match(PAGE, /role: "assistant", content: reply, source/);
});

test("a citation is rendered under the reply", () => {
  assert.match(PAGE, /\{msg\.source\}/);
});

test("a reply with no citation says so", () => {
  assert.match(PAGE, /No citation given — verify before relying on this/);
});

test("unknown is not rendered as missing", () => {
  // Both the stored-message check and the parse keep `undefined` distinct.
  assert.match(PAGE, /msg\.source !== undefined/);
  assert.match(PAGE, /typeof json\.data\.source === "string" \? json\.data\.source : undefined/);
});

test("only an assistant reply is ever annotated", () => {
  assert.match(PAGE, /msg\.role === "assistant" && msg\.source !== undefined/);
});
