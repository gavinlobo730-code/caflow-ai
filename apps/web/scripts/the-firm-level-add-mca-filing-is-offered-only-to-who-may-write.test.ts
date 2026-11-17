// The firm-level MCA screen's header Add Filing is offered only to someone POST /api/mca-workspace/filings admits (POST-A-442).
//
// The add went through the API (`mca` `write`, which a Reviewer does not hold), and the header button stayed offered to every member, who
// filled in the form and was then refused. The empty state's own Add Filing already asked `requires={["mca", "write"]}`.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-firm-level-add-mca-filing-is-offered-only-to-who-may-write.test.ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const src = strip(readFileSync(new URL("../app/mca/page.tsx", import.meta.url), "utf8"));

test("the header Add Filing is drawn only for someone who may write MCA filings", () => {
  const gate = /const\s+(\w+)\s*=\s*usePermissions\(\)\.can\("mca",\s*"write"\)/.exec(src);
  assert.ok(gate, "the page reads the `mca` `write` permission");
  const button = /\{([^{}]*)\(\s*<button onClick=\{\(\) => setShowModal\(true\)\}/.exec(src);
  assert.ok(button, "the header Add Filing button is found");
  assert.ok(button[1].split("&&").map((s) => s.trim()).includes(gate[1]), `the button's condition (${button[1].trim()}) asks ${gate[1]}`);
});

test("the empty state's Add Filing asks the same pair", () => {
  assert.match(src, /requires=\{\["mca", "write"\]\}.*label="Add Filing"/);
});
