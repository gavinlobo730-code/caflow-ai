// Where a list row's menu opens (POST-A-395). Run with:
//   node --experimental-strip-types --test lib/ui/rowMenuPosition.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { ROW_MENU_GAP, ROW_MENU_ROOM, rowMenuPosition, type RowMenuPlace } from "./rowMenuPosition.ts";

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
