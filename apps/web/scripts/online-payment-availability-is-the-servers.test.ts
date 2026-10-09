// Whether a client may pay online, and what the screen says when not, is the SERVER's answer. Run with:
//   node --experimental-strip-types --test scripts/online-payment-availability-is-the-servers.test.ts
//
// WHAT WAS WRONG (PRE-B-002 part 2)
//     The portal's Pay Now button was drawn for every invoice with `outstanding_paise > 0` and called the pay route
//     with no check of which payment provider the deployment had. With the provider blank or `mock` (the production
//     state) the link was an address that does not exist, and the practice-side "Payment Link" modal could email it
//     to a client's customer. A draft or a cancelled invoice got the button too, because an outstanding figure
//     is not tied to a status.
//
// THE RULE (the browser decides nothing and holds no words about it)
//   * `apps/api/domain/payments/availability.py` decides whether a real gateway is set up, words it for each
//     audience and says which invoices are payable; the dashboard serves `online_payment` and each invoice row
//     `can_pay_online`. The screens render those and nothing else.
//   * So no source file in the product names a gateway or the test double (`razorpay`, `mock-pay`,
//     `PAYMENT_PROVIDER`, `rzp_`), and none of the screens that show the control or the modal holds the
//     sentence "coming soon": a copy of the server's wording is a second voice that the register
//     (docs/open-items/coming-soon.md) holds the server to and not the browser.
//   * The portal reaches the pay route only from the control's `onPay`, which the control gives an `onClick`
//     to only when the server said available: every reference to `payInvoice` is the value of an `onPay`
//     attribute.
//   * The practice-side modal offers Generate, Copy and Email only inside a `gatewayOn &&` (the server's
//     `online_payment.available`), and the server refuses those calls with the same words in any case.
//
// WHAT IT CANNOT SEE: a payload that arrives wrong (the render test fails it closed), and whether the page looks
// right: nothing here opens a browser. The control itself is rendered by components/portal/PayOnlineControl.test.ts.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

const PORTAL_PAGE = "app/portal/dashboard/page.tsx";
const SALES_PAGE = "app/clients/[id]/sales/page.tsx";
const CONTROL = "components/portal/PayOnlineControl.tsx";
const TYPES = "lib/payments/onlinePayment.ts";

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "out" || e.name.startsWith(".")) continue;
      walk(rel, out);
    } else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name)) {
      out.push(rel);
    }
  }
  return out;
}

function parse(source: string): ts.SourceFile {
  return ts.createSourceFile("x.tsx", source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
}

/** Every reference to `name` that is not its declaration and is not the value of a JSX attribute called `attr`. */
export function referencesOutsideAttribute(source: string, name: string, attr: string): string[] {
  const sf = parse(source);
  const bad: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isIdentifier(node) && node.text === name) {
      const parent = node.parent;
      const isDeclaration = (ts.isVariableDeclaration(parent) && parent.name === node)
        || (ts.isFunctionDeclaration(parent) && parent.name === node);
      // `api.portalSelf.payInvoice` is the API client's method of the same name, not a reference to the local.
      const isMemberName = ts.isPropertyAccessExpression(parent) && parent.name === node;
      if (!isDeclaration && !isMemberName) {
        let n: ts.Node | undefined = node;
        let ok = false;
        while (n) {
          if (ts.isJsxAttribute(n) && n.name.getText(sf) === attr) { ok = true; break; }
          n = n.parent;
        }
        if (!ok) bad.push(`line ${sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1}: ${parent.getText(sf).slice(0, 80)}`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return bad;
}

/** In the function `fn`, every JSX `onClick` whose expression mentions one of `actions` that is NOT inside a
 *  `<guard> && ...` expression (the guard identifier on the left of the &&). */
export function unguardedActions(source: string, fn: string, actions: RegExp, guard: string): string[] {
  const sf = parse(source);
  const bad: string[] = [];
  let found = false;
  const underGuard = (node: ts.Node): boolean => {
    for (let n: ts.Node | undefined = node.parent; n; n = n.parent) {
      if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
          && new RegExp(`\\b${guard}\\b`).test(n.left.getText(sf)) && n.right.pos <= node.pos && node.end <= n.right.end) {
        return true;
      }
    }
    return false;
  };
  const inFn = (node: ts.Node) => {
    if (ts.isJsxAttribute(node) && node.name.getText(sf) === "onClick" && actions.test(node.getText(sf)) && !underGuard(node)) {
      bad.push(`line ${sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1}: ${node.getText(sf).slice(0, 80)}`);
    }
    ts.forEachChild(node, inFn);
  };
  const visit = (node: ts.Node) => {
    if (ts.isFunctionDeclaration(node) && node.name?.text === fn) { found = true; inFn(node); return; }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  assert.ok(found, `function ${fn} not found: the rule below would pass over nothing`);
  return bad;
}

// ── the browser holds no wording and no gateway name ─────────────────────────────────────────────────────

test("no source file in the product names a payment gateway or the test double", () => {
  const files = [...walk("app"), ...walk("components"), ...walk("lib")];
  assert.ok(files.length > 300, "the walk found almost nothing; the rule would pass over an empty tree");
  const offenders = files.filter((f) => /razorpay|mock-pay|PAYMENT_PROVIDER|rzp_/i.test(stripComments(read(f))));
  assert.deepEqual(offenders, [], "the server's block carries the label and the words: the browser names no gateway");
});

test("the screens that show the control or the modal do not hold the server's sentence", () => {
  for (const f of [PORTAL_PAGE, SALES_PAGE, CONTROL, TYPES]) {
    assert.doesNotMatch(stripComments(read(f)), /coming soon/i,
      `${f} holds a copy of the wording; render the server's block (docs/open-items/coming-soon.md COMING-001)`);
  }
});

// ── the portal pays only through the control ─────────────────────────────────────────────────────────────

test("the portal reaches the pay route only as the value of the control's onPay", () => {
  const src = stripComments(read(PORTAL_PAGE));
  assert.match(src, /<PayOnlineControl\b/, "the Invoices table draws the control");
  assert.deepEqual(referencesOutsideAttribute(src, "payInvoice", "onPay"), []);
  // The old gate was `outstanding_paise > 0` and nothing else; the label was typed into the page.
  assert.doesNotMatch(src, />\s*Pay Now\s*</, "the label is the server's, not JSX text");
});

test("the scanner finds a Pay button that bypasses the control", () => {
  const bad = `function A(){ const payInvoice = async () => {}; return <Button onClick={() => payInvoice(1)}>x</Button>; }`;
  assert.equal(referencesOutsideAttribute(bad, "payInvoice", "onPay").length, 1);
  const ok = `function A(){ const payInvoice = async () => { await api.portalSelf.payInvoice(1); }; return <C onPay={() => payInvoice(1)} />; }`;
  assert.deepEqual(referencesOutsideAttribute(ok, "payInvoice", "onPay"), []);
});

// ── the practice-side modal offers Generate, Copy and Email only when the server says a gateway is set up ──

test("the Payment Link modal offers Generate, Copy and Email only when the server says online payment is available", () => {
  const src = stripComments(read(SALES_PAGE));
  assert.match(src, /const gatewayOn = online\?\.available === true;/, "gatewayOn is the server's answer, strictly true");
  assert.deepEqual(unguardedActions(src, "PaymentLinkModal", /\b(generate|copy|send)\b/, "gatewayOn"), []);
  assert.match(src, /readOnlinePayment\(hist\?\.online_payment\)/, "the modal reads the block the history carries");
});

test("the scanner finds a Generate button that is not behind the gateway guard", () => {
  const bad = `function PaymentLinkModal(){ return <div><B onClick={generate}>Generate</B></div>; }`;
  assert.equal(unguardedActions(bad, "PaymentLinkModal", /\b(generate|copy|send)\b/, "gatewayOn").length, 1);
  const ok = `function PaymentLinkModal(){ return <div>{gatewayOn && (<B onClick={generate}>Generate</B>)}</div>; }`;
  assert.deepEqual(unguardedActions(ok, "PaymentLinkModal", /\b(generate|copy|send)\b/, "gatewayOn"), []);
  const wrongSide = `function PaymentLinkModal(){ return <div>{<B onClick={generate}/> && gatewayOn}</div>; }`;
  assert.equal(unguardedActions(wrongSide, "PaymentLinkModal", /\b(generate|copy|send)\b/, "gatewayOn").length, 1);
});

// (That a missing, unclear or non-boolean `available` renders no enabled control is a BEHAVIOUR, and is held by
// rendering the real control: components/portal/PayOnlineControl.test.ts, "fails closed".)
