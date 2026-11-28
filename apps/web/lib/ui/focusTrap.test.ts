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

// POST-A-568 — an opener that lost the focus (it was disabled while the dialog's data was fetched) is found again from the last control pressed.
test("nothing holds the focus when the dialog is drawn: the control last pressed is who it gives the focus back to", () => {
  const panel = el("panel");
  const pressed = el("Physical count button");
  assert.equal(whoOpenedTheDialog(null, panel, null, pressed), pressed);
});

test("the control last pressed never beats an opener that still holds the focus, and is never one inside the dialog", () => {
  const field = el("autofocused field");
  const panel = el("panel", true, [field]);
  const opener = el("Edit button");
  const stale = el("some other button");
  assert.equal(whoOpenedTheDialog(opener, panel, field, stale), opener, "the opener the render saw wins");
  assert.equal(whoOpenedTheDialog(null, panel, field, field), null, "a pressed control inside the dialog is not an opener");
});

test("a control that has gone from the page is not given the focus", () => {
  const panel = el("panel");
  const gone = el("removed button", false);
  assert.equal(whoOpenedTheDialog(null, panel, null, gone), null);
});

test("a press is remembered for a short time only, so an old press cannot claim a dialog something else opened", async () => {
  const { lastPressedControl, PRESS_MEMORY_MS, rememberPressedControls } = await import("./focusTrap.ts");
  assert.equal(lastPressedControl(), null, "nothing was pressed in this process");
  assert.ok(PRESS_MEMORY_MS >= 5_000 && PRESS_MEMORY_MS <= 60_000, "the window is seconds, not minutes");
  const target = { closest: () => target } as unknown as Element;
  const handlers = new Map<string, (e: Event) => void>();
  const doc = { addEventListener: (t: string, f: (e: Event) => void) => handlers.set(t, f), removeEventListener: () => {} } as unknown as Document;
  rememberPressedControls(doc);
  handlers.get("click")!({ target } as unknown as Event);
  assert.equal(lastPressedControl(), target as unknown as HTMLElement);
  assert.equal(lastPressedControl(Date.now() + PRESS_MEMORY_MS + 1), null, "a press older than the window is forgotten");
  handlers.get("keydown")!({ target, key: "a" } as unknown as KeyboardEvent);
});


// ── POST-A-555, third part: where the keyboard goes when the opener has left the page ───────────────────────────────────────────────

/** A stand-in document: `active` is whatever last took the focus; a node may refuse it (a disabled button). */
function fakePage({ dialogs = [] as string[], main = true } = {}) {
  const state: { active: unknown } = { active: null };
  const node = (name: string, { connected = true, takesFocus = true } = {}) => {
    const n = { name, isConnected: connected, focus: (opts?: { preventScroll?: boolean }) => { if (takesFocus) { state.active = n; n.lastOptions = opts; } }, lastOptions: undefined as unknown };
    return n;
  };
  const mainNode = node("main");
  const dialogNodes = dialogs.map((d) => node(d));
  const doc = {
    get activeElement() { return state.active; },
    querySelectorAll: (sel: string) => (sel.includes('role="dialog"') ? dialogNodes : []),
    getElementById: (id: string) => (id === "main-content" && main ? mainNode : null),
  } as unknown as Document;
  return { doc, node, mainNode, dialogNodes, state };
}

test("an opener that is still on the page gets the focus back, and nothing else is touched", async () => {
  const { giveFocusBack } = await import("./focusTrap.ts");
  const { doc, node, mainNode, state } = fakePage();
  const opener = node("Mark Filed");
  giveFocusBack(opener as unknown as HTMLElement, doc);
  assert.equal(state.active, opener);
  assert.equal(mainNode.lastOptions, undefined, "the main region was focused although the opener took the focus");
});

test("an opener that has left the page hands the keyboard to the page's main region, without scrolling it", async () => {
  const { giveFocusBack } = await import("./focusTrap.ts");
  const { doc, node, mainNode, state } = fakePage();
  giveFocusBack(node("a bulk bar's button", { connected: false }) as unknown as HTMLElement, doc);
  assert.equal(state.active, mainNode, "the keyboard fell to the document");
  assert.deepEqual(mainNode.lastOptions, { preventScroll: true });
  const none = fakePage();
  giveFocusBack(null, none.doc);
  assert.equal(none.state.active, none.mainNode, "a dialog nobody is known to have opened still lands on the main region");
});

test("an opener that is on the page and cannot take the focus (disabled) is treated as gone", async () => {
  const { giveFocusBack } = await import("./focusTrap.ts");
  const { doc, node, mainNode, state } = fakePage();
  giveFocusBack(node("a disabled button", { takesFocus: false }) as unknown as HTMLElement, doc);
  assert.equal(state.active, mainNode);
});

test("with another dialog still open underneath, the keyboard goes to THAT dialog and never to the page behind it", async () => {
  const { giveFocusBack } = await import("./focusTrap.ts");
  const { doc, node, mainNode, dialogNodes, state } = fakePage({ dialogs: ["the sheet underneath", "the dialog on top of it"] });
  giveFocusBack(node("a row that was deleted", { connected: false }) as unknown as HTMLElement, doc);
  assert.equal(state.active, dialogNodes[1], "the topmost dialog still open did not get the focus");
  assert.equal(mainNode.lastOptions, undefined, "focus went to the page behind an open dialog");
});

test("with no main region and no document there is nothing to do, and it does not throw", async () => {
  const { giveFocusBack } = await import("./focusTrap.ts");
  const { doc, node, state } = fakePage({ main: false });
  giveFocusBack(node("gone", { connected: false }) as unknown as HTMLElement, doc);
  assert.equal(state.active, null);
  giveFocusBack(null, null);
});

test("the landing place is the id both shells give their main region, and both shared overlays use the one function", async () => {
  const fs = await import("node:fs");
  const path = await import("node:path");
  const { WHERE_FOCUS_LANDS_WHEN_THE_OPENER_IS_GONE } = await import("./focusTrap.ts");
  const web = path.join(import.meta.dirname, "..", "..");
  const skip = fs.readFileSync(path.join(web, "components", "shell", "SkipToContent.tsx"), "utf8");
  assert.match(skip, new RegExp(`export const MAIN_CONTENT_ID = "${WHERE_FOCUS_LANDS_WHEN_THE_OPENER_IS_GONE}";`));
  for (const shell of ["ClientShell.tsx", "WorkspaceShell.tsx"]) {
    assert.match(fs.readFileSync(path.join(web, "components", "shell", shell), "utf8"), /<main id=\{MAIN_CONTENT_ID\} tabIndex=\{-1\}/, `${shell}: the main region is not focusable under the shared id`);
  }
  for (const overlay of ["modal.tsx", "drawer.tsx"]) {
    const src = fs.readFileSync(path.join(web, "components", "ui", overlay), "utf8");
    assert.match(src, /giveFocusBack\(restore(Focus)?Ref\.current\);/, `${overlay} does not hand the focus back through the shared function`);
    assert.doesNotMatch(src, /restore(Focus)?Ref\.current\?\.focus/, `${overlay} still calls focus() on an opener that may be gone`);
  }
});

// ── a dialog whose focused control is taken away keeps the keyboard (POST-A-555, the last part) ─────────────────────────────────────────────

test("the keyboard is nowhere when the focus is on nothing or on the document's body, and somewhere on anything else", async () => {
  const { theKeyboardIsNowhere } = await import("./focusTrap.ts");
  const body = { tagName: "BODY" } as unknown as Element;
  const panel = { tagName: "DIV" } as unknown as Element;
  assert.equal(theKeyboardIsNowhere(null, body), true);
  assert.equal(theKeyboardIsNowhere(body, body), true);
  assert.equal(theKeyboardIsNowhere(panel, body), false, "focus on the dialog's own panel is a place");
});

/** A stand-in for MutationObserver that hands back its callback, so the rule can be run without a browser. */
function withAFakeObserver<T>(run: (fire: () => void, watched: { node: unknown; options: unknown; disconnected: boolean }) => T): T {
  const watched = { node: null as unknown, options: null as unknown, disconnected: false };
  let callback: () => void = () => {};
  const real = (globalThis as { MutationObserver?: unknown }).MutationObserver;
  (globalThis as { MutationObserver?: unknown }).MutationObserver = class {
    constructor(cb: () => void) { callback = cb; }
    observe(node: unknown, options: unknown) { watched.node = node; watched.options = options; }
    disconnect() { watched.disconnected = true; }
  };
  try { return run(() => callback(), watched); } finally { (globalThis as { MutationObserver?: unknown }).MutationObserver = real; }
}

function aPanel(active: { current: unknown }) {
  const body = { tagName: "BODY" };
  const panel = {
    isConnected: true, focused: 0, lastOptions: undefined as unknown,
    ownerDocument: { body, get activeElement() { return active.current; } },
    focus(options?: unknown) { this.focused += 1; this.lastOptions = options; active.current = this; },
  };
  return { panel, body };
}

test("when the dialog's content changes and the focus has fallen to the document, the panel takes it back without scrolling", async () => {
  const { keepTheKeyboardInside } = await import("./focusTrap.ts");
  withAFakeObserver((fire, watched) => {
    const active = { current: null as unknown };
    const { panel, body } = aPanel(active);
    const stop = keepTheKeyboardInside(panel as unknown as HTMLElement, () => true);
    assert.equal(watched.node, panel);
    assert.deepEqual(watched.options, { childList: true, subtree: true }, "it must hear a control removed anywhere inside the panel");
    active.current = body;          // the focused button was removed with the old content
    fire();
    assert.equal(panel.focused, 1, "the panel did not take the keyboard back");
    assert.deepEqual(panel.lastOptions, { preventScroll: true });
    stop();
    assert.equal(watched.disconnected, true, "closing the dialog must stop the watching");
  });
});

test("a change of content while the focus is still on a control of the dialog moves nothing", async () => {
  const { keepTheKeyboardInside } = await import("./focusTrap.ts");
  withAFakeObserver((fire) => {
    const field = { tagName: "INPUT" };
    const active = { current: field as unknown };
    const { panel } = aPanel(active);
    keepTheKeyboardInside(panel as unknown as HTMLElement, () => true);
    fire();
    assert.equal(panel.focused, 0, "the cursor was pulled out of the field a person was typing in");
    assert.equal(active.current, field);
  });
});

test("a dialog that is not the one on top does not pull the keyboard down to itself, and a panel that has left the page takes nothing", async () => {
  const { keepTheKeyboardInside } = await import("./focusTrap.ts");
  withAFakeObserver((fire) => {
    const active = { current: null as unknown };
    const { panel } = aPanel(active);
    keepTheKeyboardInside(panel as unknown as HTMLElement, () => false);
    fire();
    assert.equal(panel.focused, 0, "a drawer under a dialog took the focus from the dialog");
  });
  withAFakeObserver((fire) => {
    const active = { current: null as unknown };
    const { panel } = aPanel(active);
    panel.isConnected = false;
    keepTheKeyboardInside(panel as unknown as HTMLElement, () => true);
    fire();
    assert.equal(panel.focused, 0);
  });
});

test("with no panel, or where the page cannot be watched, there is nothing to do and nothing throws", async () => {
  const { keepTheKeyboardInside } = await import("./focusTrap.ts");
  keepTheKeyboardInside(null, () => true)();
  const real = (globalThis as { MutationObserver?: unknown }).MutationObserver;
  (globalThis as { MutationObserver?: unknown }).MutationObserver = undefined;
  try { keepTheKeyboardInside({} as unknown as HTMLElement, () => true)(); } finally { (globalThis as { MutationObserver?: unknown }).MutationObserver = real; }
});

test("both shared overlays keep the keyboard inside through the one function, and stop when they close", async () => {
  const fs = await import("node:fs");
  const path = await import("node:path");
  const web = path.join(import.meta.dirname, "..", "..");
  for (const overlay of ["modal.tsx", "drawer.tsx"]) {
    const src = fs.readFileSync(path.join(web, "components", "ui", overlay), "utf8");
    assert.match(src, /const stopKeeping = keepTheKeyboardInside\(panelRef\.current, overlay\.isTop\);/, `${overlay} does not watch for its focused control being taken away`);
    assert.match(src, /stopKeeping\(\);\s*\n\s*overlay\.close\(\);/, `${overlay} does not stop watching when it closes`);
  }
});
