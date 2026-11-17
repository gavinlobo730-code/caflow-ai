// POST-A-455, part 1. A button in the client workspace that only a Partner (or a Manager and a Partner) may use is offered
// only to someone the route behind it admits. Each row below names the button, the variable or component that gates it,
// the pair the screen asks, and the route the button calls; the pair is read off the route in the API source, so a route
// that changes its permission fails here until the screen follows.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gatedBy, gatePair, routePair } from "./buttonGates.ts";

const WEB = join(import.meta.dirname, "..");
const API = join(WEB, "..", "api");
const read = (...p: string[]) => readFileSync(join(...p), "utf8");

type Row = {
  what: string; file: string[]; anchor: string; gate: string; gateExpr?: string;
  router: string; method: string; path: string;
};
const C = ["app", "clients", "[id]"];
const YE = [...C, "year-end", "[engagementId]"];
const ROWS: Row[] = [
  { what: "payroll Finalise", file: [...C, "payroll", "page.tsx"], anchor: `onClick={() => finalizeRun(r.id)}`, gate: "mayFinalize",
    router: "payroll.py", method: "post", path: "/runs/{run_id}/finalize" },
  { what: "payroll Write loans down", file: [...C, "payroll", "page.tsx"], anchor: `onClick={() => writeDownLoans(r)}`, gate: "mayFinalize",
    router: "payroll.py", method: "post", path: "/runs/{run_id}/loan-writedown" },
  { what: "payroll Record payment", file: [...C, "payroll", "page.tsx"], anchor: `onClick={() => setDisburseRun(r)}`, gate: "mayFinalize",
    router: "payroll.py", method: "post", path: "/runs/{run_id}/disburse" },
  { what: "payroll Reverse", file: [...C, "payroll", "page.tsx"], anchor: `onClick={() => reverse(r)}`, gate: "mayFinalize",
    router: "payroll.py", method: "post", path: "/runs/{run_id}/reverse" },
  { what: "year-end review Approve", file: [...YE, "review", "_page.tsx"], anchor: `doAction("approve")}`, gate: `<Can resource="year_end" action="approve"`,
    router: "year_end_reviews.py", method: "post", path: "/engagements/{engagement_id}/reviews/approve" },
  { what: "year-end review Request Revision", file: [...YE, "review", "_page.tsx"], anchor: `doAction("requestRevision")}`, gate: `<Can resource="year_end" action="approve"`,
    router: "year_end_reviews.py", method: "post", path: "/engagements/{engagement_id}/reviews/request-revision" },
  { what: "year-end Final Approve & Lock", file: [...YE, "review", "_page.tsx"], anchor: `doAction("finalApprove")}`, gate: `<Can resource="year_end" action="final_approve"`,
    router: "year_end_reviews.py", method: "post", path: "/engagements/{engagement_id}/reviews/final-approve" },
  { what: "year-end Reopen Year", file: [...YE, "review", "_page.tsx"], anchor: `doAction("reopen")}`, gate: `<Can resource="year_end" action="final_approve"`,
    router: "year_end_reviews.py", method: "post", path: "/engagements/{engagement_id}/reviews/reopen" },
  { what: "year-end Lock Note", file: [...YE, "notes", "_page.tsx"], anchor: `onClick={() => handleLock(note)}`, gate: "mayLock",
    router: "year_end_notes.py", method: "post", path: "/{engagement_id}/notes/{note_id}/lock" },
  { what: "journal Approve & Post", file: [...C, "accounting", "page.tsx"], anchor: `onClick={() => approve(j.id)}`, gate: "mayPost",
    router: "accounting.py", method: "post", path: "/journals/{journal_id}/post" },
  { what: "invoice Void", file: [...C, "sales", "page.tsx"], anchor: "/api/sales-invoices/${inv.id}/cancel`", gate: "!mayVoid",
    gateExpr: "mayVoid", router: "sales_invoices.py", method: "post", path: "/{invoice_id}/cancel" },
  { what: "receipt Reverse", file: [...C, "sales", "page.tsx"], anchor: `onClick={() => reverseReceipt(r)}`, gate: "mayReverse",
    router: "receipts.py", method: "post", path: "/{receipt_id}/reverse" },
  { what: "payment Reverse", file: [...C, "purchases", "page.tsx"], anchor: `onClick={() => reversePayment(p)}`, gate: "mayReverse",
    router: "purchase_payments.py", method: "post", path: "/{payment_id}/reverse" },
  { what: "bill Cancel (row menu)", file: [...C, "purchases", "page.tsx"], anchor: `return cancelBill(b); }}`, gate: "mayCancelBill",
    router: "purchase_bills.py", method: "post", path: "/{bill_id}/cancel" },
  { what: "bank reconciliation Reopen", file: ["components", "banking", "ReconcileTab.tsx"], anchor: `onClick={() => setReopening(true)}`, gate: "mayReopen",
    router: "banking.py", method: "post", path: "/reconciliations/{recon_id}/reopen" },
];

for (const row of ROWS) {
  test(`${row.what} is offered only to someone its route admits`, () => {
    const src = read(WEB, ...row.file);
    const asked = routePair(read(API, "routers", row.router), row.method, row.path);
    assert.equal(gatePair(src, row.gateExpr ?? row.gate), asked, `${row.what}: the screen asks a different pair from the route`);
    assert.ok(gatedBy(src, row.anchor, row.gate), `${row.what} is drawn without its gate`);
  });
}

test("a year-end adjustment's Approve and Post to Journal are offered only to someone their routes admit", () => {
  const src = read(WEB, ...YE, "adjustments", "_page.tsx");
  const api = read(API, "routers", "year_end_adjustments.py");
  for (const path of ["/{engagement_id}/adjustments/{adjustment_id}/approve", "/{engagement_id}/adjustments/{adjustment_id}/post"]) {
    assert.equal(gatePair(src, "mayApprove"), routePair(api, "post", path));
  }
  // The gate is an early return in AdjActions, ahead of both buttons, for both statuses they are drawn in.
  const fn = src.slice(src.indexOf("function AdjActions("), src.indexOf("// ── New Adjustment Form"));
  const gate = fn.indexOf(`if ((adj.status === "pending_review" || adj.status === "approved") && !mayApprove) {`);
  assert.ok(gate >= 0, "AdjActions no longer returns early for someone who may not approve");
  assert.ok(gate < fn.indexOf(`onAction("approve")`) && gate < fn.indexOf(`onAction("post")`));
});

test("the journal list offers Delete and Reverse posted only to someone their routes admit", () => {
  const src = read(WEB, ...C, "accounting", "page.tsx");
  const api = read(API, "routers", "accounting.py");
  assert.equal(gatePair(src, "mayDeleteEntries"), routePair(api, "delete", "/journal/{entry_id}"));
  assert.equal(gatePair(src, "mayReverseEntries"), routePair(api, "post", "/journal/{entry_id}/reverse"));
  assert.match(src, /\.filter\(\(a\) => \(a\.id !== "discard" \|\| mayDeleteEntries\) && \(a\.id !== "reverse-posted" \|\| mayReverseEntries\)\)/);
});

test("the journal editor offers Post Entry on a saved draft only to someone the approval route admits", () => {
  const page = read(WEB, ...C, "accounting", "journal", "[entryId]", "edit", "_page.tsx");
  assert.equal(gatePair(page, "mayPostDraft"), routePair(read(API, "routers", "accounting.py"), "post", "/journals/{journal_id}/post"));
  assert.match(page, /mayPostDraft=\{mayPostDraft\}/);
  const editor = read(WEB, "components", "journal", "JournalEditor.tsx");
  assert.ok(gatedBy(editor, `onClick={() => handleSave("post")}`, "isNew || mayPostDraft"), "Post Entry is drawn on a saved draft without the gate");
});

test("the bill drawer draws Cancel Bill only when the page hands it the action", () => {
  const drawer = read(WEB, "components", "purchases", "PurchaseBillViewDrawer.tsx");
  assert.match(drawer, /onCancelBill\?: \(bill: PurchaseBillDetail\) => void;/);
  assert.ok(gatedBy(drawer, `onClick={() => onCancelBill(bill)}`, "&& onCancelBill &&"));
  assert.match(read(WEB, ...C, "purchases", "page.tsx"), /onCancelBill=\{mayCancelBill \? cancelBill : undefined\}/);
});

test("the helpers fail on a button with no gate and on a gate asking the wrong pair", () => {
  const route = `@router.post("/x/{id}/cancel")\ndef f(current_user: dict = Depends(rbac("accounting", "approve"))):\n  pass\n@router.get("/y")`;
  assert.equal(routePair(route, "post", "/x/{id}/cancel"), "accounting:approve");
  const screen = `const mayVoid = usePermissions().can("accounting", "write");\n{true && <button onClick={() => cancel(r)}>Void</button>}`;
  assert.notEqual(gatePair(screen, "mayVoid"), "accounting:approve");
  assert.equal(gatedBy(screen, `onClick={() => cancel(r)}`, "mayVoid"), false);
  const elsewhere = `{mayVoid && (\n  <button onClick={() => a(r)}>A</button>\n)}\n{true && (\n  <button onClick={() => cancel(r)}>Void</button>\n)}`;
  assert.equal(gatedBy(elsewhere, `onClick={() => cancel(r)}`, "mayVoid"), false, "a gate on a neighbour's condition counts");
  assert.equal(gatedBy(elsewhere, `onClick={() => a(r)}`, "mayVoid"), true);
  assert.equal(gatePair(`<Can resource="year_end" action="approve">`, `<Can resource="year_end" action="approve"`), "year_end:approve");
});
