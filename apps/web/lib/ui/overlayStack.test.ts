// POST-A-128: one Escape closes only the top dialog.
// Run with: node --experimental-strip-types --test lib/ui/overlayStack.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { openOverlay, openOverlayCount } from "./overlayStack.ts";

test("a lone dialog is the top one, and nothing is left when it closes", () => {
  const before = openOverlayCount();
  const a = openOverlay();
  assert.equal(a.isTop(), true);
  a.close();
  assert.equal(openOverlayCount(), before);
});

test("the newest dialog is the top one and the one beneath is not, until the top closes", () => {
  const a = openOverlay();
  const b = openOverlay();
  assert.equal(b.isTop(), true);
  assert.equal(a.isTop(), false, "the lower dialog must not act on Escape while another is open over it");
  b.close();
  assert.equal(a.isTop(), true, "closing the top one gives the lower one its Escape back");
  a.close();
});

test("a dialog closed out of order does not disturb the others", () => {
  const a = openOverlay();
  const b = openOverlay();
  const c = openOverlay();
  b.close();                       // the middle one goes (its parent unmounted it)
  assert.equal(c.isTop(), true);
  assert.equal(a.isTop(), false);
  c.close();
  assert.equal(a.isTop(), true);
  a.close();
});

test("closing twice is closing once", () => {
  const before = openOverlayCount();
  const a = openOverlay();
  const b = openOverlay();
  b.close();
  b.close();
  assert.equal(openOverlayCount(), before + 1);
  assert.equal(a.isTop(), true, "a second close of b must not have removed a");
  a.close();
  assert.equal(openOverlayCount(), before);
});

test("a closed dialog is not the top one", () => {
  const a = openOverlay();
  a.close();
  const b = openOverlay();
  assert.equal(a.isTop(), false);
  assert.equal(b.isTop(), true);
  b.close();
});
