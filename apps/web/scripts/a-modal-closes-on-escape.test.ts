// Every dialog closes on Escape, matching the shared Modal
// (components/ui/modal.tsx), Drawer and ConfirmDialog — not only its own X
// icon and Cancel button.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-modal-closes-on-escape.test.ts
//
// WHAT WAS WRONG (sweep-client-payroll-07, sweep-clients-admin-08)
//     components/ui/modal.tsx, drawer.tsx and confirm-dialog.tsx all close on
//     Escape through a document/window keydown listener. Six hand-rolled
//     `fixed inset-0` overlays did not: the shared CsvImportModal (used by
//     every CSV import screen, including the payroll Import Employees modal),
//     ClientFormModal, the three engagements/page.tsx modals
//     (CreateEngagementModal, TemplateModal, DetailModal), and the clients
//     page's own inline Archive/Restore/Delete confirmations. Only their X/
//     Cancel controls closed them.
//
// THE FIX
//     Each now carries its own `window.addEventListener("keydown", …)`
//     guarding `e.key === "Escape"`, following the pattern already used by
//     components/SearchModal.tsx — and refusing to close while its own save/
//     import/action is in flight, so Escape can't abandon a request that has
//     already gone out.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

/** The source of one top-level `function <name>(` declaration through to the
 *  next top-level `function` (or end of file) — good enough for these files,
 *  where every component is declared at column 0. */
function functionBody(src: string, name: string): string {
  const m = new RegExp(`(?:^|\\n)(?:export\\s+(?:default\\s+)?)?function ${name}\\(`).exec(src);
  assert.ok(m, `function ${name} not found`);
  const start = m.index + m[0].length;
  const rest = src.slice(start);
  const next = rest.search(/\nfunction |\nexport default function /);
  return next === -1 ? rest : rest.slice(0, next);
}

/** Escape is wired: a keydown listener on window/document that checks
 *  e.key === "Escape" against real code (not just a comment naming it). */
function assertClosesOnEscape(rawBody: string, label: string) {
  const body = stripComments(rawBody);
  assert.match(body, /addEventListener\("keydown"/, `${label}: no keydown listener`);
  assert.match(body, /e\.key === "Escape"/, `${label}: Escape is not checked`);
}

test("CsvImportModal (payroll's Import Employees, and every other CSV import screen) closes on Escape", () => {
  const src = read("components/CsvImportModal.tsx");
  assertClosesOnEscape(functionBody(src, "CsvImportModal"), "CsvImportModal");
});

test("CsvImportModal does not close on Escape while the import is running", () => {
  const src = read("components/CsvImportModal.tsx");
  const body = stripComments(functionBody(src, "CsvImportModal"));
  assert.match(body, /step !== "importing"/);
});

test("ClientFormModal (Add/Edit Client) closes on Escape", () => {
  // Since POST-A-130's eighth step it is the shared Modal, which closes on Escape by calling its `onClose`. A key listener of its own
  // would be dead code (the Modal stops the key first) that reads as the thing closing the dialog, so there must be none.
  const body = stripComments(functionBody(read("components/ClientFormModal.tsx"), "ClientFormModal"));
  assert.match(body, /<Modal title=\{editClient \? "Edit Client" : "Add New Client"\}/, "the client form is not the shared Modal");
  assert.doesNotMatch(body, /addEventListener\("keydown"/, "the client form listens for keys itself again");
});

test("ClientFormModal does not close on Escape while saving", () => {
  const body = stripComments(functionBody(read("components/ClientFormModal.tsx"), "ClientFormModal"));
  assert.match(body, /onClose=\{\(\) => \{ if \(!saving\) onClose\(\); \}\}/, "the client form can be closed while a save is in flight");
});

test("engagements/page.tsx: CreateEngagementModal, TemplateModal and DetailModal each close on Escape", () => {
  // Since POST-A-130's fourteenth step each is the shared Modal, which closes on Escape by calling its `onClose` (and only as the top
  // dialog). The rule held here is that each one's `onClose` is held while its own request is out, and that none keeps the key listener
  // it used to have: the Modal stops the key before a window listener hears it, so one here would be dead code that reads as the thing
  // closing the dialog.
  const src = stripComments(read("app/engagements/page.tsx"));
  for (const [name, flag] of [["CreateEngagementModal", "saving"], ["TemplateModal", "saving"], ["DetailModal", "actionLoading"]]) {
    const body = functionBody(src, name);
    assert.match(body, /<Modal\s+title=/, `${name} is not the shared Modal`);
    assert.doesNotMatch(body, /addEventListener\("keydown"/, `${name} listens for keys itself again`);
    assert.ok(body.includes(`onClose={() => { if (!${flag}) onClose(); }}`), `${name} can be closed while its request is in flight`);
  }
});

test("clients/page.tsx: the Archive/Restore/Delete confirmations close on Escape, guarded on actionBusy", () => {
  // Since POST-A-130's seventh step each is the shared Modal, which closes on Escape by calling its `onClose` (and only as the top dialog):
  // the rule this test holds is that each one's `onClose` clears its own target and is held while an action is in flight. The page's own
  // keydown listener is gone, and must stay gone: the Modal stops the key before a window listener hears it, so one here would be dead code
  // that reads as the thing closing the dialog.
  const src = stripComments(read("app/clients/page.tsx"));
  assert.doesNotMatch(src, /addEventListener\("keydown"/, "the page listens for keys itself again");
  for (const [title, setter] of [["Archive Client", "setArchiveTarget(null)"], ["Restore Client", "setRestoreTarget(null)"], ["Permanently Delete", "setDeleteTarget(null)"]]) {
    const at = src.indexOf(`<Modal title="${title}"`);
    assert.ok(at >= 0, `${title} is not the shared Modal`);
    const open = src.slice(at, src.indexOf(">\n", src.indexOf("onClose=", at)));
    assert.match(open, /onClose=\{\(\) => \{ if \(!actionBusy\) \{/, `${title} can be closed while its action is in flight`);
    assert.ok(open.includes(setter), `${title}: closing it does not clear its target`);
  }
});
