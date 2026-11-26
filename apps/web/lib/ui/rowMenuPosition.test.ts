// Where a list row's menu opens (POST-A-395). Run with:
//   node --experimental-strip-types --test lib/ui/rowMenuPosition.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { LIST_EDGE, ROW_MENU_GAP, ROW_MENU_ROOM, listPosition, rowMenuPosition, type RowMenuPlace } from "./rowMenuPosition.ts";

const VIEW = { width: 1440, height: 900 };

test("a row with room below opens its menu under the button", () => {
  assert.deepEqual(rowMenuPosition({ top: 100, bottom: 120, right: 1300 }, 176, VIEW), { top: 120 + ROW_MENU_GAP, left: 1300 - 176 });
});

test("a row near the foot of the window opens its menu above the button, anchored by its bottom edge", () => {
  const place: RowMenuPlace = rowMenuPosition({ top: 860, bottom: 880, right: 1300 }, 176, VIEW);
  assert.equal(place.top, undefined);
  assert.deepEqual(place, { bottom: 900 - 860 + ROW_MENU_GAP, left: 1300 - 176 });
});

test("exactly the room below is enough, one pixel less on a tall window is not", () => {
  const bottom = VIEW.height - ROW_MENU_ROOM;
  assert.ok(rowMenuPosition({ top: bottom - 20, bottom, right: 600 }, 176, VIEW).top !== undefined);
  assert.ok(rowMenuPosition({ top: bottom - 19, bottom: bottom + 1, right: 600 }, 176, VIEW).bottom !== undefined);
});

test("on a window too short for either, the menu goes to the side with more room", () => {
  const short = { width: 800, height: 300 };
  assert.ok(rowMenuPosition({ top: 100, bottom: 120, right: 600 }, 176, short).top !== undefined, "more room below");
  assert.ok(rowMenuPosition({ top: 200, bottom: 220, right: 600 }, 176, short).bottom !== undefined, "more room above");
});

test("the menu is kept inside the window's width", () => {
  assert.equal(rowMenuPosition({ top: 100, bottom: 120, right: 100 }, 176, VIEW).left, 8);
  assert.equal(rowMenuPosition({ top: 100, bottom: 120, right: 1440 }, 176, VIEW).left, 1440 - 176 - 8);
});

test("no list row's menu is placed by hand under its button any more", () => {
  const root = path.join(import.meta.dirname, "..", "..");
  const offenders: string[] = [];
  for (const rel of ["app/clients/[id]/sales/page.tsx", "app/clients/[id]/purchases/page.tsx"]) {
    const text = fs.readFileSync(path.join(root, rel), "utf8");
    if (/top:\s*r\.bottom\s*\+\s*4/.test(text)) offenders.push(rel);
    assert.match(text, /rowMenuAt\(/, `${rel} no longer places its row menus through rowMenuAt`);
  }
  assert.deepEqual(offenders, []);
});

// ── The shared picker's list (POST-A-471) ────────────────────────────────────

test("a picker with room below opens its list under the box, left-aligned, as tall as the room it has", () => {
  assert.deepEqual(listPosition({ top: 100, bottom: 136, left: 300 }, 256, VIEW, 256),
    { top: 136 + ROW_MENU_GAP, left: 300, maxHeight: 900 - 136 - ROW_MENU_GAP - LIST_EDGE });
});

test("a picker near the foot of a 720-pixel window opens its list above the box, and every row is inside the window", () => {
  const short = { width: 1280, height: 720 };
  const box = { top: 640, bottom: 676, left: 300 };
  const place = listPosition(box, 256, short, 256);
  assert.equal(place.top, undefined);
  assert.equal(place.bottom, 720 - 640 + ROW_MENU_GAP);
  // The list's top edge is at least LIST_EDGE inside the window however tall it grows to its cap.
  assert.ok(720 - place.bottom! - place.maxHeight >= LIST_EDGE);
});

test("on a window too short for the list either way, the list goes to the bigger side and is capped to it", () => {
  const short = { width: 800, height: 300 };
  const down = listPosition({ top: 100, bottom: 130, left: 10 }, 256, short, 448);
  assert.ok(down.top !== undefined && down.top + down.maxHeight <= 300 - LIST_EDGE);
  const up = listPosition({ top: 200, bottom: 230, left: 10 }, 256, short, 448);
  assert.ok(up.bottom !== undefined && 300 - up.bottom - up.maxHeight >= LIST_EDGE);
});

test("the list is kept inside the window's width", () => {
  assert.equal(listPosition({ top: 0, bottom: 30, left: 1300 }, 416, VIEW, 256).left, 1440 - 416 - LIST_EDGE);
  assert.equal(listPosition({ top: 0, bottom: 30, left: -20 }, 256, VIEW, 256).left, LIST_EDGE);
});

test("the shared picker places its list through listPosition and nowhere by hand", () => {
  const root = path.join(import.meta.dirname, "..", "..");
  const text = fs.readFileSync(path.join(root, "components", "ui", "combobox.tsx"), "utf8");
  assert.match(text, /listPosition\(/, "the combobox no longer places its list through listPosition");
  assert.doesNotMatch(text, /top:\s*r\.bottom\s*\+/, "the combobox places its list under the box by hand again");
});
