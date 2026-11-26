// PRE-A-022 follow-up. A full-window layer opening over another takes the level just above it, so a dialog opened
// from a panel drawn at a higher level is not hidden behind the panel that opened it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { coversTheWindow, levelAboveOpenLayers } from "./layerStack.ts";

test("with nothing open a layer keeps its own level", () => {
  assert.equal(levelAboveOpenLayers(70, []), null);
  assert.equal(levelAboveOpenLayers(null, []), null);
});

test("a dialog at 70 opened over the product manager at 80 takes 81, above the panel that opened it", () => {
  assert.equal(levelAboveOpenLayers(70, [80]), 81);
});

test("a side panel at 50 opened over a dialog at 70 takes 71", () => {
  assert.equal(levelAboveOpenLayers(50, [70]), 71);
});

test("a layer already above everything open keeps its own level", () => {
  assert.equal(levelAboveOpenLayers(80, [50, 70]), null);
});

test("an equal level is raised by one, so the newer layer is in front whatever the order on the page", () => {
  assert.equal(levelAboveOpenLayers(70, [70]), 71);
});

test("a layer with no level of its own goes above the highest open one", () => {
  assert.equal(levelAboveOpenLayers(null, [50, 110]), 111);
});

test("a full-window panel counts as a layer, a toast or a menu does not", () => {
  const win = { width: 1440, height: 900 };
  assert.equal(coversTheWindow({ width: 1440, height: 900 }, win), true);
  assert.equal(coversTheWindow({ width: 1440, height: 852 }, win), true, "a backdrop below a 48 px bar");
  assert.equal(coversTheWindow({ width: 320, height: 60 }, win), false, "a toast");
  assert.equal(coversTheWindow({ width: 240, height: 400 }, win), false, "a dropdown");
});
