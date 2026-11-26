// A sign-in ends when the browser is closed unless the person asked to stay, and after thirty idle minutes.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-session-ends-when-the-browser-closes-and-when-nobody-is-there.test.ts
//
// WHAT WAS WRONG (POST-A-483; the owner's rule of 18-11-2026, "go as per your suggestions")
//     The sign-in service keeps its session in the browser's long-lived storage by default, so a closed browser stayed
//     signed in for as long as the token could be renewed, and nothing anywhere signed out a screen left alone.
//
// THE LIMIT: no web page can detect a browser close. The rule is the other way round (lib/auth/browserSession): at
// the next page start, is this still the browser session the person signed in during? The decisions are unit-tested
// in lib/auth; this reads that the screens APPLY them.
//
// THE RULES
//     1. a page that starts asks before it uses a stored session: enforceBrowserSession runs before getSession;
//     2. both sign-outs the browser decides on its own (a closed browser, an idle screen) end THIS device only
//        (scope "local"), so the person's other devices are left alone;
//     3. the sign-in tickbox is OFF unless ticked and reaches signIn; an explicit sign-out forgets the keep flag;
//     4. the keeper is mounted once inside the auth provider, counts a key, a pointer, a touch and a wheel but NOT an
//        API call (the app makes some on its own), and says why on the page it sends the person to.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
function code(rel: string): string {
  const src = fs.readFileSync(path.join(WEB, rel), "utf8");
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ").replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, " ");
}

test("a starting page asks about the browser session before it uses a stored session", () => {
  const src = code("lib/auth/AuthContext.tsx");
  // it also tells the server the session it ends is over (POST-A-486), through a recorder it is handed, so the session it leaves behind is closed
  assert.match(src, /enforceBrowserSession\(getSupabaseClient\(\), undefined, \(\) => import\("@\/lib\/api"\)\.then\(\(\{ api \}\) => api\.identity\.recordLoginEvent\("logout"\)\)\)\.catch\(\(\) => "kept"\)\.then\(\(\) => supabase\.auth\.getSession\(\)\)/);
  assert.match(src, /if \(_event === "SIGNED_IN"\) markBrowserSession\(\);/);
});

test("the browser-decided sign-outs end this device only", () => {
  const glue = code("lib/auth/browserSessionGlue.ts");
  assert.match(glue, /client\.auth\.signOut\(\{ scope: "local" \}\)/);
  const ctx = code("lib/auth/AuthContext.tsx");
  assert.match(ctx, /const endSessionHere = useCallback\([\s\S]*?getSupabaseClient\(\)\.auth\.signOut\(\{ scope: "local" \}\)/);
});

test("the sign-in tickbox is off by default, reaches signIn, and a sign-out forgets it", () => {
  const login = code("app/login/page.tsx");
  assert.match(login, /const \[keepSignedIn, setKeepSignedIn\] = useState\(false\)/);
  assert.match(login, /signIn\(email, password, keepSignedIn\)/);
  assert.match(login, /Keep me signed in on this computer/);
  const ctx = code("lib/auth/AuthContext.tsx");
  assert.match(ctx, /rememberKeepSignedIn\(keepSignedIn === true, data\?\.user\?\.id \?\? null\)/);
  assert.match(ctx, /const signOut = useCallback\([\s\S]*?forgetKeepSignedIn\(\);[\s\S]*?await supabase\.auth\.signOut\(\);/);
});

test("the keeper is mounted once, inside the auth provider, and counts what a person does", () => {
  const layout = code("app/layout.tsx");
  assert.equal((layout.match(/<SessionKeeper \/>/g) ?? []).length, 1);
  assert.match(layout, /<AuthProvider>\s*<SessionKeeper \/>/);
  const keeper = code("components/auth/SessionKeeper.tsx");
  for (const ev of ["keydown", "pointerdown", "wheel", "touchstart"]) assert.ok(keeper.includes(`"${ev}"`), `${ev} is not counted as activity`);
  assert.ok(!/api\.|lib\/api|fetch\(/.test(keeper), "an API call must not count as activity: the app makes some on its own");
  assert.match(keeper, /closedAccountPath\("idle"\)/);
  assert.match(keeper, /idleStatus\(Date\.now\(\)/);
  assert.match(keeper, /role="alert"/);
});

test("the decision reads what the page found when it started, and no writer acts before the decision (the independent review's two blockers)", () => {
  const glue = code("lib/auth/browserSessionGlue.ts");
  assert.match(glue, /const startFacts: StartFacts \| null = readStartFacts\(\);/);
  assert.match(glue, /export function markBrowserSession\(\): void \{\s*if \(!decided\) return;/);
  assert.match(glue, /export function beat\(\): void \{\s*if \(!decided\) return;/);
  assert.match(glue, /\} finally \{\s*decided = true;/);
  // the decision is judged by the facts, never by a fresh read of storage the page itself has written to
  const decide = glue.slice(glue.indexOf("export async function enforceBrowserSession"));
  assert.doesNotMatch(decide, /getItem\(MARKER_KEY\)|getItem\(ALIVE_KEY\)|getItem\(KEEP_KEY\)/);
  assert.match(glue, /ALIVE_LOCK_NAME/);
  assert.match(glue, /freshSignIn: urlCarriesASignIn\(/);
});

test("signing out records the logout without waiting on it, once, and an unreadable storage does not stop the idle clock", () => {
  const ctx = code("lib/auth/AuthContext.tsx");
  const end = ctx.slice(ctx.indexOf("const endSessionHere = useCallback"));
  assert.match(end, /if \(!data\.session\) return;/);
  assert.match(end, /Promise\.race\(\[[\s\S]*?LOGOUT_RECORD_WAIT_MS/);
  const keeper = code("components/auth/SessionKeeper.tsx");
  assert.match(keeper, /let memoryActivity: number \| null = null;/);
  assert.match(keeper, /idleStatus\(Date\.now\(\), newestActivity\(\)\)/);
  assert.doesNotMatch(keeper, /idleStatus\(Date\.now\(\), parseActivity\(window\.localStorage/);
});
