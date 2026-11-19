// Every password box can show what was typed, and each box's eye hides only its own box (POST-A-513).
//
// Run with:
//   node --experimental-strip-types --test scripts/every-password-box-can-show-what-was-typed.test.ts
//
// WHY
//     The owner asked for an eye on the staff sign-in screen, the only password screen without one; and on Settings > Security one
//     `showPw` setting drove the current, new and confirm boxes while only the new-password box carried the eye, so his screenshot
//     showed the current password in clear text with no eye beside it. The portal sign-in and the bank statement's PDF password were
//     the same. `components/auth/PasswordField` is the one box now.
//
// THE RULE, NOT A SPELLING OF IT
//     No screen draws an `<input type="password">` of its own: a literal password type is a box that cannot be uncovered. (A box that
//     toggles its own `type` is drawn with a computed type and has its own eye; PasswordField is the shared form of it.) The field's
//     eye is a real button with a name built from the box's own label and a pressed state, and the Settings > Security boxes are
//     three fields with three labels and no setting shared between them.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
      const rel = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== "node_modules") walk(rel); continue; }
      if (/\.tsx$/.test(e.name) && !/\.test\./.test(e.name)) out.push(rel);
    }
  };
  for (const root of ["app", "components"]) walk(root);
  return out;
}

test("no screen draws a password box that cannot be uncovered", () => {
  const offenders = sourceFiles()
    .filter((f) => f !== path.join("components", "auth", "PasswordField.tsx"))
    .filter((f) => /<input\b[^>]*\btype="password"/s.test(stripComments(read(f))));
  assert.deepEqual(offenders, [], "an <input type=\"password\"> with a literal type has no eye: draw it with components/auth/PasswordField");
});

test("the eye is a button with a name from the box's own label and a pressed state", () => {
  const src = stripComments(read("components/auth/PasswordField.tsx"));
  assert.match(src, /<button\s+type="button"/);
  assert.match(src, /aria-label=\{shown \? `Hide \$\{label\}` : `Show \$\{label\}`\}/);
  assert.match(src, /aria-pressed=\{shown\}/);
  assert.match(src, /useState\(false\)/, "each box keeps its own shown setting");
});

test("Settings > Security: three boxes, three eyes, three names, and no setting shared between them", () => {
  const src = stripComments(read("app/settings/security/page.tsx"));
  const labels = [...src.matchAll(/<PasswordField\b[^>]*?\blabel="([^"]+)"/gs)].map((m) => m[1]);
  assert.equal(labels.length, 3, "the Change Password card draws three password boxes");
  assert.equal(new Set(labels).size, 3, "two boxes share a name, so a person cannot tell their eyes apart");
  assert.ok(!/\bshowPw\b/.test(src), "one setting still drives more than one box");
});

test("the sign-in boxes keep what the browser's saved-password fill looks for", () => {
  for (const f of ["app/login/page.tsx", "app/portal/login/page.tsx"]) {
    const src = stripComments(read(f));
    assert.match(src, /<PasswordField[^>]*\bname="password"[^>]*\bautoComplete="current-password"/s, `${f}: name and autoComplete`);
  }
});

test("the shared field hands its id, name and autoComplete to the one <input> it renders, and flips only the type", () => {
  const src = stripComments(read("components/auth/PasswordField.tsx"));
  const input = /<input\b[\s\S]*?\/>/.exec(src)?.[0] ?? "";
  assert.match(input, /id=\{id\}/);
  assert.match(input, /name=\{name\}/);
  assert.match(input, /autoComplete=\{autoComplete\}/);
  assert.match(input, /type=\{shown \? "text" : "password"\}/);
  assert.equal([...src.matchAll(/<input\b/g)].length, 1, "the field renders exactly one input");
});
