// Settings > Security's Change Password: the current password is proved on a throwaway client, sent again in the update itself, and
// every refusal is words (POST-A-512).
//
// Run with:
//   node --experimental-strip-types --test scripts/change-password-sends-the-current-password-and-leaves-the-session-alone.test.ts
//
// WHY
//     Live on 19-11-2026 at 16:04 IST the sign-in service refused the owner's change with `current_password_required` (HTTP 400): the
//     project's "Require current password when updating" switch was on and the card never sent the current password. It had proved
//     it with `signInWithPassword` on the browser's own client, which REPLACES the browser's session (a new token, a first-level
//     assurance for a person with an authenticator, the page rebuilt under the answer), and the refusal was set on a page that had
//     gone, so the screen said nothing at all.
//
// THE RULE, NOT A SPELLING OF IT
//     The card makes NO sign-in on any client of its own: the proof is `verifyCurrentPassword` on `makeEphemeralAuthClient`, a client
//     that keeps nothing. The update carries `current_password`, so does the reauthentication branch, and every sentence that comes
//     from the service goes through `refused()`, which keeps it for the next page if this one was unmounted.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

function cardOf(): string {
  const src = stripComments(read("app/settings/security/page.tsx"));
  const a = src.indexOf("function ChangePasswordCard()");
  const b = src.indexOf("function MfaCard()");
  assert.ok(a >= 0 && b > a, "the Change Password card was not found");
  return src.slice(a, b);
}

test("the card makes no sign-in of its own: the browser's session is never replaced to prove a password", () => {
  const card = cardOf();
  assert.ok(!/signInWithPassword\s*\(/.test(card), "the card calls signInWithPassword: that replaces the browser's session (POST-A-512)");
  assert.match(card, /verifyCurrentPassword\(\s*user\.email,\s*current,\s*makeEphemeralAuthClient\s*\)/, "the proof is not made on the throwaway client");
});

test("the update carries the current password, and so does the reauthentication branch", () => {
  const card = cardOf();
  assert.match(card, /updateUser\(\{\s*password:\s*next,\s*current_password:\s*current\s*\}\)/, "updateUser does not send current_password");
  assert.match(card, /setPasswordWithReauthNonce\(\s*supabase\.auth,\s*next,\s*reauthOtp,\s*current\s*\)/, "the reauthentication branch drops current_password");
});

test("every sentence that comes from the service goes through refused(), which survives a rebuilt page", () => {
  const card = cardOf();
  const direct = [...card.matchAll(/setError\(([^;]*?)\);/g)].map((m) => m[1].trim());
  for (const arg of direct) {
    const ok = arg === "null" || /^"[^"]*"$/.test(arg) || arg === "sentence" || arg === "rulesProblem";
    assert.ok(ok, `setError(${arg}) puts a computed sentence on a page that may have gone: use refused()`);
  }
  assert.match(card, /function refused\(sentence: string\)\s*\{[^}]*rememberPasswordRefusal\(sentence\)/, "refused() does not keep the sentence for the next page");
  assert.match(card, /useState<string \| null>\(\(\) => takePasswordRefusal\(\)\)/, "the card does not read a refusal an earlier mount left");
  assert.ok(!/setError\(authErrorMessage/.test(card), "a service refusal is set straight on the page");
});

test("the throwaway client holds nothing: no stored session, no refresh, no address read, its own storage key", () => {
  const src = stripComments(read("lib/supabase/client.ts"));
  const a = src.indexOf("export function makeEphemeralAuthClient");
  assert.ok(a >= 0, "makeEphemeralAuthClient is missing");
  const fn = src.slice(a, src.indexOf("\n}\n", a) + 3);
  assert.match(fn, /persistSession:\s*false/);
  assert.match(fn, /autoRefreshToken:\s*false/);
  assert.match(fn, /detectSessionInUrl:\s*false/);
  assert.match(fn, /storageKey:\s*"ps-password-check"/);
  assert.match(fn, /fetch:\s*plainRestFetch/, "the throwaway client is not given the product's fetch");
});

test("the browser still makes its Supabase clients in ONE module", () => {
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
      const rel = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== "node_modules") walk(rel); continue; }
      if (!/\.(ts|tsx)$/.test(e.name) || /\.test\./.test(e.name)) continue;
      if (rel === path.join("lib", "supabase", "client.ts")) continue;
      if (/from "@supabase\/supabase-js"/.test(read(rel)) && /\bcreateClient\s*\(/.test(stripComments(read(rel)))) offenders.push(rel);
    }
  };
  for (const root of ["app", "lib", "components"]) walk(root);
  assert.deepEqual(offenders, [], "a Supabase client is made outside lib/supabase/client.ts: it would not have plainRestFetch");
});
