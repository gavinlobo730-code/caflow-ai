// POST-A-130 — where Tab goes inside a dialog that declares itself modal, and what stops the page behind it from scrolling.
//   node --experimental-strip-types --test lib/ui/focusTrap.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { tabTarget } from "./focusTrap.ts";
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
