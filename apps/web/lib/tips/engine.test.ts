// Run with: node --experimental-strip-types --test lib/tips/engine.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { nextStop, openTipsOn, placeTip, readTipsState, screenOf, tipToShow, TIP_GAP, TIP_MARGIN } from "./engine.ts";
import type { Tip } from "./registry.ts";

const tip = (id: string, path: string, anchor: string, roles?: Tip["roles"]): Tip =>
  ({ id, path, anchor, source: "x.tsx", title: id, body: id, holds: [], roles });
const TIPS: Tip[] = [
  tip("a1", "/", "menu"), tip("a2", "/", "search"),
  tip("b1", "/clients", "add", ["Partner", "Manager"]),
  tip("c1", "/books", "books", ["Partner"]),
];
const TOUR = ["/", "/clients", "/books"];
const all = () => true;

test("a screen's address is read without its trailing slash, its query or its fragment", () => {
  assert.equal(screenOf("/clients/"), "/clients");
  assert.equal(screenOf("/clients/?tab=all#top"), "/clients");
  assert.equal(screenOf("/"), "/");
  assert.equal(screenOf(""), "/");
});

test("the first tip of the screen that is not closed and whose anchor is on the page is the one shown", () => {
  const on = { on: true, seen: [] as string[] };
  assert.equal(tipToShow("/", "Partner", on, all, TIPS)?.id, "a1");
  assert.equal(tipToShow("/", "Partner", { on: true, seen: ["a1"] }, all, TIPS)?.id, "a2");
  assert.equal(tipToShow("/", "Partner", { on: true, seen: ["a1", "a2"] }, all, TIPS), null);
  // The first tip's anchor is not drawn: it is skipped, not closed, and the second is shown.
  assert.equal(tipToShow("/", "Partner", on, (a) => a !== "menu", TIPS)?.id, "a2");
  assert.equal(tipToShow("/elsewhere", "Partner", on, all, TIPS), null);
});

test("tips that are off, and a state that could not be read, show nothing", () => {
  assert.equal(tipToShow("/", "Partner", { on: false, seen: [] }, all, TIPS), null);
  assert.equal(tipToShow("/", "Partner", null, all, TIPS), null);
  // Only a real `true` turns them on: a truthy stub answer does not.
  assert.equal(tipToShow("/", "Partner", { on: 1 as unknown as boolean, seen: [] }, all, TIPS), null);
});

test("a tip for some roles is not shown to another, nor to a person whose role is not known yet", () => {
  const on = { on: true, seen: [] as string[] };
  assert.equal(tipToShow("/clients", "Manager", on, all, TIPS)?.id, "b1");
  assert.equal(tipToShow("/clients", "Executive", on, all, TIPS), null);
  assert.equal(tipToShow("/clients", null, on, all, TIPS), null);
  assert.deepEqual(openTipsOn("/books", "Manager", [], TIPS), []);
});

test("Next leads to the next screen of the tour that still has a tip for this person", () => {
  // Two tips on the dashboard: closing the first leaves the second, so there is no Next yet.
  assert.equal(nextStop("/", "Partner", [], "a1", TIPS, TOUR), null);
  assert.equal(nextStop("/", "Partner", ["a1"], "a2", TIPS, TOUR), "/clients");
  // An Executive has no tip on Clients or on the books: the tour ends on the dashboard.
  assert.equal(nextStop("/", "Executive", ["a1"], "a2", TIPS, TOUR), null);
  // A Manager skips nothing on Clients and has nothing after it.
  assert.equal(nextStop("/clients", "Manager", ["a1", "a2"], "b1", TIPS, TOUR), null);
  assert.equal(nextStop("/clients", "Partner", ["a1", "a2"], "b1", TIPS, TOUR), "/books");
  // A stop whose tips are already closed is passed over.
  assert.equal(nextStop("/", "Partner", ["a1", "b1"], "a2", TIPS, TOUR), "/books");
  assert.equal(nextStop("/books", "Partner", [], "c1", TIPS, TOUR), null);
  assert.equal(nextStop("/not-on-the-tour", "Partner", [], null, TIPS, TOUR), null);
});

test("the pop-up sits below its anchor, above when there is no room below, and inside the window", () => {
  const win = { width: 1200, height: 800 };
  const size = { width: 320, height: 150 };
  const below = placeTip({ top: 100, left: 500, width: 100, height: 40 }, size, win)!;
  assert.equal(below.side, "below");
  assert.equal(below.top, 140 + TIP_GAP);
  assert.equal(below.left, 550 - 160);
  assert.equal(below.arrowLeft, 160);
  const above = placeTip({ top: 700, left: 500, width: 100, height: 40 }, size, win)!;
  assert.equal(above.side, "above");
  assert.equal(above.top, 700 - TIP_GAP - 150);
  // Against the right edge the pop-up stays inside and its arrow still points at the anchor.
  const right = placeTip({ top: 10, left: 1150, width: 40, height: 30 }, size, win)!;
  assert.equal(right.left, 1200 - 320 - TIP_MARGIN);
  assert.equal(right.arrowLeft, 302);
  const left = placeTip({ top: 10, left: 0, width: 20, height: 30 }, size, win)!;
  assert.equal(left.left, TIP_MARGIN);
  assert.equal(left.arrowLeft, 18);
});

test("an anchor that is not in view, or has no size, gets no pop-up", () => {
  const win = { width: 1200, height: 800 };
  const size = { width: 320, height: 150 };
  assert.equal(placeTip({ top: 900, left: 100, width: 50, height: 30 }, size, win), null);
  assert.equal(placeTip({ top: -200, left: 100, width: 50, height: 30 }, size, win), null);
  assert.equal(placeTip({ top: 100, left: 100, width: 0, height: 0 }, size, win), null);
});

test("the server's answer is read strictly, and anything else is no tips", () => {
  assert.deepEqual(readTipsState({ on: true, chosen: false, seen: ["a", 3, "b"] }), { on: true, chosen: false, seen: ["a", "b"] });
  assert.deepEqual(readTipsState({ on: false, chosen: true, seen: [] }), { on: false, chosen: true, seen: [] });
  for (const bad of [null, undefined, [], "on", { seen: [] }, { on: "true" }, { on: 1 }]) assert.equal(readTipsState(bad), null);
});
