// "Set up Practice" reads the server's answer: a firm with no PAN is told so,
// and the button is not offered when the server says it cannot work. Run with:
//   node --experimental-strip-types --test scripts/the-practice-setup-screen-says-why-it-cannot-set-up.test.ts
//
// WHAT WAS WRONG (PRE-A-003)
//     `provision()` in app/practice/page.tsx was
//         try { await api.practice.provision(); await load(); }
//     It never read the response. `POST /api/practice/provision` answers a firm
//     with no valid PAN as `success: true` with `provisioned: false` and the
//     sentence "Could not provision - the firm has no valid PAN. Set the firm
//     PAN (Settings) and retry.", and `GET /api/practice` already served
//     `can_provision`. Sign-up collects no PAN, so every freshly signed-up firm
//     pressed the button, saw the same "Set up your Practice" screen come back
//     and was told nothing.
//
// THE RULE (not a spelling of today's lines), four limbs
//   1. provision() keeps the response and reads `success` and `provisioned`
//      and shows the server's `message`; a bare `await api.practice.provision();`
//      is the defect.
//   2. The GET is read through `success` too (this router answers a refusal as
//      HTTP 200 {success: false}), and `can_provision` is taken off it.
//   3. The button that runs provision() is disabled on `can_provision === false`
//      (only an explicit false: an absent field is "the server did not say").
//   4. The way out is a permission-gated link to Settings, where the firm PAN
//      is edited (PATCH /api/firms/profile is rbac("firm", "write")).
// No business logic is added: every sentence about PAN validity is the
// server's, and the screen only displays it.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/practice/page.tsx");

/** The text between the braces of `function name(...) { ... }`, or null. */
function functionBody(src: string, name: string): string | null {
  const start = src.search(new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`));
  if (start < 0) return null;
  const open = src.indexOf("{", src.indexOf(")", start));
  if (open < 0) return null;
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(open + 1, i);
  }
  return null;
}

/** What is wrong with a provision() body, as sentences (empty when nothing). */
function provisionProblems(body: string | null): string[] {
  if (body === null) return ["provision() is missing"];
  const out: string[] = [];
  if (/^\s*await\s+api\.practice\.provision\(\)\s*;?\s*$/m.test(body) ||
      /\btry\s*\{\s*await\s+api\.practice\.provision\(\)/.test(body)) {
    out.push("the response of api.practice.provision() is thrown away (a bare await)");
  }
  const assigned = body.match(/(?:const|let)\s+(\w+)\s*=\s*await\s+api\.practice\.provision\(\)/);
  if (!assigned) {
    out.push("api.practice.provision() is not assigned to anything, so nothing can read it");
    return out;
  }
  const r = assigned[1];
  if (!new RegExp(`\\b${r}\\??\\.success\\b`).test(body)) out.push(`${r}.success is never read`);
  if (!/\bprovisioned\b/.test(body)) out.push("`provisioned` is never read");
  if (!/\bmessage\b/.test(body)) out.push("the server's `message` is never read");
  return out;
}

const raw = fs.readFileSync(PAGE, "utf8");
const code = stripComments(raw);

test("the Practice set-up screen says why it cannot set up", async (t) => {
  await t.test("provision() reads the server's answer and shows its sentence", () => {
    assert.deepEqual(provisionProblems(functionBody(code, "provision")), []);
    // ...and puts the sentence on the screen rather than into a variable nobody renders.
    assert.match(code, /\{provisionNotice\}/, "the notice state is never rendered");
  });

  await t.test("the status read goes through success and takes can_provision", () => {
    const load = code.slice(code.indexOf("const load = useCallback"));
    assert.match(load.slice(0, 1400), /api\.practice\.get\(\)/);
    assert.match(load.slice(0, 1400), /!\s*p\?*\.success/,
      "load() must check success on GET /api/practice");
    assert.match(load.slice(0, 1400), /can_provision/,
      "load() must read can_provision off GET /api/practice");
  });

  await t.test("the button that runs provision() is disabled on can_provision === false", () => {
    // The element whose onClick calls provision(), up to the end of its opening tag.
    const m = code.match(/<(?:Button|button)\b[^>]*?onClick=\{\s*\(\)\s*=>\s*provision\(\)\s*\}[^>]*?>/s)
      ?? code.match(/<(?:Button|button)\b[^>]*?onClick=\{provision\}[^>]*?>/s);
    assert.ok(m, "no button runs provision()");
    assert.match(m![0], /disabled=\{[^}]*canProvision\s*===\s*false/,
      "the set-up button does not honour can_provision (only an explicit false disables it)");
  });

  await t.test("the way out is a gated link to Settings", () => {
    const m = code.match(/<EmptyStateAction\b[^>]*href="\/settings"[^>]*\/>/s);
    assert.ok(m, "no EmptyStateAction links to /settings");
    // Same pair PATCH /api/firms/profile is gated on (routers/firms.py).
    assert.match(m![0], /requires=\{\[\s*"firm"\s*,\s*"write"\s*\]\}/);
  });

  await t.test("negative control: the old provision() and an ungated button are caught", () => {
    const old = functionBody(
      "async function provision() { setProvisioning(true); try { await api.practice.provision(); await load(); } " +
        "catch (e) { setError('x'); } finally { setProvisioning(false); } }",
      "provision");
    assert.ok(provisionProblems(old).length >= 1);
    const good = functionBody(
      "async function provision() { const r = await api.practice.provision(); " +
        "if (!r?.success) { setN(r.error); return; } const d = r.data; " +
        "if (!d?.provisioned) { setN(d?.message); return; } }",
      "provision");
    assert.deepEqual(provisionProblems(good), []);
  });
});
