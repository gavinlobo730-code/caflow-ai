// A HALF-TYPED FORM IS WARNED ABOUT, KEPT IN THIS TAB, AND OFFERED BACK — NEVER APPLIED (frontend_ux-23).
//   node --experimental-strip-types --test scripts/an-unsent-draft-is-offered-and-never-restored-silently.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// `useUnsavedChanges` (a beforeunload warning and an in-app confirmLeave) was
// wired into six document editors. It was not on the journal editor — where a
// forty-line voucher is the longest thing a CA types — nor the employee drawer,
// the asset drawers or the onboarding wizard, and nothing at all survived a
// refresh. Autosave is deliberately deferred in lib/invoices/dirtyState.ts, so
// what is built here is the smaller thing that closes the loss: warn, and keep
// the typing in this tab so it can be OFFERED back.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULES THIS HOLDS (the logic is unit-tested in lib/drafts/*.test.ts and
// lib/journal/journalDraft.test.ts; these are the ones only the source can say)
// ─────────────────────────────────────────────────────────────────────────────
//  1. A draft lives in sessionStorage and nowhere else. CLAUDE.md allows an
//     unsent draft in the browser as a per-viewer convenience and forbids the
//     user's WORK there (a-browser-only-screen-says-so); localStorage would
//     outlive the tab and be offered to whoever sat down next.
//  2. A draft is OFFERED. `restore()` is called from a click handler and from
//     nowhere else — never from an effect, never on mount.
//  3. A successful save clears it, and only a save does.
//  4. Sign-out clears every draft this module wrote.
//  5. The list of editors that keep drafts is a frozen list (the journal and the
//     purchase bill, the two the finding named): a third is a
//     decision about what may be stored in a browser, not a convenience.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { stripComments } from "./stripComments.ts";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => stripComments(readFileSync(join(WEB, rel), "utf8"));

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(WEB, dir))) {
    if (e === "node_modules" || e === ".next") continue;
    const rel = join(dir, e).replace(/\\/g, "/");
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (/\.(ts|tsx)$/.test(rel) && !rel.endsWith(".test.ts")) out.push(rel);
  }
  return out;
}
const ALL = ["app", "components", "lib"].flatMap((d) => walk(d));

/** The body of `function name(...) { … }` / `async function name`, balanced. */
function functionBody(src: string, name: string): string {
  const at = src.search(new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `function ${name} not found`);
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")" && --depth === 0) { i++; break; }
  }
  const open = src.indexOf("{", i);
  depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(open, j + 1);
  }
  throw new Error(`unbalanced ${name}`);
}

// ═════════════════════════════════════════════════════════════════════════════
// 1. sessionStorage, and only sessionStorage
// ═════════════════════════════════════════════════════════════════════════════

test("the draft modules reach sessionStorage and never localStorage", () => {
  for (const rel of ["lib/drafts/unsentDraft.ts", "lib/drafts/useUnsentDraft.ts"]) {
    const src = read(rel);
    assert.doesNotMatch(src, /localStorage/, `${rel}: a draft that outlived the tab would be work living in a browser`);
  }
  assert.match(read("lib/drafts/unsentDraft.ts"), /window\.sessionStorage/);
});

test("the one place that touches window.sessionStorage does so inside a try", () => {
  const src = read("lib/drafts/unsentDraft.ts");
  const body = functionBody(src, "browserSessionStorage");
  assert.match(body, /try\s*\{[\s\S]*window\.sessionStorage[\s\S]*\}\s*catch/,
    "reading window.sessionStorage can itself throw a SecurityError (blocked site data)");
});

test("nothing outside lib/drafts touches the draft keys directly", () => {
  const offenders = ALL.filter((f) => !f.startsWith("lib/drafts/") && /ps:draft:/.test(read(f)));
  assert.deepEqual(offenders, [], "a second writer of draft keys is a second set of rules");
});

// ═════════════════════════════════════════════════════════════════════════════
// 2. OFFERED, NEVER APPLIED
// ═════════════════════════════════════════════════════════════════════════════

/** Every file that keeps a draft. FROZEN: a third is a decision (rule 5). */
const DRAFT_EDITORS = [
  "components/journal/JournalEditor.tsx",
  "components/purchases/PurchaseBillEditor.tsx",
];

test("the editors that keep drafts are exactly the frozen list", () => {
  const users = ALL.filter((f) => !f.startsWith("lib/drafts/") && /\buseUnsentDraft\s*[<(]/.test(read(f))).sort();
  assert.deepEqual(users, [...DRAFT_EDITORS].sort(),
    "a new editor keeping drafts must be added here on purpose, with its validator and its clear-on-save");
});

for (const rel of DRAFT_EDITORS) {
  test(`${rel} calls restore() only from a handler, never from an effect`, () => {
    const src = read(rel);
    const calls = [...src.matchAll(/\.restore\(\)/g)];
    assert.ok(calls.length >= 1, "an editor that keeps a draft must offer a way back to it");
    // Every call must sit inside a function that is passed to DraftOffer.
    assert.match(src, /<DraftOffer[\s\S]*?onRestore=\{(\w+)\}/, "the banner is how it is offered");
    const handler = /onRestore=\{(\w+)\}/.exec(src)?.[1] as string;
    const body = functionBody(src, handler);
    assert.match(body, /\.restore\(\)/, `${handler} is the one place that applies the draft`);
    // …and not from an effect.
    for (const m of src.matchAll(/useEffect\s*\(\s*\(\)\s*=>\s*\{/g)) {
      let depth = 0;
      const start = (m.index ?? 0) + m[0].length - 1;
      let end = start;
      for (let i = start; i < src.length; i++) {
        if (src[i] === "{") depth++;
        else if (src[i] === "}" && --depth === 0) { end = i; break; }
      }
      assert.doesNotMatch(src.slice(start, end), /\.restore\(\)|restoreDraft\(/,
        "restoring from an effect would apply the draft on mount, which is the browser deciding what goes into a voucher");
    }
  });

  test(`${rel} clears the draft on a SAVE and only on a save`, () => {
    // The RULE, read off the syntax tree: every `draft.clear()` is reachable only
    // once the server has said yes. It used to be pinned as the spelling
    // `saved === true ... draft.clear()` with exactly one call, which failed the
    // day the bill editor — whose save is its own function, with two successful
    // endings (an edit and a create) — needed two, and said nothing about whether
    // either was actually behind a success check.
    const sf = ts.createSourceFile(rel, readFileSync(join(WEB, rel), "utf8"), ts.ScriptTarget.Latest, true,
      ts.ScriptKind.TSX);
    const clears: ts.CallExpression[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isCallExpression(n) && n.expression.getText() === "draft.clear") clears.push(n);
      n.forEachChild(visit);
    };
    visit(sf);
    assert.ok(clears.length >= 1, "an editor that keeps a draft must clear it when the document is saved");

    for (const call of clears) {
      const where = `${rel}:${sf.getLineAndCharacterOfPosition(call.getStart()).line + 1}`;
      let fn: ts.Node | undefined;
      for (let p: ts.Node | undefined = call.parent; p; p = p.parent) {
        // A failed save must not clear: never in a catch, never in a finally.
        assert.ok(!ts.isCatchClause(p), `${where}: draft.clear() in a catch clears a draft the server never received`);
        if (ts.isTryStatement(p) && p.finallyBlock
            && call.pos >= p.finallyBlock.pos && call.end <= p.finallyBlock.end) {
          assert.fail(`${where}: draft.clear() in a finally runs on a failed save too`);
        }
        if (!fn && (ts.isFunctionDeclaration(p) || ts.isArrowFunction(p) || ts.isFunctionExpression(p))) fn = p;
      }
      assert.ok(fn, `${where}: not inside a function`);

      // GATED: either inside `if (… saved …) { draft.clear() }`, or after an
      // `if (… .success …) throw` in the same function.
      let gated = false;
      for (let p: ts.Node | undefined = call.parent; p && p !== fn; p = p.parent) {
        if (ts.isIfStatement(p) && /\bsaved\b/.test(p.expression.getText())
            && call.pos >= p.thenStatement.pos && call.end <= p.thenStatement.end) gated = true;
      }
      const checks: ts.IfStatement[] = [];
      const find = (n: ts.Node): void => {
        if (ts.isIfStatement(n) && n.end <= call.pos && /\.success\b/.test(n.expression.getText())) {
          let throws = false;
          const looks = (m: ts.Node): void => { if (ts.isThrowStatement(m)) throws = true; m.forEachChild(looks); };
          looks(n.thenStatement);
          if (throws) checks.push(n);
        }
        n.forEachChild(find);
      };
      find(fn as ts.Node);
      if (checks.length > 0) gated = true;
      assert.ok(gated, `${where}: draft.clear() is not behind a success check — clearing before the server answers loses the draft on a refusal`);

      // And it comes AFTER the request: inside an async function after an await,
      // or inside a `.then` callback.
      let afterRequest = false;
      const awaits = (n: ts.Node): void => {
        if (ts.isAwaitExpression(n) && n.end <= call.pos) afterRequest = true;
        n.forEachChild(awaits);
      };
      awaits(fn as ts.Node);
      for (let p: ts.Node | undefined = call.parent; p; p = p.parent) {
        if (ts.isCallExpression(p) && ts.isPropertyAccessExpression(p.expression)
            && p.expression.name.text === "then") afterRequest = true;
      }
      assert.ok(afterRequest, `${where}: draft.clear() does not follow an await — it cannot be reached on the server's answer`);
    }
  });

  test(`${rel} keeps no draft for a document it cannot edit`, () => {
    const src = read(rel);
    assert.match(src, /useUnsentDraft\s*<[^>]*>\s*\(\s*\{[\s\S]*?enabled:\s*!\s*(?:readOnly|isLocked)/,
      "a read-only or locked document has no form to keep: nothing should be stored or offered for it");
  });
}

test("the hook never applies what it reads", () => {
  const src = read("lib/drafts/useUnsentDraft.ts");
  // `offer` is data. The hook has no setter for the caller's fields at all.
  assert.match(src, /offer: ReadDraft<T> \| null/);
  assert.doesNotMatch(src, /onRestore|apply\(|setFields/, "applying is the editor's act, on a click");
});

// ═════════════════════════════════════════════════════════════════════════════
// 4. SIGN-OUT
// ═════════════════════════════════════════════════════════════════════════════

test("signing out clears every draft", () => {
  const src = read("lib/auth/AuthContext.tsx");
  const body = src.slice(src.indexOf("const signOut"));
  const end = body.indexOf("}, []);");
  assert.match(body.slice(0, end), /clearAllDrafts\(browserSessionStorage\(\)\)/);
});
