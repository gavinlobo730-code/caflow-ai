// The MFA "Verify" button waits for the factor id it needs before it can be
// pressed at all.
//
// Run with:
//   node --experimental-strip-types --test scripts/mfa-verify-waits-for-the-factor-id.test.ts
//
// WHAT WAS WRONG
//     app/login/page.tsx fetches the verified TOTP factor id asynchronously
//     (supabase.auth.mfa.listFactors(), inside a useEffect keyed off
//     mfaPending flipping true) and used it directly as
//     `mfaFactorId: mfaFactorId` in the challenge call, with the only gate on
//     submission being `mfaCode.length < 6`. A user (or a password manager
//     autofilling the code) who submitted within roughly the round trip that
//     fetch takes posted a challenge with an EMPTY factor id, Supabase
//     rejected it, and the screen showed "Invalid code — check your
//     authenticator app and try again" — misleading, since the code itself
//     may well have been right.
//
// THE FIX
//     The submit button (and therefore an Enter-key implicit submit too) is
//     disabled until `mfaFactorReady` — `mfaFactorId !== ""` — is true, and it
//     reads "Preparing verification…" meanwhile: the UI honestly reflects its
//     own readiness rather than hoping the user waits long enough. A second,
//     independent state (`mfaFactorLoadFailed`) covers the fetch resolving
//     with NO verified factor at all, which is not something retrying fixes
//     and must not leave the button disabled forever with no explanation.
//     `handleMfaSubmit` also refuses at the top as a second line of defence
//     against a submit triggered some way other than a click on the (now
//     disabled) button.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const src = stripComments(fs.readFileSync(path.join(WEB, "app/login/page.tsx"), "utf8"));

test("readiness is its own boolean, derived from the factor id actually being present", () => {
  assert.match(src, /mfaFactorReady\s*=\s*mfaFactorId\s*!==\s*""/,
    "mfaFactorReady must be derived from mfaFactorId, not a separate flag that can drift from it");
});

test("the Verify button's disabled condition includes factor readiness", () => {
  const button = /disabled=\{[^}]*\}/.exec(src.slice(src.indexOf("handleMfaSubmit")));
  assert.ok(button, "could not find a disabled={...} prop after handleMfaSubmit");
  assert.match(button![0], /mfaFactorReady/,
    "the Verify button can still be pressed before the factor id has loaded");
});

test("the button shows it is not ready yet, rather than looking identical to the ready state", () => {
  assert.match(src, /Preparing verification/,
    "no distinct state for 'fetching the factor id, please wait'");
});

test("a load failure is its own state, not indistinguishable from still-loading", () => {
  assert.match(src, /mfaFactorLoadFailed/,
    "listFactors() resolving with no verified factor must not read the same as 'still fetching'");
});

test("the submit handler itself refuses when the factor id is not ready (defence in depth)", () => {
  const start = src.indexOf("async function handleMfaSubmit");
  const end = src.indexOf("\n  return (", start); // the component's own JSX return
  const body = src.slice(start, end === -1 ? undefined : end);
  assert.match(body, /if\s*\(!mfaFactorReady\)\s*return;/,
    "handleMfaSubmit does not guard against running with no factor id");
});
