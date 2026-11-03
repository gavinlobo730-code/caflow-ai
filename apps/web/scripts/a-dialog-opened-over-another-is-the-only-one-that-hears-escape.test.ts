// POST-A-128 - dialogs STACK, and one Escape closes only the top one.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-dialog-opened-over-another-is-the-only-one-that-hears-escape.test.ts
//
// WHAT WAS WRONG
//     Every shared dialog listens for Escape on the document. With two open (the bank's entry dialog and the split, settle or match-finder
//     dialog it opens from inside itself; a confirmation shown over a Modal; a Modal over a Drawer) both heard one press. The Modal listens
//     in the capture phase and stops the event, so a ConfirmDialog opened over a Modal never heard Escape at all and the Modal beneath it
//     closed instead. The bank's four dialogs could not move onto the shared Modal until it stacked and took a footer.
//
// THE RULES, NOT SPELLINGS
//     * the Modal, the Drawer and the ConfirmDialog each register in `lib/ui/overlayStack` when they open, take themselves off when they
//       close, and act on Escape only when they are the top one;
//     * the Modal takes a `footer` that stays at the bottom of its panel;
//     * the bank's entry dialog and the three it opens are the shared Modal, and the entry dialog's shell is nothing else.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

/** What is wrong with a shared dialog's use of the stack, as sentences (empty when it is right). */
export function stackProblems(src: string): string[] {
  const found: string[] = [];
  if (!/import \{[^}]*\bopenOverlay\b[^}]*\} from "@\/lib\/ui\/overlayStack"/.test(src)) found.push("does not import openOverlay");
  if (!/const overlay = openOverlay\(\);/.test(src)) found.push("does not register when it opens");
  if (!/overlay\.close\(\)/.test(src)) found.push("does not take itself off the stack when it closes");
  if (!/overlay\.isTop\(\)/.test(src)) found.push("does not ask whether it is the top dialog before acting on Escape");
  return found;
}

for (const file of ["components/ui/modal.tsx", "components/ui/drawer.tsx", "components/ui/confirm-dialog.tsx"]) {
  test(`${file}: registers on the stack, leaves it, and acts on Escape only as the top dialog`, () => {
    const src = read(file);
    assert.deepEqual(stackProblems(src), []);
    // negative controls on the real text: each way of getting it wrong is found
    assert.notDeepEqual(stackProblems(src.replace(/overlay\.isTop\(\)/g, "true")), []);
    assert.notDeepEqual(stackProblems(src.replace(/overlay\.close\(\)/g, "void 0")), []);
    assert.notDeepEqual(stackProblems(src.replace("const overlay = openOverlay();", "const overlay = { isTop: () => true, close() {} };")), []);
  });
}

test("the Escape branch asks isTop BEFORE it stops the event or closes", () => {
  // A dialog that stopped the event first would swallow the press the top dialog needs (the capture-phase Modal over a ConfirmDialog).
  for (const file of ["components/ui/modal.tsx", "components/ui/drawer.tsx"]) {
    const src = read(file);
    const at = src.indexOf('e.key === "Escape"');
    assert.ok(at !== -1, `${file}: no Escape branch`);
    const branch = src.slice(at, at + 700);
    const ask = branch.indexOf("overlay.isTop()");
    const stop = branch.indexOf("e.stopPropagation()");
    assert.ok(ask !== -1 && stop !== -1 && ask < stop, `${file}: isTop must be asked before stopPropagation`);
    // negative control: swapping the two lines is found
    const swapped = branch.replace("if (!overlay.isTop()) return;", "").replace("e.stopPropagation();", "e.stopPropagation(); if (!overlay.isTop()) return;");
    assert.ok(swapped.indexOf("overlay.isTop()") > swapped.indexOf("e.stopPropagation()"), "the control must put the ask after the stop");
  }
});

test("the Modal takes a footer and keeps it at the bottom of the panel", () => {
  const src = read("components/ui/modal.tsx");
  assert.match(src, /footer\?: ReactNode/);
  assert.match(src, /\{footer && \(\s*<div className="sticky bottom-0[^"]*">\s*\{footer\}/);
});

test("the bank's entry dialog and the three it opens are the shared Modal", () => {
  const entry = read("components/banking/EntryDetailModal.tsx");
  assert.match(entry, /import \{ Modal \} from "@\/components\/ui\/modal"/);
  assert.match(entry, /<Modal title=\{title\} note=\{note\} footer=\{footer\} onClose=\{onClose\} maxWidthClass="max-w-xl">/);
  for (const file of ["SplitAcrossLedgersModal", "SettleDocumentsModal", "FindMatchModal"]) {
    const src = read(`components/banking/${file}.tsx`);
    assert.match(src, /import \{ Modal \} from "@\/components\/ui\/modal"/, `${file} must import the shared Modal`);
    assert.match(src, /<Modal\s/, `${file} must render the shared Modal`);
    assert.doesNotMatch(src, /fixed inset-0/, `${file} still builds its own overlay`);
    // a request in flight ignores Escape, the backdrop and the X, as it ignores Cancel
    assert.match(src, /onClose=\{\(\) => \{ if \((?:!saving|picking === null)\) onClose\(\); \}\}/, `${file}: a request in flight must hold the dialog open`);
  }
  assert.doesNotMatch(entry, /fixed inset-0/);
});

test("an Escape inside an open picker is left to the picker, before the dialog stops the event", () => {
  for (const file of ["components/ui/modal.tsx", "components/ui/drawer.tsx"]) {
    const src = read(file);
    assert.match(src, /import \{ escapeBelongsToAnOpenPicker, openOverlay \} from "@\/lib\/ui\/overlayStack"/, `${file} does not import the picker rule`);
    const at = src.indexOf('e.key === "Escape"');
    const branch = src.slice(at, at + 1100);
    const picker = branch.indexOf("escapeBelongsToAnOpenPicker(");
    const stop = branch.indexOf("e.stopPropagation()");
    assert.ok(picker !== -1 && stop !== -1 && picker < stop, `${file}: the picker rule must be asked before stopPropagation`);
    const swapped = branch.replace(/\n[^\n]*escapeBelongsToAnOpenPicker\([^\n]*\n/, "\n").replace("e.stopPropagation();", "e.stopPropagation(); if (escapeBelongsToAnOpenPicker(e.target as Element | null)) return;");
    assert.ok(swapped.indexOf("escapeBelongsToAnOpenPicker(") > swapped.indexOf("e.stopPropagation()"), "the control must put the picker rule after the stop");
  }
  assert.match(read("components/ui/drawer.tsx"), /e\.defaultPrevented \|\| escapeBelongsToAnOpenPicker\(/, "the Drawer also honours an Escape a child already handled");
});

test("a dialog moves focus to the first control a person can focus, not to a hidden one", () => {
  const src = read("components/ui/modal.tsx");
  assert.match(src, /firstFormField\(panelRef\.current\) \?\? panelRef\.current\)\?\.focus\(\)/);
  assert.doesNotMatch(src, /querySelector<HTMLElement>\("input, select, textarea"\)/, "the unfiltered first-field query is back");
});

test("the fixed-asset drawers ignore Escape, the backdrop and Cancel while a save is in flight", () => {
  const src = read("app/clients/[id]/fixed-assets/page.tsx");
  const leaves = src.match(/const leave = async \(\) => \{[^\n]*\n/g) ?? [];
  assert.equal(leaves.length, 2, "both drawers define leave");
  for (const l of leaves) assert.match(l, /if \(submittingRef\.current\) return;/, `a drawer's leave does not hold while saving: ${l.trim()}`);
});

test("the Modal's footer bar is flush with the panel's bottom edge, which a plain -mb-4 cannot do under space-y-3", () => {
  const src = read("components/ui/modal.tsx");
  assert.match(src, /sticky bottom-0 -mx-4 !-mb-4/);
  assert.match(src, /footer \? " scroll-pb-16" : ""/);
});

