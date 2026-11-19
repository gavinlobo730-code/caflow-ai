// The reset page is told which page load was opened by a recovery link BEFORE the sign-in library cleans the address (POST-A-510). Run with:
//   node --experimental-strip-types --test scripts/a-recovery-link-is-remembered-before-the-library-cleans-the-address.test.ts
//
// WHAT WAS WRONG
//     /auth/reset-password decided whether to trust an already-established session by reading `window.location` "at first render, before
//     Supabase's own URL cleanup can run". It cannot make that read. The sign-in guard holds every page back until `getSession()` answers,
//     and that answer waits for the library to start, which reads the recovery link, stores its session, clears the hash
//     (`window.location.hash = ''`; the PKCE flow deletes `?code=`) and only then schedules PASSWORD_RECOVERY on a zero-delay timer
//     (auth-js 2.118, GoTrueClient._initialize and _getSessionFromURL, read on 19-11-2026). By the time the page rendered the address held no
//     marker, so the fallback was off, and the page depended on hearing an event a timer may have fired before its listener attached: a valid
//     link could land on "Link invalid or expired". The one attempt to drive the page on 19-11-2026 showed exactly that and was not explained.
//
// WHAT IT DOES NOW
//     `lib/supabase/client.ts` reads the address before it makes the library (`rememberRecoveryLink`), only for a load of the reset page,
//     and the page asks `recoveryLinkWasOpened`; the page forgets the memory when it settles, whichever way. NOT driven in a browser: that
//     needs a real recovery link, which the owner has not yet been through (POST-A-510 stays open for it).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.join(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

test("the client reads the address before it makes the library, in the one place a client is made", () => {
  const src = read("lib/supabase/client.ts");
  assert.match(src, /import \{ rememberRecoveryLink \} from "\.\.\/auth\/recoveryLink\.ts";/);
  const remember = src.indexOf("rememberRecoveryLink(window.location, Date.now())");
  const create = src.indexOf("createClient(url ||");
  assert.ok(remember > 0, "the client no longer reads the address");
  assert.ok(create > 0, "the client's createClient call moved: update this test");
  assert.ok(remember < create, "the address is read AFTER the library is made, which is too late: it has cleaned it by then");
  assert.match(src, /if \(typeof window !== "undefined"\) rememberRecoveryLink/, "a build with no window must not read one");
});

test("no other file makes a browser sign-in client that could read the link first", () => {
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "out") continue;
      const rel = path.posix.join(dir, e.name);
      if (e.isDirectory()) { walk(rel); continue; }
      if (!/\.(ts|tsx)$/.test(e.name) || /\.test\./.test(e.name)) continue;
      const src = read(rel);
      // a client that leaves the address alone (the throwaway one that proves a password) is allowed; one that reads it is not
      const makesOne = /import\s*\{[^}]*\bcreateClient\b[^}]*\}\s*from\s*["']@supabase\/supabase-js["']/.test(src);
      if (makesOne && !/detectSessionInUrl:\s*false/.test(src) && rel !== "lib/supabase/client.ts") offenders.push(rel);
    }
  };
  for (const dir of ["app", "components", "lib"]) walk(dir);
  assert.deepEqual(offenders, [], `these make a sign-in client that would read and clean the address before the reset page can ask: ${offenders.join(", ")}`);
});

test("the reset page asks the memory first and the address second", () => {
  const src = read("app/auth/reset-password/page.tsx");
  assert.match(src, /import \{ forgetRecoveryLink, hasRecoveryMarkerInUrl, recoveryLinkWasOpened \} from "@\/lib\/auth\/recoveryLink";/);
  assert.match(src, /recoveryLinkWasOpened\(Date\.now\(\)\) \|\| hasRecoveryMarkerInUrl\(window\.location\)/);
});

test("the page forgets the memory when it settles, whichever way: an event, an established session, or the wait running out", () => {
  const src = read("app/auth/reset-password/page.tsx");
  assert.match(src, /settled = true;\s*forgetRecoveryLink\(\);\s*setStage\("form"\);/);                       // PASSWORD_RECOVERY
  assert.match(src, /settled = true; forgetRecoveryLink\(\); setStage\("form"\);/);                          // the established session
  assert.match(src, /settled = true; forgetRecoveryLink\(\); setStage\("invalid"\);/);                       // the wait ran out
  assert.equal((src.match(/forgetRecoveryLink\(\)/g) ?? []).length, 3);
});

test("the page's own note says why the address is not read at first render", () => {
  const src = read("app/auth/reset-password/page.tsx");
  assert.match(src, /holds this page back until the library has started/);
  assert.match(src, /POST-A-510/);
});

test("an ordinary session is still not a recovery link: the established-session fallback is gated by the marker", () => {
  const src = read("app/auth/reset-password/page.tsx");
  assert.match(src, /if \(hadRecoveryMarker\) \{\s*supabase\.auth\.getSession\(\)/);
});
