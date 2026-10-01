// THE FIRST TWO SCREENS A PERSON SEES NAME THEIR FIELDS TO THE BROWSER.
//   node --experimental-strip-types --test scripts/the-sign-in-and-sign-up-screens-name-their-fields.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT (frontend_ux-12)
// ─────────────────────────────────────────────────────────────────────────────
// `app/login/page.tsx` and `app/signup/page.tsx` drew their labels as bare
// `<label>` elements and their boxes as bare `<input>`s: no `htmlFor`, no `id`,
// no `name`, no `autoComplete`. Three things follow, and each one is invisible
// to a sighted person with a mouse, which is how it survived:
//
//   * A SCREEN READER announces "edit text" with no name, because a label that
//     is not tied to its box by `htmlFor`/`id` is just text next to it, and
//     Playwright's `getByLabel('Email address')` finds nothing.
//   * A PASSWORD MANAGER cannot tell which box is the account name and which is
//     the secret, so the browser does not offer the saved credential. The
//     sign-in form is the one place every staff member types a password every
//     day.
//   * THE AUTHENTICATOR-CODE BOX was `inputMode="numeric"` and nothing else, so
//     a phone that has just received the code by SMS, or a manager holding the
//     TOTP, had no `one-time-code` field to offer it into. The box is shown to
//     exactly the people who are already mid-task on a second device.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE
// ─────────────────────────────────────────────────────────────────────────────
// On a sign-in or sign-up screen —
//   1. EVERY `<label>` carries `htmlFor`, and a literal `htmlFor="x"` has an
//      input with `id="x"` in the same file (a computed `htmlFor={id}` must meet
//      an `id={id}` on an input);
//   2. EVERY `<input>` carries `id`, `name` and `autoComplete`;
//   3. a `type="password"` box is `current-password` or `new-password`, a
//      `type="email"` box is `username` or `email`, and a numeric-keypad code
//      box is `one-time-code`.
//
// `username` rather than `email` is what the sign-in box carries, although the
// finding said `email`: on a sign-in form the email IS the account name, and
// `username` is the token a password manager pairs with `current-password`. On
// the sign-up form, which has no password at all (the account is opened from the
// emailed link), it is `email`, and nothing there may claim `new-password`.
//
// THE OTHER SIGN-IN SURFACES ARE NOT FIXED BY THIS CHANGE, and the list below
// says so instead of pretending: it is a FROZEN LIST that can only shrink. A
// page leaves it by being fixed, and a page that is fixed while still listed
// fails the test that asks whether the exemption is still true — the same shape
// `an-object-payload-is-not-its-fields-until-it-is-checked` uses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");

/** The screens this change fixes and the rule is held against, with the fewest
 *  `<input>` elements each must show — a floor so a scan that reads nothing
 *  cannot pass. Sign-in has three (code, email, password); sign-up draws its
 *  three boxes from ONE `<input>` inside a `.map`, so it shows one. */
const FRONT_DOOR_MIN_INPUTS: Record<string, number> = {
  "app/login/page.tsx": 3,
  "app/signup/page.tsx": 1,
};
const FRONT_DOOR = Object.keys(FRONT_DOOR_MIN_INPUTS);

/** Sibling sign-in and account-setup screens that have the SAME gap and were
 *  outside this finding (found while fixing it). Each is named with what it
 *  lacks. Remove an entry when its page is fixed — the test below fails if you
 *  forget. */
const KNOWN_UNFIXED = [
  "app/login/forgot-password/page.tsx",
  "app/auth/reset-password/page.tsx",
  "app/portal/login/page.tsx",
  "app/portal/activate/page.tsx",
  "app/portal/employee/activate/page.tsx",
];

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}
function read(rel: string): string {
  return stripComments(readFileSync(join(WEB, rel), "utf8"));
}

/** The source of every `<tag …>` opening element, read to its closing `>` with
 *  braces and quotes respected — a regex stops at the `>` of `=>` inside an
 *  `onChange={(e) => …}` and reports half an element. */
function openingTags(src: string, tag: string): string[] {
  const out: string[] = [];
  const start = new RegExp(`<${tag}(?=[\\s/>])`, "g");
  for (const m of src.matchAll(start)) {
    let i = (m.index ?? 0) + m[0].length;
    let depth = 0;
    let quote = "";
    for (; i < src.length; i++) {
      const ch = src[i];
      if (quote) {
        if (ch === "\\") { i++; continue; }
        if (ch === quote) quote = "";
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") { quote = ch; continue; }
      if (ch === "{") depth++;
      else if (ch === "}") depth--;
      else if (ch === ">" && depth === 0) break;
    }
    out.push(src.slice(m.index ?? 0, i + 1));
  }
  return out;
}

const hasAttr = (tag: string, name: string) =>
  new RegExp(`(?:^|\\s)${name}\\s*=`).test(tag);
/** The attribute's literal value, `{expr}` text, or null when absent. */
function attr(tag: string, name: string): string | null {
  const m = new RegExp(`(?:^|\\s)${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|\\{([^}]*)\\})`).exec(tag);
  if (!m) return null;
  return m[1] ?? m[2] ?? `{${m[3]}}`;
}

export function problemsWith(src: string): string[] {
  const problems: string[] = [];
  const inputs = openingTags(src, "input").filter(
    (t) => !/type\s*=\s*"(?:hidden|checkbox|radio|file|submit|button)"/.test(t));
  const labels = openingTags(src, "label");

  for (const l of labels) {
    if (!hasAttr(l, "htmlFor")) problems.push(`a <label> has no htmlFor: ${l.replace(/\s+/g, " ").slice(0, 90)}`);
  }
  const ids = new Set(inputs.map((t) => attr(t, "id")).filter((v): v is string => v !== null));
  for (const l of labels) {
    const target = attr(l, "htmlFor");
    if (target !== null && !ids.has(target)) {
      problems.push(`htmlFor=${JSON.stringify(target)} names no input id`);
    }
  }
  for (const t of inputs) {
    const at = t.replace(/\s+/g, " ").slice(0, 80);
    for (const name of ["id", "name", "autoComplete"]) {
      if (!hasAttr(t, name)) problems.push(`an <input> has no ${name}: ${at}`);
    }
    const ac = attr(t, "autoComplete");
    const type = attr(t, "type");
    if (type === "password" && ac !== null && !["current-password", "new-password"].includes(ac)) {
      problems.push(`a password box is autoComplete=${ac}: ${at}`);
    }
    if (type === "email" && ac !== null && !["username", "email"].includes(ac)) {
      problems.push(`an email box is autoComplete=${ac}: ${at}`);
    }
    if (/inputMode\s*=\s*"numeric"/.test(t) && ac !== null && ac !== "one-time-code") {
      problems.push(`a numeric code box is autoComplete=${ac}, not one-time-code: ${at}`);
    }
  }
  return problems;
}

// ── the checker has to detect, or everything below passes for ever ───────────

test("the checker catches each way a field goes unnamed", () => {
  const bare = `<label className="x">Email</label><input type="email" value={e} onChange={(ev) => setE(ev.target.value)} />`;
  const found = problemsWith(bare).join("\n");
  assert.match(found, /no htmlFor/);
  assert.match(found, /no id/);
  assert.match(found, /no name/);
  assert.match(found, /no autoComplete/, "the arrow function's `>` must not cut the element short");

  assert.match(problemsWith(
    `<label htmlFor="a">A</label><input id="b" name="b" autoComplete="email" />`).join(),
    /names no input id/);
  assert.match(problemsWith(
    `<label htmlFor="p">P</label><input id="p" name="p" type="password" autoComplete="off" />`).join(),
    /password box is autoComplete=off/);
  assert.match(problemsWith(
    `<label htmlFor="c">C</label><input id="c" name="c" inputMode="numeric" autoComplete="off" />`).join(),
    /not one-time-code/);
});

test("the checker passes a correctly named field, and a computed pair", () => {
  assert.deepEqual(problemsWith(
    `<label htmlFor="e">E</label><input id="e" name="email" type="email" autoComplete="username" onChange={(x) => y(x)} />`), []);
  assert.deepEqual(problemsWith(
    `<label htmlFor={id}>E</label><input id={id} name={name} autoComplete={autoComplete} />`), []);
});

// ── the rule, held against the two screens ───────────────────────────────────

for (const rel of FRONT_DOOR) {
  test(`${rel}: every label is tied to a box and every box is named`, () => {
    const src = read(rel);
    assert.ok(openingTags(src, "input").length >= FRONT_DOOR_MIN_INPUTS[rel],
      `${rel}: fewer than ${FRONT_DOOR_MIN_INPUTS[rel]} inputs read — the scan is broken`);
    assert.deepEqual(problemsWith(src), [],
      `${rel} has fields a screen reader, a password manager or a phone's code autofill cannot identify`);
  });
}

test("sign-in: email is the account name, password is current-password, the code is one-time-code", () => {
  const src = read("app/login/page.tsx");
  const byId = (id: string) =>
    openingTags(src, "input").find((t) => attr(t, "id") === id) ?? "";
  assert.match(attr(byId("login-email"), "autoComplete") ?? "", /^(username|email)$/);
  assert.equal(attr(byId("login-password"), "autoComplete"), "current-password");
  const code = byId("login-mfa-code");
  assert.equal(attr(code, "autoComplete"), "one-time-code");
  assert.match(code, /inputMode\s*=\s*"numeric"/, "the digit pad must still come up");
  // Its label is the one Playwright's getByLabel and a screen reader both find.
  assert.match(src, /<label htmlFor="login-mfa-code"[^>]*>Authentication code<\/label>/);
  assert.match(src, /<label htmlFor="login-email"[^>]*>Email address<\/label>/);
  assert.match(src, /<label htmlFor="login-password"[^>]*>Password<\/label>/);
});

test("sign-up: no password box exists, so nothing there claims new-password", () => {
  const src = read("app/signup/page.tsx");
  assert.doesNotMatch(src, /type\s*=\s*"password"/);
  assert.doesNotMatch(src, /new-password/,
    "this screen opens the account from an emailed link — a new-password hint would offer to save a password it never takes");
  for (const token of ["organization", "name", "email"]) {
    assert.match(src, new RegExp(`autoComplete:\\s*"${token}"`), `sign-up has no ${token} field hint`);
  }
});

// ── the exemptions are real, and only ever shrink ────────────────────────────

for (const rel of KNOWN_UNFIXED) {
  test(`${rel} is still listed as unfixed — and still is`, () => {
    const problems = problemsWith(read(rel));
    assert.ok(problems.length > 0,
      `${rel} now passes the rule. Remove it from KNOWN_UNFIXED so the list keeps shrinking.`);
  });
}

test("the unfixed list names files that exist", () => {
  for (const rel of [...FRONT_DOOR, ...KNOWN_UNFIXED]) {
    assert.doesNotThrow(() => readFileSync(join(WEB, rel), "utf8"), `${rel} is listed and does not exist`);
  }
});
