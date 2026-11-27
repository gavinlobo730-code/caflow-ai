// POST-A-130 — where Tab goes inside a dialog that declares itself modal, and what stops the page behind it from scrolling.
//   node --experimental-strip-types --test lib/ui/focusTrap.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { tabTarget, canTakeFocusOnOpen, whoOpenedTheDialog } from "./focusTrap.ts";
import { lockBodyScroll } from "./scrollLock.ts";

const items = ["close", "name", "save"];

test("Tab on the last element wraps to the first, and Shift+Tab on the first wraps to the last", () => {
  assert.equal(tabTarget(items, "save", false), "first");
  assert.equal(tabTarget(items, "close", true), "last");
});

test("a step that stays inside the dialog is the browser's own", () => {
  assert.equal(tabTarget(items, "close", false), null);
  assert.equal(tabTarget(items, "name", false), null);
  assert.equal(tabTarget(items, "name", true), null);
  assert.equal(tabTarget(items, "save", true), null);
});

test("focus on the panel itself or outside it is pulled in: Shift+Tab goes to the last element, Tab to the first", () => {
  // The panel is focused on open (tabindex -1) and is not one of the focusable elements; Shift+Tab from it would leave for the page.
  assert.equal(tabTarget(items, "panel", true), "last");
  assert.equal(tabTarget(items, "panel", false), "first");
  assert.equal(tabTarget(items, null, true), "last");
  assert.equal(tabTarget(items, null, false), "first");
});

test("a dialog with nothing focusable traps nothing", () => {
  assert.equal(tabTarget([], null, false), null);
  assert.equal(tabTarget([], "panel", true), null);
});

test("a dialog with one focusable element keeps focus on it either way", () => {
  assert.equal(tabTarget(["only"], "only", false), "first");
  assert.equal(tabTarget(["only"], "only", true), "last");
});

// ── the scroll lock ──────────────────────────────────────────────────────────────────────────────────────────────────
function withBody(initial: string, body: (style: { overflow: string }) => void) {
  const saved = (globalThis as { document?: unknown }).document;
  const style = { overflow: initial };
  (globalThis as { document?: unknown }).document = { body: { style } };
  try { body(style); } finally { (globalThis as { document?: unknown }).document = saved; }
}

test("the page is locked while a dialog is open and goes back to what it was", () => {
  withBody("auto", (style) => {
    const release = lockBodyScroll();
    assert.equal(style.overflow, "hidden");
    release();
    assert.equal(style.overflow, "auto");
  });
});

test("a dialog over a dialog keeps the page locked until the LAST one closes", () => {
  withBody("", (style) => {
    const drawer = lockBodyScroll();
    const modal = lockBodyScroll();
    modal();
    assert.equal(style.overflow, "hidden", "the drawer is still open");
    drawer();
    assert.equal(style.overflow, "");
  });
});

test("releasing twice releases once, so a double cleanup cannot unlock a dialog that is still open", () => {
  withBody("", (style) => {
    const first = lockBodyScroll();
    const second = lockBodyScroll();
    first();
    first();
    assert.equal(style.overflow, "hidden", "the second holder is still there");
    second();
    assert.equal(style.overflow, "");
  });
});

test("with no document (server render) locking is a no-op that can still be released", () => {
  const saved = (globalThis as { document?: unknown }).document;
  (globalThis as { document?: unknown }).document = undefined;
  try {
    assert.doesNotThrow(() => lockBodyScroll()());
  } finally {
    (globalThis as { document?: unknown }).document = saved;
  }
});

test("a dialog moves focus to a control a person can focus, never to a hidden or disabled one", () => {
  assert.equal(canTakeFocusOnOpen({ disabled: false, type: "text", offsetParent: {} }), true);
  assert.equal(canTakeFocusOnOpen({ disabled: false, type: "file", offsetParent: null }), false, "a `class=hidden` file input is display:none: focus() on it does nothing");
  assert.equal(canTakeFocusOnOpen({ disabled: true, type: "text", offsetParent: {} }), false);
  assert.equal(canTakeFocusOnOpen({ disabled: false, type: "hidden", offsetParent: {} }), false);
  assert.equal(canTakeFocusOnOpen({ disabled: false, offsetParent: {} }), true, "a select or textarea has no input type");
});

// POST-A-555 — who a dialog gives the focus back to. The elements are stand-ins with the two facts the rule reads.
const el = (name: string, connected = true, inside: unknown[] = []) =>
  ({ name, isConnected: connected, contains: (x: unknown) => inside.includes(x) }) as unknown as HTMLElement;

test("a field that took the focus itself is not the opener: the element read before the dialog mounted is", () => {
  const field = el("autofocused field");
  const panel = el("panel", true, [field]);
  const opener = el("Edit button");
  // At effect time the focused element is the field inside the panel; the render before it saw the button.
  assert.equal(whoOpenedTheDialog(opener, panel, field), opener);
});

test("an overlay replaced in the same commit hands the focus to its own opener, and that is who this one gives it back to", () => {
  const menuItem = el("menu item", false);       // gone by now: the menu unmounted in the commit that mounted the dialog
  const rowButton = el("row button");            // where the menu put the focus on its way out
  const panel = el("panel");
  assert.equal(whoOpenedTheDialog(menuItem, panel, rowButton), rowButton);
});

test("nothing focused when it was drawn and a field inside took the focus: there is nobody to give it back to, so the page", () => {
  const field = el("autofocused field");
  const panel = el("panel", true, [field]);
  const body = el("body");
  assert.equal(whoOpenedTheDialog(body, panel, field), body);
});

test("the element read in the render that is inside the dialog is never the opener", () => {
  const field = el("field");
  const panel = el("panel", true, [field]);
  const rowButton = el("row button");
  assert.equal(whoOpenedTheDialog(field, panel, rowButton), rowButton);
});
