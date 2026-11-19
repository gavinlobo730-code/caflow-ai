// A dialog that holds Close and Cancel while its request is out is freed when that request is given up on (POST-A-395).
//   node --experimental-strip-types --test scripts/a-dialog-that-holds-close-is-freed-by-a-bounded-request.test.ts
//
// The engagement letters page's two dialogs hold Close and Cancel while a save or a step is out (driven in
// scripts/drive/scenarios/dialogLeftovers.mjs). Held over a request that never answers, they stayed held until the browser
// gave up, which can be minutes: the page's own JSON helper called `fetch` with no bound, where every JSON call through
// `lib/api` is aborted at 45 seconds. A held dialog is only safe over a request that ends, so the helper is bounded the same.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const page = readFileSync(join(WEB, "app/engagements/page.tsx"), "utf8");

test("the engagement letters page's requests are bounded at lib/api's 45 seconds", () => {
  // The bound itself is held over the whole tree by scripts/a-request-a-screen-makes-ends.test.ts (POST-A-470); this page's two calls go through the bounded door with no longer bound.
  const helper = page.slice(page.indexOf("async function apiFetch("), page.indexOf("// Types"));
  assert.match(helper, /fetchBounded\(`\$\{API\}\$\{path\}`, \{\s*\.\.\.opts,/, "the JSON helper does not send through the bounded door (or lets nothing override it)");
  const pdf = page.slice(page.indexOf("async function doDownloadPdf("), page.indexOf("async function doDownloadPdf(") + 900);
  assert.match(pdf, /fetchBounded\(/, "the PDF download, which holds Close too, is not bounded");
  assert.doesNotMatch(pdf, /LONG_REQUEST_BOUND_MS/, "a one-letter PDF was given the export's long bound, so Close stays held for minutes");
});

test("each dialog's Close and Cancel are held while its request is out", () => {
  const template = page.slice(page.indexOf("function TemplateModal("), page.indexOf("function DetailModal("));
  assert.match(template, /onClick=\{onClose\} disabled=\{saving\} aria-label="Close"/, "the template dialog's Close is not held or not named");
  assert.match(template, /onClick=\{onClose\}\s*disabled=\{saving\}/, "the template dialog's Cancel is not held");
  const detail = page.slice(page.indexOf("function DetailModal("), page.indexOf("function EngagementsPageInner("));
  assert.match(detail, /onClick=\{onClose\} disabled=\{actionLoading\} aria-label="Close"/, "the detail dialog's Close is not held or not named");
  const cancels = detail.match(/onClick=\{\(\) => setShow\w+\(false\)\}( disabled=\{actionLoading\})?/g) ?? [];
  assert.ok(cancels.length >= 5, `the detail dialog's step Cancels were not found (${cancels.length})`);
  assert.deepEqual(cancels.filter((c) => !c.includes("disabled={actionLoading}")), [], "a step's Cancel is live while the step is out");
});

// ── the rule over every overlay (the review of 18-11-2026: the shared Modal's Escape, backdrop and X, and the trackers' batch prompts) ──

import { readdirSync, statSync } from "node:fs";
import ts from "typescript";
import { looseDismissers, overlaysInFlight } from "./dialogHolds.ts";

const loose = (src: string) => looseDismissers("t.tsx", src).map((l) => l.what);

test("the rule: each way of dismissing an overlay over a write in flight is found, a held one is not, and a read is not a write", () => {
  const modal = (onClose: string, cancel: string) =>
    `const A = () => <Modal title="x" onClose={${onClose}}><button ${cancel} onClick={onClose}>Cancel</button><Button disabled={saving} onClick={save}>Save</Button></Modal>;`;
  assert.deepEqual(loose(modal("onClose", "")), ["onClose (Escape, backdrop, X)", "Cancel"]);
  assert.deepEqual(loose(modal("() => { if (!saving) onClose(); }", "disabled={saving}")), []);
  const handBuilt = (backdrop: string, x: string) =>
    `const B = () => <div className="fixed inset-0 z-50" ${backdrop}><div><button ${x} onClick={onClose}><X size={14} /></button><button aria-label="Close" ${x} onClick={onClose}>x</button>`
    + `<Button disabled={busy || !ok} onClick={go}>Send</Button></div></div>;`;
  assert.deepEqual(loose(handBuilt("onClick={onClose}", "")), ["backdrop click", "X", "Close (named)"]);
  assert.deepEqual(loose(handBuilt("onClick={(e) => { e.stopPropagation(); if (!busy) onClose(); }}", "disabled={busy}")), []);
  assert.deepEqual(loose(`const C = () => <Drawer onClose={leave}><button onClick={leave}>Cancel</button><button disabled={submitting}>Save</button></Drawer>;`),
    ["onClose (Escape, backdrop, X)", "Cancel"]);
  // A dialog whose only flag is a READ: leaving while it reads is not trapping a write.
  assert.deepEqual(loose(`const D = () => <Modal title="x" onClose={onClose}><button onClick={onClose}>Cancel</button><Button disabled={loading}>Save</Button></Modal>;`), []);
  assert.equal(overlaysInFlight("t.tsx", modal("onClose", "")), 1);
});

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(WEB, dir))) {
    if (e === "node_modules" || e === ".next") continue;
    const rel = join(dir, e).replace(/\\/g, "/");
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (rel.endsWith(".tsx") && !rel.includes(".test.")) out.push(rel);
  }
  return out;
}

test("no overlay in the product lets the person dismiss it over a write in flight (the list of exceptions is empty)", () => {
  const files = ["app", "components"].flatMap((d) => walk(d));
  const found = files.flatMap((f) => looseDismissers(f, readFileSync(join(WEB, f), "utf8")).map((l) => `${l.file}:${l.line} ${l.overlay} ${l.what}`));
  const inFlight = files.reduce((n, f) => n + overlaysInFlight(f, readFileSync(join(WEB, f), "utf8")), 0);
  assert.ok(inFlight >= 80, `only ${inFlight} overlays with a write in flight were found: the scan is not reading the product`);
  assert.deepEqual(found, [], "an overlay can be closed over a write in flight: hold its Cancel, Close and X on the flag its Save is held by, and its onClose or backdrop too");
});

test("the shared prompt that records a filing holds Escape, the backdrop and its X while the filings are out", () => {
  const prompt = readFileSync(join(WEB, "components/compliance/MarkFiledModal.tsx"), "utf8");
  assert.match(prompt, /<Modal title=\{title\} onClose=\{\(\) => \{ if \(!busy\) onClose\(\); \}\}/, "MarkFiledModal hands the Modal an onClose that ignores busy");
});

test("apiCall can be bounded and has no bound of its own, and the supplier form's save is bounded", () => {
  const shared = readFileSync(join(WEB, "lib/invoices/shared.ts"), "utf8");
  assert.match(shared, /export const HELD_DIALOG_MS = REQUEST_BOUND_MS;/);
  assert.match(shared, /options: \{ timeoutMs\?: number \} = \{\},/, "apiCall takes no time limit");
  assert.match(shared, /\.\.\.\(options\.timeoutMs \? \{ signal: AbortSignal\.timeout\(options\.timeoutMs\) \} : \{\}\),/, "apiCall's limit is not an abort signal, or it has a default");
  const purchases = readFileSync(join(WEB, "app/clients/[id]/purchases/page.tsx"), "utf8");
  for (const call of ['apiCall(`/api/vendors/${editingVendor.id}`, "PATCH", fields, token, { timeoutMs: HELD_DIALOG_MS })', 'apiCall("/api/vendors/", "POST", { client_id: clientId, ...fields }, token, { timeoutMs: HELD_DIALOG_MS })']) {
    assert.ok(purchases.includes(call), `the supplier form's save is not bounded: ${call}`);
  }
  assert.doesNotMatch(purchases, /apiCall\("\/api\/(vendors|purchase-bills)\/bulk"[^)]*HELD_DIALOG_MS/, "a bulk import was bounded at 45 seconds");
});

// ── the second review (18-11-2026): what the rule could not see ────────────────────────────────────────────────────────────────────

test("the rule sees a × button, a button whose click is onClose, a write flag that starts or ends with the word, and a backdrop that lets a click reach the overlay behind", () => {
  const over = (inner: string, backdrop = "onClick={(e) => { e.stopPropagation(); if (!savingOverride) onClose(); }}") =>
    `const E = () => <div className="fixed inset-0 z-50" ${backdrop}><div>${inner}<Button disabled={savingOverride} onClick={go}>Save</Button></div></div>;`;
  assert.deepEqual(loose(over(`<button onClick={close}><span className="text-lg">×</span></button>`)), ["×"]);
  assert.deepEqual(loose(over(`<button onClick={close}>&times;</button>`)), ["×"]);
  assert.deepEqual(loose(over(`<Button onClick={onClose}>Done</Button>`)), ["onClose button"]);
  assert.deepEqual(loose(over(`<button disabled={savingOverride} onClick={onClose}><span>×</span></button>`)), []);
  // A backdrop that only declines to close leaves the click to bubble into an overlay behind it (a dialog over a ledger).
  assert.deepEqual(loose(over("", "onClick={savingOverride ? undefined : onClose}")), ["backdrop click reaches the overlay behind"]);
  // `busyId === "save"` is a write flag too: the word begins the name.
  assert.deepEqual(loose(`const F = () => <Modal title="x" onClose={onClose}><button onClick={onClose}>Cancel</button><Button disabled={busyId === "save"}>Save</Button></Modal>;`),
    ["onClose (Escape, backdrop, X)", "Cancel"]);
});

test("the rule sees a write flag set before an await that a throw would leave set, through a flag made of others", () => {
  const src = (body: string) => `function G() {
    const [deactivating, setDeactivating] = useState(false);
    const actionInFlight = deactivating || other;
    async function go() { setDeactivating(true); ${body} }
    return <div className="fixed inset-0"><button disabled={actionInFlight} onClick={() => setT(null)}>Cancel</button><button disabled={actionInFlight} onClick={go}>Deactivate</button></div>;
  }`;
  assert.deepEqual(loose(src(`const r = await call(); setDeactivating(false);`)), ["setDeactivating(true) before an await with no setDeactivating(false) in a finally"]);
  assert.deepEqual(loose(src(`try { await call(); } finally { setDeactivating(false); }`)), []);
});

test("a bounded write is never inside a loop: a row of an import or a bulk action that takes long must not throw the whole loop and lose its tally", () => {
  const LOOPY = /(^|\.)(map|forEach|mapWithConcurrency|all|allSettled|filter|reduce|flatMap)$/;
  const offenders: string[] = [];
  for (const rel of ["app/clients/[id]/purchases/page.tsx", "app/clients/[id]/sales/page.tsx", "components/customers/CustomerFormModal.tsx", "components/purchases/LandedCostPanel.tsx", "components/purchases/RecurringBills.tsx"]) {
    const sf = ts.createSourceFile(rel, readFileSync(join(WEB, rel), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    let bounded = 0;
    const visit = (n: ts.Node) => {
      if (ts.isCallExpression(n) && n.expression.getText() === "apiCall" && n.arguments[4]?.getText().includes("timeoutMs")) {
        bounded += 1;
        for (let p: ts.Node | undefined = n.parent; p; p = p.parent) {
          const inLoop = ts.isForStatement(p) || ts.isForOfStatement(p) || ts.isForInStatement(p) || ts.isWhileStatement(p) || ts.isDoStatement(p)
            || ((ts.isArrowFunction(p) || ts.isFunctionExpression(p)) && !!p.parent && ts.isCallExpression(p.parent) && LOOPY.test(p.parent.expression.getText()))
            || ((ts.isFunctionDeclaration(p) && p.name?.text === "runAllDue") || (ts.isVariableDeclaration(p) && p.name.getText() === "runAllDue"));
          if (inLoop) { offenders.push(`${rel}:${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`); break; }
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
    assert.ok(bounded > 0, `${rel} bounds no write: the scan is not reading it`);
  }
  assert.deepEqual(offenders, []);
});
