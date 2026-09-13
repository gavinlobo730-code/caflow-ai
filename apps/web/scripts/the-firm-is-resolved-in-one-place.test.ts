// The current user's firm is resolved in exactly ONE place, and that place
// caches. Run with:
//   node --experimental-strip-types --test scripts/the-firm-is-resolved-in-one-place.test.ts
//
// WHAT WENT WRONG
//     `lib/data/getFirmId.ts` has existed the whole time. It reads
//     users.firm_id keyed on the session's auth_user_id, caches the answer for
//     five minutes, and throws one sentence a CA can act on ("No firm found —
//     please complete onboarding first").
//
//     On 2026-09-13 there were TWELVE other copies of it: nine top-level
//     `async function getFirmId()` definitions, two written inline, and one
//     inside lib/data/clients.ts's own createClient. Every one was uncached, so
//     each screen made its own users round trip on every load, and three of
//     them — app/income-tax, app/documents and lib/data/clients — used
//     `.single()` where the shared one uses `.maybeSingle()`. `.single()` on
//     zero rows returns a PostgREST error object rather than null, so a user
//     without a firm row got a raw database message instead of the onboarding
//     sentence.
//
//     They were not a deliberate variation. They were a copy that spread.
//
// WHY THE RULE IS THE QUERY AND NOT THE FUNCTION NAME
//     A guard spelled "no file may define its own `getFirmId`" would have found
//     nine of the twelve and passed on app/DashboardContent.tsx, app/gst and
//     lib/data/clients.ts, which did the same lookup inline with no function
//     around it. CLAUDE.md records the same mistake being made once already, on
//     the money parser: three regexes each naming one SPELLING passed on
//     sixteen files that used a fourth.
//
//     So the rule is the OPERATION: resolving a firm from the users table by
//     auth_user_id. However it is spelled, wherever it is written, it belongs
//     in the helper.
//
// WHAT IS DELIBERATELY STILL ALLOWED, AND WHY THAT LINE IS WHERE IT IS
//     Reading the users table for anything else. The team screen lists members,
//     the work-allocation screen loads assignees, the year-end dashboard joins
//     names — none of those is "which firm am I in". The check keys on
//     `auth_user_id` for that reason: it is what makes a query a lookup of the
//     CURRENT user.
//
//     But two files DO look up the current user's own row by auth_user_id and
//     are still not this defect, and the rule distinguishes them without an
//     exemption list. app/team/page.tsx selects eight columns of that row and
//     lib/auth/AuthContext.tsx selects role, firm_id and full_name — they need
//     the ROW, and getUserProfile() returns three ids and no role. So the
//     offence is narrowed to a query whose select list is `firm_id` ALONE:
//     that query has no reason to exist outside the helper, and a query that
//     asks for more is asking a different question.
//
//     One real exemption remains, and it is not a style call: app/onboarding
//     POLLS for the firm to appear while it is being created, and a cache with
//     a five-minute TTL is exactly wrong there. (The helper caches only a
//     SUCCESSFUL lookup — a missing firm is never cached — so onboarding
//     finishing does not leave a stale "no firm" behind for other screens.)

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");

/** THE one implementation. Everything else imports from it. */
const THE_HELPER = "lib/data/getFirmId.ts";

// `scripts` holds the guards themselves, this one included; their example
// strings are the pattern by construction.
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", "public", ".git", "scripts"]);

/** app/onboarding POLLS for the firm while it is being created, so the helper's
 *  five-minute cache is exactly the wrong shape there. The only exemption. */
const THE_ONE_EXEMPTION = "app/onboarding/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "");
}

function sources(): string[] {
  const found: string[] = [];
  (function walk(dir: string) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (SKIP.has(e.name)) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name)) found.push(path.relative(ROOT, p));
    }
  })(ROOT);
  return found.sort();
}

/** A PostgREST chain on the users table that filters on auth_user_id — the
 *  current user's own row, however the chain is spelled or wrapped.
 *
 *  `[\s\S]*?` rather than `.*?` because every real copy spans several lines,
 *  and the two halves are anchored in the order the builder writes them —
 *  `.from("users")` first, `.eq("auth_user_id", …)` after. Non-greedy and
 *  length-capped, so it cannot span from one query's `.from` to a later
 *  query's `.eq`. */
const OWN_USER_ROW = /\.from\(\s*["']users["']\s*\)[\s\S]{0,400}?\.eq\(\s*["']auth_user_id["']/g;

/** …selecting firm_id AND NOTHING ELSE. That query is the lookup; one that asks
 *  for the row's other columns is asking a different question the helper does
 *  not answer. */
const ONLY_FIRM_ID = /\.select\(\s*["']\s*firm_id\s*["']\s*\)/;

/** Every window this file opens with `.from("users") … .eq("auth_user_id"`. */
function firmLookups(src: string): string[] {
  return [...src.matchAll(OWN_USER_ROW)].map((m) => m[0]);
}

test("only lib/data/getFirmId.ts resolves the current user's firm", () => {
  const offenders = sources()
    .filter((f) => f !== THE_HELPER && f !== THE_ONE_EXEMPTION)
    .filter((f) => firmLookups(code(f)).some((w) => ONLY_FIRM_ID.test(w)));

  assert.deepEqual(offenders, [],
    "these resolve the current user's firm themselves:\n  "
    + offenders.join("\n  ")
    + `\n\nImport { getFirmId } from "@/lib/data/getFirmId" instead. It caches `
    + "for five minutes, uses .maybeSingle() so a user with no firm gets the "
    + "onboarding sentence rather than a PostgREST error, and is the one place "
    + "that has to change if the lookup ever does. If the screen needs the "
    + "users-table id or the auth id too, getUserProfile() returns all three.");
});

test("the one exemption still needs to be one", () => {
  // An exemption that stops applying is an assertion about nothing.
  assert.ok(firmLookups(code(THE_ONE_EXEMPTION)).some((w) => ONLY_FIRM_ID.test(w)),
    `${THE_ONE_EXEMPTION} no longer resolves a firm itself — delete the exemption`);
});

test("nothing declares a second getFirmId", () => {
  // The weaker half of the rule, kept because it is the shape the copies
  // actually took and it catches a re-export or a wrapper that would satisfy
  // the query rule by delegating to something else.
  const DECLARES = /^\s*(?:export\s+)?(?:async\s+function\s+getFirmId\b|(?:const|let|var)\s+getFirmId\s*[:=])/m;
  const offenders = sources()
    .filter((f) => f !== THE_HELPER)
    .filter((f) => DECLARES.test(code(f)));

  assert.deepEqual(offenders, [],
    "these declare their own getFirmId:\n  " + offenders.join("\n  ")
    + "\n\nThere is one, in lib/data/getFirmId.ts.");
});

test("the helper is still the thing being pointed at", () => {
  // A guard that names a file has to fail when the file moves, or it silently
  // becomes an assertion about nothing.
  const src = fs.readFileSync(path.join(ROOT, THE_HELPER), "utf8");
  assert.ok(firmLookups(src).length > 0,
    `${THE_HELPER} no longer performs the lookup this check exempts it for`);
  assert.match(src, /export async function getFirmId\b/,
    `${THE_HELPER} no longer exports getFirmId`);
  assert.match(src, /maybeSingle\(\)/,
    `${THE_HELPER} must use .maybeSingle() — .single() turns "no firm yet" into `
    + "a raw PostgREST error, which is the difference two of the eleven copies had");
});

/** True when the source contains the offence the first test bans. */
const offends = (src: string) => firmLookups(src).some((w) => ONLY_FIRM_ID.test(w));

test("the rule is stated over the operation, not over a name", () => {
  // A regression guard for the guard, in the shape
  // a-day-count-comes-from-the-one-helper.test.ts uses.
  assert.ok(offends(
    `const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();`),
    "the one-line spelling nine copies used");
  assert.ok(offends(
    `await sb\n  .from("users")\n  .select("firm_id")\n  .eq("auth_user_id", session.user.id)\n  .single();`),
    "the multi-line spelling app/income-tax and app/documents used");
  assert.ok(offends(
    `await supabase.from("users").select("firm_id").eq("auth_user_id", user!.id).maybeSingle()`),
    "the INLINE spelling, with no function around it — a name-based rule missed this");

  assert.ok(!offends(
    `sb.from("users").select("id, full_name, email, role").eq("firm_id", firmId)`),
    "listing a firm's members is a different question and must stay legal");
  assert.ok(!offends(
    `sb.from("users").select("role, firm_id, full_name").eq("auth_user_id", user.id)`),
    "AuthContext needs the ROW, not the firm — getUserProfile() has no role");
  assert.ok(!offends(
    `sb.from("users").select("id, full_name, email, role, is_active, created_at, firm_id, auth_user_id").eq("auth_user_id", a)`),
    "the team screen needs eight columns of its own row");
  assert.ok(!offends(
    `sb.from("client_portal_users").select("firm_id").eq("auth_user_id", uid)`),
    "a PORTAL principal resolving their own firm is a different lookup — they "
    + "have no `users` row at all, which is why lib/data/getFirmId cannot serve "
    + "them and why the rule keys on the TABLE as well as the column");
  assert.ok(!offends(
    // A REAL table and a REAL column, because two other guards scan apps/web
    // and cannot tell an example from a query:
    // tests/test_frontend_tables_exist.py checks every `.from("…")` name
    // against the migrations, and test_frontend_columns_exist_pg.py checks
    // every `.eq("…")` against the real schema. This example failed both in
    // turn: first with a made-up one-letter table name, then with a real table
    // that has no auth_user_id column. Neither scanner strips comments either,
    // so do not write an example query in one.
    `sb.from("users").select("firm_id");\n${"x\n".repeat(300)}sb.from("client_portal_users").eq("auth_user_id", u)`),
    "a later query's filter must not be pulled onto an earlier query's from");
});
