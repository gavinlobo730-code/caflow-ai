// An example in a form field is a made-up example, never a real person.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-placeholder-does-not-name-a-real-person.test.ts
//
// WHY
//     Onboarding's Full Name field read "e.g. CA Gavin Lobo" — the owner's own
//     name — so every CA who signed up was shown it as the example of what to
//     type, and Settings used the same name for the Full Name, the Firm Name
//     and the bank Account Holder. The sign-up page already used a neutral
//     "e.g. CA Ravi Sharma"; the others now match it.
//
// THE RULE
//     Every placeholder in the product and the marketing site — a JSX
//     `placeholder=` attribute or a `placeholder:` key in a field list — is
//     read, and none may carry a name belonging to the owner or their accounts.
//     Tests, fixtures and docs are out of scope: they are not shown to a CA.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const APPS = path.resolve(WEB, "..");
const ROOTS = [
  "web/app", "web/components", "web/lib",
  "marketing/app", "marketing/components", "marketing/lib",
];

const OWNER = /gavin|lobo|derick|knightgaming/i;

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(tsx|ts|jsx|js)$/.test(e.name) && !/\.test\.[jt]sx?$/.test(e.name)) out.push(p);
    }
  };
  for (const r of ROOTS) walk(path.join(APPS, r));
  return out;
}

/** Every literal a placeholder is given: `placeholder="…"`, `placeholder={"…"}`, `placeholder: "…"`. */
function placeholders(src: string): string[] {
  const out: string[] = [];
  const re = /\bplaceholder\s*(?:=\s*\{?\s*|:\s*)(["'`])((?:\\.|(?!\1)[^\\])*)\1/g;
  for (const m of stripComments(src).matchAll(re)) out.push(m[2]);
  return out;
}

test("the scan reads each way a placeholder is written", () => {
  const sample = `
    <input placeholder="e.g. A" />
    <input placeholder={'e.g. B'} />
    <input placeholder={\`e.g. C\`} />
    { label: "Name", placeholder: "e.g. D" }
  `;
  assert.deepEqual(placeholders(sample), ["e.g. A", "e.g. B", "e.g. C", "e.g. D"]);
  assert.ok(OWNER.test("e.g. CA Gavin Lobo"));
  assert.ok(!OWNER.test("e.g. CA Ravi Sharma"));
});

test("no placeholder a CA or a visitor sees names the owner", () => {
  let seen = 0;
  const offenders: string[] = [];
  for (const p of sourceFiles()) {
    for (const ph of placeholders(fs.readFileSync(p, "utf8"))) {
      seen++;
      if (OWNER.test(ph)) offenders.push(`${path.relative(APPS, p)}: ${ph}`);
    }
  }
  // Vacuity floor: the product has several hundred placeholders.
  assert.ok(seen > 200, `only ${seen} placeholders were read — the scan is not reaching the tree`);
  assert.deepEqual(offenders, []);
});
