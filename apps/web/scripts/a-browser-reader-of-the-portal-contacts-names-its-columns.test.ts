// Every browser read of `client_portal_users` names its columns, and none of them names the invite secret.
// Run with:
//   node --experimental-strip-types --test scripts/a-browser-reader-of-the-portal-contacts-names-its-columns.test.ts
//
// WHY THIS EXISTS (POST-B-027, migration 497)
//     `client_portal_users.invite_token` is a live, single-use invite secret (accepting an invite also needs a
//     matching e-mail on the signed-in account, which the code calls defence in depth). Migration 497 takes it out of
//     what a signed-in user may read, column by column, so a `select("*")` from the browser (which would once have put
//     the token on the page's heap and in the
//     network tab) is now a permission error. This is the static half: a reader that would be refused at run time is
//     found at build time, and a reader that names the secret on purpose is found at all.
//
// WHAT THIS DOES NOT DO
//     It reads source. The database half is `apps/api/tests/test_497_..._pg.py`, run against a real Postgres.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !p.includes(`${path.sep}scripts${path.sep}`)) out.push(p);
  }
  return out;
}

/** Every `.from("client_portal_users")` read in the app and the statement it starts (up to the next `;`, capped). */
function readers(): { file: string; stmt: string }[] {
  const found: { file: string; stmt: string }[] = [];
  for (const f of walk(WEB)) {
    const src = code(fs.readFileSync(f, "utf8"));
    const re = /\.from\(\s*["']client_portal_users["']\s*\)/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(src))) {
      const end = src.indexOf(";", m.index);
      found.push({ file: path.relative(WEB, f), stmt: src.slice(m.index, end === -1 ? m.index + 600 : Math.min(end, m.index + 1200)) });
    }
  }
  return found;
}

test("the scan finds the browser readers it is meant to govern", () => {
  const r = readers();
  assert.ok(r.length >= 2, `vacuity: only ${r.length} browser read(s) of client_portal_users found — has the scan broken?`);
});

test("every browser read of the portal contacts names its columns", () => {
  for (const { file, stmt } of readers()) {
    const sel = /\.select\(\s*(["'`])([^"'`]*)\1/.exec(stmt);
    assert.ok(sel, `${file}: a read of client_portal_users with no select list — it would ask for every column`);
    const list = sel![2].trim();
    assert.ok(list !== "" && !list.split(",").some((c) => c.trim() === "*" || c.trim().endsWith(".*")),
      `${file}: select("${list}") on client_portal_users asks for every column, the invite secret included`);
  }
});

test("no browser read names the invite secret", () => {
  for (const { file, stmt } of readers()) {
    assert.doesNotMatch(stmt, /invite_token/, `${file}: a browser read names invite_token — the database refuses it (migration 497)`);
  }
});
