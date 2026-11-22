// A ROW'S "MORE" MENU IS THE SHARED ONE, AND NO SCREEN DRAWS A LAYER OVER THE WINDOW TO CLOSE IT. Run with:
//   node --experimental-strip-types --test scripts/a-row-menu-is-the-shared-one.test.ts
//
// THE DEFECT (POST-A-130)
//   Eight row menus on the Sales and Purchases screens were each two siblings built by hand: an invisible `fixed inset-0` layer whose
//   only job was to catch the click that closes the menu, and the menu. Opened from the keyboard, focus stayed on the row's button
//   behind the layer, Escape did nothing, and the first click anywhere (another row's own button included) was swallowed.
//
// THE RULE
//   * Wherever a screen holds a row menu in state (`setMenu(null)` closes it), the menu is drawn by `components/ui/row-menu`, once per
//     menu, and the screen draws no window-covering layer beside it (the overlay guard holds that no new one appears anywhere).
//   * Every button that opens one says that it opens something and whether it is open (`aria-haspopup`, `aria-expanded`).
//   * The shared menu is a named group that moves focus in, gives it back, closes on Escape, moves by the arrow keys, and closes on a
//     click outside WITHOUT stopping that click (the opening button's own click aside). These are held by text here and driven in a
//     browser by the weekly `row-menus` group; the key rule itself is `lib/ui/rowMenuKeys`, with its own test.
//
// WHAT THIS DOES NOT SEE
//   A menu held under another state name, and a menu built from a library. It does not prove behaviour: the drive does.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "out") continue;
      walk(rel, out);
    } else if (/\.tsx$/.test(e.name)) out.push(rel);
  }
  return out;
}

const count = (s: string, re: RegExp) => (s.match(re) ?? []).length;

/** Screens that hold a row menu in state: they close it with `setMenu(null)` and open it with `rowMenuAt`. */
const SCREENS = ["app", "components"].flatMap((d) => walk(d)).filter((f) => !f.startsWith("components/ui/"))
  .filter((f) => { const s = stripComments(read(f)); return /\bsetMenu\(null\)/.test(s) && /\browMenuAt\(/.test(s); });

test("the screens with row menus are found, and each draws every menu with the shared RowMenu", () => {
  assert.ok(SCREENS.includes("app/clients/[id]/sales/page.tsx") && SCREENS.includes("app/clients/[id]/purchases/page.tsx"),
    `the scan has gone blind: it found ${JSON.stringify(SCREENS)}`);
  for (const f of SCREENS) {
    const s = stripComments(read(f));
    const states = count(s, /const \[menu, setMenu\] = useState</g);
    assert.ok(states > 0, `${f}: no menu state found`);
    assert.equal(count(s, /<RowMenu place=\{menu\}[^>]*onClose=\{\(\) => setMenu\(null\)\}>/g), states, `${f}: a row menu is not the shared RowMenu`);
    assert.equal(count(s, /<\/RowMenu>/g), states, `${f}: a RowMenu is not closed`);
    assert.doesNotMatch(s, /fixed inset-0[^"]*"\s+onClick=\{\(\) => setMenu\(null\)\}/, `${f}: a window-covering click-catcher is back`);
  }
});

test("every button that opens a row menu says that it opens one and whether it is open", () => {
  for (const f of SCREENS) {
    const s = stripComments(read(f));
    const openers = s.match(/onClick=\{\(e\) => openMenuFor\(e, \w+\)\}[\s\S]{0,400}?\n\s*>/g) ?? [];
    assert.equal(openers.length, count(s, /const \[menu, setMenu\] = useState</g), `${f}: one opening button per menu`);
    for (const o of openers) {
      assert.match(o, /aria-haspopup="true"/, `${f}: an opening button does not say it opens something: ${o.slice(0, 80)}`);
      assert.match(o, /aria-expanded=\{menu\?\.id === \w+\.id\}/, `${f}: an opening button does not say whether its menu is open: ${o.slice(0, 80)}`);
      assert.match(o, /aria-label=\{`Actions for /, `${f}: an opening button has no name: ${o.slice(0, 80)}`);
    }
  }
});

test("the shared menu is a named group with no layer behind it, and holds its keyboard and click rules", () => {
  const src = read("components/ui/row-menu.tsx");
  const code = stripComments(src);
  assert.match(code, /role="group"/);
  assert.match(code, /aria-label=\{label\}/);
  assert.doesNotMatch(code, /inset-0/, "the shared row menu draws a layer over the window");
  // Focus in on opening, and back to the opener on closing while focus is still inside it.
  assert.match(code, /openerRef\.current = \(document\.activeElement as HTMLElement \| null\) \?\? null;/);
  assert.match(code, /if \(menu && menu\.contains\(document\.activeElement\)\) openerRef\.current\?\.focus\?\.\(\);/);
  // Escape is this menu's alone; the arrow keys go through the one tested rule.
  assert.match(code, /if \(e\.key === "Escape"\) \{\s*e\.stopPropagation\(\);\s*onCloseRef\.current\(\);/);
  assert.match(code, /nextActionIndex\(e\.key, /);
  // A click outside closes it and is not stopped, except on the button that opened it.
  assert.match(code, /document\.addEventListener\("click", onClick, true\)/);
  assert.match(code, /if \(openerRef\.current\?\.contains\(target\)\) e\.stopPropagation\(\);\s*onCloseRef\.current\(\);/);
  assert.equal(count(code, /stopPropagation\(\)/g), 2, "a second place stops an event: a click outside must reach what was clicked");
});
