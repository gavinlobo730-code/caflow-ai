/**
 * The portal's Pay Now control, rendered (PRE-B-002 part 2). Run with:
 *   node --experimental-strip-types --test components/portal/PayOnlineControl.test.ts
 *
 * Same method as components/ui/empty-state-action.test.ts: `pnpm test` strips types and does not parse JSX, so this
 * transpiles the REAL PayOnlineControl.tsx, onlinePayment.ts, shape.ts, callout.tsx and button.tsx (with its two
 * async helpers) with the TypeScript compiler already in node_modules and renders them with react-dom/server.
 * `lucide-react` is a stand-in (named svgs) and `react/jsx-runtime` is one that records the props of each host
 * element, so the test can take the `onClick` the button really attached. No browser, no layout, no pixels.
 *
 * WHAT IT PINS, all from the server's block and nothing the browser knows:
 *   * while the server says online payment is not available, a payable invoice shows a DISABLED button carrying the
 *     server's own label, with no click handler at all and a pointer at the one notice, and the notice says the
 *     server's headline and reason ONCE;
 *   * a row the server does not mark `can_pay_online: true` renders nothing, whatever the block says (a draft, a
 *     cancelled or a paid invoice), and an unclear flag is not true;
 *   * a block that is missing, not an object or whose `available` is not the boolean true renders NO enabled
 *     control (it fails closed), which is what a frontend ahead of its backend sees;
 *   * when the server says available, the button is enabled and a second click while the link is being made is
 *     ignored (the page's promise is returned to the Button's guard).
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";

const WEB = path.resolve(import.meta.dirname, "../..");
type Props = Record<string, unknown>;
let dir = "";
let PayOnlineControl: (p: Props) => React.ReactElement | null;
let OnlinePaymentNotice: (p: Props) => React.ReactElement | null;

function transpile(rel: string, replacements: Record<string, string>): string {
  const source = fs.readFileSync(path.join(WEB, rel), "utf8");
  let js = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  for (const [from, to] of Object.entries(replacements)) js = js.split(JSON.stringify(from)).join(to);
  return js;
}

before(async () => {
  dir = fs.mkdtempSync(path.join(WEB, ".pay-online-test-"));
  const utils = JSON.stringify(pathToFileURL(path.join(WEB, "lib/utils.ts")).href);
  fs.writeFileSync(path.join(dir, "icons.mjs"),
    'import React from "react";\n' +
    'const icon = (name) => () => React.createElement("svg", { "data-icon": name });\n' +
    'export const CreditCard = icon("CreditCard");\nexport const Loader2 = icon("Loader2");\n' +
    'export const AlertTriangle = icon("AlertTriangle");\nexport const Info = icon("Info");\n' +
    'export const EyeOff = icon("EyeOff");\nexport const XCircle = icon("XCircle");\n');
  fs.writeFileSync(path.join(dir, "recording-runtime.mjs"),
    'import * as real from "react/jsx-runtime";\n' +
    'export const Fragment = real.Fragment;\n' +
    'const wrap = (fn) => (type, props, ...rest) => {\n' +
    '  if (typeof type === "string") (globalThis.__host ??= []).push({ type, props });\n' +
    '  return fn(type, props, ...rest);\n};\n' +
    'export const jsx = wrap(real.jsx);\nexport const jsxs = wrap(real.jsxs);\n');

  fs.writeFileSync(path.join(dir, "singleFlight.mjs"), transpile("lib/async/singleFlight.ts", {}));
  fs.writeFileSync(path.join(dir, "useSingleFlight.mjs"), transpile("lib/async/useSingleFlight.ts", {
    "@/lib/async/singleFlight": '"./singleFlight.mjs"',
  }));
  fs.writeFileSync(path.join(dir, "button.mjs"), transpile("components/ui/button.tsx", {
    "react/jsx-runtime": '"./recording-runtime.mjs"',
    "lucide-react": '"./icons.mjs"',
    "@/lib/utils": utils,
    "@/lib/async/singleFlight": '"./singleFlight.mjs"',
    "@/lib/async/useSingleFlight": '"./useSingleFlight.mjs"',
  }));
  fs.writeFileSync(path.join(dir, "callout.mjs"), transpile("components/ui/callout.tsx", {
    "lucide-react": '"./icons.mjs"',
    "@/lib/utils": utils,
  }));
  fs.writeFileSync(path.join(dir, "shape.mjs"), transpile("lib/api/shape.ts", {}));
  fs.writeFileSync(path.join(dir, "onlinePayment.mjs"), transpile("lib/payments/onlinePayment.ts", {
    "@/lib/api/shape": '"./shape.mjs"',
  }));
  fs.writeFileSync(path.join(dir, "control.mjs"), transpile("components/portal/PayOnlineControl.tsx", {
    "react/jsx-runtime": '"./recording-runtime.mjs"',
    "lucide-react": '"./icons.mjs"',
    "@/components/ui/button": '"./button.mjs"',
    "@/components/ui/callout": '"./callout.mjs"',
    "@/lib/payments/onlinePayment": '"./onlinePayment.mjs"',
  }));
  const m = await import(pathToFileURL(path.join(dir, "control.mjs")).href);
  PayOnlineControl = m.PayOnlineControl;
  OnlinePaymentNotice = m.OnlinePaymentNotice;
});

after(() => {
  if (dir) fs.rmSync(dir, { recursive: true, force: true });
  delete (globalThis as Record<string, unknown>).__host;
});

const h = React.createElement;
const html = (el: React.ReactElement) => renderToStaticMarkup(el);

// The blocks are what the SERVER sends (apps/api/domain/payments/availability.py portal_block); the wording here
// is a fixture, not a copy the browser uses: nothing in the component under test holds any of it.
const COMING_SOON = {
  available: false, label: "Pay Now · coming soon",
  headline: "Online payment is coming soon.", reason: "It has not been switched on yet, so for now please pay by the details on your invoice.",
};
const LIVE = { available: true, label: "Pay Now", headline: null, reason: null };

const control = (over: Props = {}) =>
  h(PayOnlineControl, { block: COMING_SOON, canPay: true, busy: false, onPay: () => {}, ...over });

type Host = { type: string; props: Record<string, unknown> };
function hosts(el: React.ReactElement): Host[] {
  (globalThis as Record<string, unknown>).__host = [];
  html(el);
  return (globalThis as Record<string, unknown>).__host as Host[];
}

test("not available: a payable invoice shows a disabled button with the server's label, and no way to click it", () => {
  const out = html(control());
  assert.match(out, /^<button class="[^"]*" disabled="" aria-describedby="online-payment-notice">/);
  assert.match(out, /Pay Now · coming soon/);
  const buttons = hosts(control()).filter((r) => r.type === "button");
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].props.onClick, undefined, "a disabled Pay Now has no handler, so nothing can open a payment page");
});

test("not available: the notice says the server's headline and reason once, and only when something is payable", () => {
  const out = html(h(OnlinePaymentNotice, { block: COMING_SOON, anyPayable: true }));
  assert.match(out, /id="online-payment-notice"/);
  assert.equal((out.match(/Online payment is coming soon\./g) ?? []).length, 1);
  assert.match(out, /pay by the details on your invoice/);
  assert.equal(html(h(OnlinePaymentNotice, { block: COMING_SOON, anyPayable: false })), "", "nothing to pay, nothing to explain");
  assert.equal(html(h(OnlinePaymentNotice, { block: LIVE, anyPayable: true })), "", "available: no notice");
});

test("a row the server does not mark can_pay_online: true renders nothing at all", () => {
  for (const flag of [false, undefined, null, "true", 1, {}]) {
    assert.equal(html(control({ canPay: flag })), "", `canPay ${JSON.stringify(flag)} is not true`);
    assert.equal(html(control({ block: LIVE, canPay: flag })), "", "even when online payment is available");
  }
});

test("a missing or unclear block renders no enabled control (fails closed)", () => {
  for (const block of [undefined, null, "yes", [], 7]) {
    assert.equal(html(control({ block })), "", `block ${JSON.stringify(block)} offers nothing`);
  }
  // An object whose `available` is not the boolean true is not available either: it is the disabled control.
  for (const available of ["true", 1, "yes", undefined, null]) {
    const out = html(control({ block: { ...COMING_SOON, available } }));
    assert.match(out, / disabled=""/, `available ${JSON.stringify(available)} is not true`);
    assert.equal(hosts(control({ block: { ...COMING_SOON, available } }))[0].props.onClick, undefined);
  }
});

test("available: the button is enabled, labelled by the server, and a second click is ignored while the link is made", async () => {
  let calls = 0;
  let release!: () => void;
  const running = new Promise<void>((r) => { release = r; });
  const el = control({ block: LIVE, onPay: () => { calls++; return running; } });
  const out = html(el);
  assert.doesNotMatch(out, / disabled=""/);
  assert.match(out, /<\/svg> Pay Now<\/button>/);
  const button = hosts(el).filter((r) => r.type === "button");
  assert.equal(button.length, 1);
  const onClick = button[0].props.onClick as (e: unknown) => unknown;
  const click = () => ({ currentTarget: {}, preventDefault() {}, stopPropagation() {} });
  onClick(click());
  onClick(click());
  assert.equal(calls, 1, "two clicks on one tick make one payment link");
  release();
  await new Promise<void>((r) => setImmediate(r));
});

test("busy: the enabled button is disabled while the page is already working on something", () => {
  assert.match(html(control({ block: LIVE, busy: true })), / disabled=""/);
});
