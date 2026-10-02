// What a key press does on a clickable table row (frontend_ux-16). Run with:
//   node --experimental-strip-types --test lib/table/rowKeyboard.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  INTERACTIVE_SELECTOR, isFromInteractiveControl, rowKeyAction, stepIndex, type ElementLike,
} from "./rowKeyboard.ts";

const onRow = (key: string, extra: Record<string, unknown> = {}) =>
  rowKeyAction({ key, fromRow: true, ...extra });

test("Enter and Space activate the row", () => {
  assert.equal(onRow("Enter"), "activate");
  assert.equal(onRow(" "), "activate");
  assert.equal(onRow("Spacebar"), "activate", "older engines");
});

test("arrows move, and only up and down", () => {
  assert.equal(onRow("ArrowDown"), "next");
  assert.equal(onRow("ArrowUp"), "previous");
  assert.equal(onRow("Down"), "next");
  assert.equal(onRow("Up"), "previous");
  for (const k of ["ArrowLeft", "ArrowRight", "Home", "End", "PageDown", "Tab", "Escape", "a", "Delete"]) {
    assert.equal(onRow(k), null, k);
  }
});

test("a key that went to a CONTROL inside the row is not the row's", () => {
  // Space on a checkbox toggles the checkbox; Enter in a cell's input submits
  // that input; an arrow in a select changes the selection.
  for (const k of ["Enter", " ", "ArrowDown", "ArrowUp"]) {
    assert.equal(rowKeyAction({ key: k, fromRow: false }), null, k);
  }
});

test("a modifier hands the key back to the browser and the page", () => {
  for (const mod of ["ctrlKey", "metaKey", "altKey"]) {
    assert.equal(onRow("Enter", { [mod]: true }), null, mod);
    assert.equal(onRow("ArrowDown", { [mod]: true }), null, mod);
  }
});

test("a key somebody already handled is not handled twice", () => {
  assert.equal(onRow("Enter", { defaultPrevented: true }), null);
});

test("stepping clamps at both ends instead of wrapping", () => {
  assert.equal(stepIndex(0, 3, "next"), 1);
  assert.equal(stepIndex(1, 3, "next"), 2);
  assert.equal(stepIndex(2, 3, "next"), 2, "the last row stays the last row");
  assert.equal(stepIndex(2, 3, "previous"), 1);
  assert.equal(stepIndex(0, 3, "previous"), 0, "and so does the first");
});

test("stepping from a row that is not in the list lands on the first; an empty list lands nowhere", () => {
  assert.equal(stepIndex(-1, 3, "next"), 0);
  assert.equal(stepIndex(-1, 3, "previous"), 0);
  assert.equal(stepIndex(0, 0, "next"), -1);
  assert.equal(stepIndex(-1, 0, "previous"), -1);
});

// ── the element rule ─────────────────────────────────────────────────────────

/** A tiny tree: row > cell > control, with `closest` doing what the DOM does. */
function tree(controlMatches: boolean) {
  const row: ElementLike & { id: string } = {
    id: "row", closest: () => null, contains: () => true,
  };
  const control: ElementLike & { id: string } = {
    id: "control",
    closest: (sel: string) => (controlMatches && sel === INTERACTIVE_SELECTOR ? control : null),
    contains: () => true,
  };
  // `row.contains(x)` is true for anything inside; a control outside the row is below.
  row.contains = (other) => other === control || other === row;
  return { row, control };
}

test("a click that began on a link, button or input inside the row is that control's click", () => {
  const { row, control } = tree(true);
  assert.equal(isFromInteractiveControl(control, row), true);
});

test("a click on the row's own cell is the row's click", () => {
  const { row, control } = tree(false);
  assert.equal(isFromInteractiveControl(control, row), false);
});

test("the row itself never counts as the control, even if it carried a role", () => {
  const row: ElementLike = { closest: () => row, contains: () => true };
  assert.equal(isFromInteractiveControl(row, row), false);
});

test("a control OUTSIDE the row (an ancestor link wrapping the whole table) is not 'inside' it", () => {
  const outer: ElementLike = { closest: () => outer, contains: () => false };
  const row: ElementLike = { closest: () => outer, contains: () => false };
  assert.equal(isFromInteractiveControl(row, row), false);
  const cell: ElementLike = { closest: () => outer, contains: () => false };
  assert.equal(isFromInteractiveControl(cell, row), false);
});

test("no target is not interactive", () => {
  const { row } = tree(true);
  assert.equal(isFromInteractiveControl(null, row), false);
  assert.equal(isFromInteractiveControl(undefined, row), false);
});

test("the selector names the controls a row is likely to hold", () => {
  for (const s of ["a[href]", "button", "input", "select", "textarea", "label", "[role='checkbox']", "[role='button']"]) {
    assert.ok(INTERACTIVE_SELECTOR.includes(s), s);
  }
});
