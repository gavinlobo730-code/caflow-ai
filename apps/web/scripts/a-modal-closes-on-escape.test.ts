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
  const src = read("components/ClientFormModal.tsx");
  assertClosesOnEscape(functionBody(src, "ClientFormModal"), "ClientFormModal");
});

test("ClientFormModal does not close on Escape while saving", () => {
  const src = read("components/ClientFormModal.tsx");
  const body = stripComments(functionBody(src, "ClientFormModal"));
  assert.match(body, /!saving/);
});

test("engagements/page.tsx: CreateEngagementModal, TemplateModal and DetailModal each close on Escape", () => {
  const src = read("app/engagements/page.tsx");
  for (const name of ["CreateEngagementModal", "TemplateModal", "DetailModal"]) {
    assertClosesOnEscape(functionBody(src, name), name);
  }
});

test("clients/page.tsx: the Archive/Restore/Delete confirmations close on Escape, guarded on actionBusy", () => {
  const src = stripComments(read("app/clients/page.tsx"));
  assert.match(src, /addEventListener\("keydown"/);
  assert.match(src, /e\.key !== "Escape" \|\| actionBusy/);
  // All three targets are cleared, whichever one was open.
  for (const setter of ["setArchiveTarget(null)", "setRestoreTarget(null)", "setDeleteTarget(null)"]) {
    assert.ok(src.includes(setter), `missing ${setter}`);
  }
});
