// POST-A-455, part 2. The approve and record-the-filing steps of a GST, TDS, MCA or ITR return, an IRN or an e-way bill,
// the deletes of a customer, a vendor or a document, and the writes to the books an Executive (whose `accounting` is read
// only) was offered: each is drawn only for someone its route admits. The pair is read off the route in the API source, or
// off the step inside the handler where a route admits more people than the step does, so a route that changes its
// permission fails here until the screen follows.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gatedBy, gatePair, innerPair, routePair } from "./buttonGates.ts";

const WEB = join(import.meta.dirname, "..");
const API = join(WEB, "..", "api");
const read = (...p: string[]) => readFileSync(join(...p), "utf8");
const router = (name: string) => read(API, "routers", name);

type Row = { what: string; file: string[]; anchor: string; gate: string; nth?: number; server: () => string };
const C = ["app", "clients", "[id]"];
const GST = [...C, "compliance", "gst", "page.tsx"];
const TDS = [...C, "compliance", "tds", "page.tsx"];
const MCA = [...C, "compliance", "mca", "page.tsx"];
const FA = [...C, "fixed-assets", "page.tsx"];
const INV = [...C, "inventory", "page.tsx"];
const gstStatus1 = () => innerPair(router("gst_workspace.py"), "patch", "/gstr1/{return_id}/status");
const gstStatus3b = () => innerPair(router("gst_workspace.py"), "patch", "/gstr3b/{return_id}/status");
const tdsApprove = () => {
  // The TDS status route words its refusal in a helper ahead of it; the step that approves or files asks this pair.
  const m = router("tds_workspace.py").match(/if body\.status in \("ca_approved", "filed"\) and not can_user\(current_user, "([a-z_]+)", "([a-z_]+)"\)/);
  assert.ok(m, "the TDS status route no longer asks a pair before an approval or a filing");
  return `${m[1]}:${m[2]}`;
};

const ROWS: Row[] = [
  // GST, the client's own returns
  { what: "GSTR-1 Validate", file: GST, anchor: `onClick={() => updateStatus(r.id as string, "validated")}`, gate: "mayCompute",
    server: () => routePair(router("gst_workspace.py"), "patch", "/gstr1/{return_id}/status") },
  { what: "GSTR-1 CA Approve", file: GST, anchor: `onClick={() => updateStatus(r.id as string, "ca_approved")}`, gate: "mayApprove", server: gstStatus1 },
  { what: "GSTR-1 Mark as filed", file: GST, anchor: "setFilingRow({ id: r.id as string, period: r.period as string }); }}", gate: "mayApprove", server: gstStatus1 },
  { what: "GSTR-3B Validate", file: GST, anchor: `onClick={() => updateStatus(r.id as string, "validated")}`, gate: "mayCompute", nth: 1,
    server: () => routePair(router("gst_workspace.py"), "patch", "/gstr3b/{return_id}/status") },
  { what: "GSTR-3B CA Approve", file: GST, anchor: `onClick={() => updateStatus(r.id as string, "ca_approved")}`, gate: "mayApprove", nth: 1, server: gstStatus3b },
  { what: "GSTR-3B Mark as filed", file: GST, anchor: "setFilingRow({ id: r.id as string, period: r.period as string }); }}", gate: "mayApprove", nth: 1, server: gstStatus3b },
  { what: "GSTR-1 Compute from Books", file: GST, anchor: "onClick={() => setShowCompute(true)}", gate: "mayCompute",
    server: () => routePair(router("gst_workspace.py"), "post", "/gstr1") },
  { what: "GSTR-3B Recheck", file: GST, anchor: "onClick={() => recheck(r.id as string)}", gate: "mayCompute",
    server: () => routePair(router("gst_workspace.py"), "post", "/gstr3b/{return_id}/recompute") },
  { what: "GSTR-3B Compute from Books", file: GST, anchor: "onClick={() => setShowCompute(true)}", gate: "mayCompute", nth: 2,
    server: () => routePair(router("gst_workspace.py"), "post", "/gstr3b") },
  { what: "GSTR-2B file box (client tab)", file: GST, anchor: `data-testid="gstr2b-dropzone"`, gate: "mayCompute",
    server: () => routePair(router("gst_workspace.py"), "post", "/gstr2b/inspect") },
  { what: "GSTR-2B Upload & Reconcile (client tab)", file: GST, anchor: `{loading ? "Reconciling…" : "Upload & Reconcile"}`, gate: "mayCompute",
    server: () => routePair(router("gst_workspace.py"), "post", "/gstr2b/upload") },
  { what: "GSTR-2B files for many clients", file: ["components", "gst", "BulkGstr2bPanel.tsx"], anchor: `data-testid="bulk-gstr2b-dropzone"`, gate: "mayCompute",
    server: () => routePair(router("gst_workspace.py"), "post", "/gstr2b/bulk") },
  // GST, the firm's return screens
  { what: "firm GSTR-1 Build", file: ["app", "gst", "gstr1", "page.tsx"], anchor: `{loading ? "Building…" : "Build GSTR-1"}`, gate: "mayCompute",
    server: () => routePair(router("gst.py"), "post", "/gstr1/from-books") },
  { what: "firm GSTR-1 CA Approve", file: ["app", "gst", "gstr1", "page.tsx"], anchor: "onClick={handleApprove}", gate: "mayApprove", server: gstStatus1 },
  { what: "firm GSTR-1 Mark as Filed", file: ["app", "gst", "gstr1", "page.tsx"], anchor: "onClick={() => setShowFiledModal(true)}", gate: "mayApprove", server: gstStatus1 },
  { what: "firm GSTR-3B CA Approve", file: ["app", "gst", "gstr3b", "page.tsx"], anchor: "onClick={handleApprove}", gate: "mayApprove", server: gstStatus3b },
  { what: "firm GSTR-3B Mark as Filed", file: ["app", "gst", "gstr3b", "page.tsx"], anchor: "onClick={() => setShowFiledModal(true)}", gate: "mayApprove", server: gstStatus3b },
  { what: "firm GSTR-3B Compute", file: ["app", "gst", "gstr3b", "page.tsx"], anchor: "onClick={handleCompute}", gate: "mayCompute",
    server: () => routePair(router("gst_workspace.py"), "post", "/gstr3b") },
  // TDS
  { what: "firm TDS Compute", file: ["app", "tds", "returns", "page.tsx"], anchor: "{loading ? \"Computing…\" : `Compute ${returnType}`}", gate: "mayCompute",
    server: () => routePair(router("tds.py"), "post", "/26q/from-books") },
  { what: "TDS Compute from Books", file: TDS, anchor: "            Compute from Books", gate: "mayCompute",
    server: () => routePair(router("tds_workspace.py"), "post", "/returns") },
  { what: "TDS + New Return", file: TDS, anchor: "+ New Return", gate: "mayCompute", server: () => routePair(router("tds_workspace.py"), "post", "/returns") },
  { what: "TDS + New Challan", file: TDS, anchor: "+ New Challan", gate: "mayCompute", server: () => routePair(router("tds_workspace.py"), "post", "/challans") },
  { what: "TDS + Record certificate", file: TDS, anchor: "+ Record certificate", gate: "mayCompute", server: () => routePair(router("tds_workspace.py"), "post", "/certificates") },
  { what: "TDS 26AS Reconcile", file: TDS, anchor: `{loading ? "Reconciling…" : "Reconcile"}`, gate: "mayCompute",
    server: () => routePair(router("tds_workspace.py"), "post", "/form26as/upload") },
  { what: "TDS + Record Certificate (§197)", file: TDS, anchor: "+ Record Certificate", gate: "mayCompute",
    server: () => routePair(router("tds_workspace.py"), "post", "/lower-deduction-certificates") },
  { what: "TDS statement Prepare", file: TDS, anchor: `onClick={() => updateStatus(r.id as string, "prepared")}`, gate: "mayCompute",
    server: () => routePair(router("tds_workspace.py"), "patch", "/returns/{return_id}/status") },
  { what: "TDS statement CA Approve", file: TDS, anchor: `onClick={() => updateStatus(r.id as string, "ca_approved")}`, gate: "mayApprove", server: tdsApprove },
  { what: "firm TDS CA Approve", file: ["app", "tds", "returns", "page.tsx"], anchor: "onClick={handleApprove}", gate: "mayApprove", server: tdsApprove },
  { what: "firm TDS Mark as Filed", file: ["app", "tds", "returns", "page.tsx"], anchor: "onClick={openFiledModal}", gate: "mayApprove", server: tdsApprove },
  // MCA
  { what: "MCA filing Start", file: MCA, anchor: `onClick={() => updateStatus(r.id as string, "in_progress")}`, gate: "mayWrite",
    server: () => routePair(router("mca_workspace.py"), "patch", "/filings/{filing_id}/status") },
  { what: "MCA filing Mark Filed", file: MCA, anchor: "onClick={() => openConfirmFiling(r)}", gate: "mayApprove",
    server: () => innerPair(router("mca_workspace.py"), "patch", "/filings/{filing_id}/status") },
  { what: "firm MCA Mark Filed", file: ["app", "mca", "page.tsx"], anchor: "onClick={() => openMarkFiledModal(f)}", gate: "mayApprove",
    server: () => innerPair(router("mca_workspace.py"), "patch", "/filings/{filing_id}/status") },
  { what: "MCA + Add Company", file: MCA, anchor: "+ Add Company", gate: "mayWrite", server: () => routePair(router("mca_workspace.py"), "post", "/companies") },
  { what: "MCA + Add Director", file: MCA, anchor: "+ Add Director", gate: "mayWrite", server: () => routePair(router("mca_workspace.py"), "post", "/directors") },
  { what: "MCA Mark KYC Active", file: MCA, anchor: "Mark KYC Active", gate: "mayWrite", server: () => routePair(router("mca_workspace.py"), "patch", "/directors/{director_id}") },
  { what: "MCA + New Filing", file: MCA, anchor: "+ New Filing", gate: "mayWrite", server: () => routePair(router("mca_workspace.py"), "post", "/filings") },
  // ITR
  { what: "ITR New Filing", file: [...C, "tax", "filing", "page.tsx"], anchor: "<Plus size={12} /> New Filing", gate: "mayCompute",
    server: () => routePair(router("itr_workspace.py"), "post", "/filings") },
  { what: "ITR Move to the next status", file: [...C, "tax", "filing", "page.tsx"], anchor: "onClick={() => handleTransition(", gate: "mayApprove",
    server: () => routePair(router("itr_workspace.py"), "post", "/filings/{filing_id}/transition") },
  { what: "ITR Record Acknowledgement", file: [...C, "tax", "filing", "page.tsx"], anchor: "onClick={openAckPanel}", gate: "mayApprove",
    server: () => routePair(router("itr_workspace.py"), "post", "/filings/{filing_id}/acknowledge") },
  { what: "ITR computation Mark reviewed", file: [...C, "tax", "computation", "page.tsx"], anchor: "onClick={() => markSnapshotReviewed(s.id)}",
    gate: `can("income_tax", "approve")`, server: () => routePair(router("itr_workspace.py"), "post", "/snapshots/{snapshot_id}/review") },
  // IRN and e-way bill
  { what: "Record IRN", file: ["components", "invoices", "CompliancePanel.tsx"], anchor: `onClick={() => setModal("recordIrn")}`, gate: "mayRecord",
    server: () => routePair(router("einvoice.py"), "post", "/records/{record_id}/irn-generated") },
  { what: "Cancel IRN", file: ["components", "invoices", "CompliancePanel.tsx"], anchor: `onClick={() => setModal("cancelIrn")}`, gate: "mayRecord",
    server: () => routePair(router("einvoice.py"), "post", "/records/{record_id}/cancel") },
  { what: "Record E-Way Bill", file: ["components", "invoices", "CompliancePanel.tsx"], anchor: `onClick={() => setModal("recordEway")}`, gate: "mayRecord",
    server: () => routePair(router("eway_bill.py"), "post", "/records/{record_id}/generated") },
  { what: "Cancel E-Way Bill", file: ["components", "invoices", "CompliancePanel.tsx"], anchor: `onClick={() => setModal("cancelEway")}`, gate: "mayRecord",
    server: () => routePair(router("eway_bill.py"), "post", "/records/{record_id}/cancel") },
  // Customers, vendors and documents
  { what: "customer Edit", file: [...C, "sales", "page.tsx"], anchor: "setEditCustomer(c); setShowForm(true); }}", gate: "mayEditParty",
    server: () => routePair(router("customers.py"), "patch", "/{customer_id}") },
  { what: "customer Add", file: [...C, "sales", "page.tsx"], anchor: "onClick={() => { setEditCustomer(null); setShowForm(true); }}", gate: "mayEditParty",
    server: () => routePair(router("customers.py"), "post", "/") },
  // The single-row Deactivate writes the table directly, under the row policy that asks `client` `write` (the same pair as the
  // PATCH route and as Reactivate); the bulk Deactivate and Delete call DELETE /api/customers/{id} and ask `client` `delete`.
  { what: "customer Deactivate", file: [...C, "sales", "page.tsx"], anchor: "setMenu(null); setDeactivateTarget(c); }}", gate: "mayEditParty",
    server: () => routePair(router("customers.py"), "patch", "/{customer_id}") },
  { what: "customer Reactivate", file: [...C, "sales", "page.tsx"], anchor: "onClick={() => { setMenu(null); return reactivateCustomer(c); }}", gate: "mayEditParty",
    server: () => routePair(router("customers.py"), "patch", "/{customer_id}") },
  { what: "customer Delete", file: [...C, "sales", "page.tsx"], anchor: "setMenu(null); startDelete(c); }}", gate: "mayRemoveParty",
    server: () => routePair(router("customers.py"), "delete", "/{customer_id}") },
  { what: "vendor Edit", file: [...C, "purchases", "page.tsx"], anchor: "setMenu(null); openEdit(v); }}", gate: "mayEditParty",
    server: () => routePair(router("vendors.py"), "patch", "/{vendor_id}") },
  { what: "vendor Deactivate", file: [...C, "purchases", "page.tsx"], anchor: "setMenu(null); setDeactivateTarget(v); }}", gate: "mayRemoveParty",
    server: () => routePair(router("vendors.py"), "delete", "/{vendor_id}") },
  { what: "vendor Delete", file: [...C, "purchases", "page.tsx"], anchor: "setMenu(null); startDelete(v); }}", gate: "mayRemoveParty",
    server: () => routePair(router("vendors.py"), "delete", "/{vendor_id}") },
  { what: "document Delete", file: [...C, "documents", "page.tsx"], anchor: "onClick={() => handleDeleteDocument(doc)}", gate: "mayDeleteDocument",
    server: () => routePair(router("client_documents.py"), "delete", "/{doc_id}") },
  // Books writes an Executive was offered
  { what: "New Journal Entry", file: [...C, "accounting", "page.tsx"], anchor: `onClick={() => router.push(journalEditorHref(clientId, "new"))}`, gate: "mayWriteBooks",
    server: () => routePair(router("accounting.py"), "post", "/journal") },
  { what: "voucher import", file: [...C, "accounting", "page.tsx"], anchor: "<VoucherImportButton clientId={clientId} onImported={loadEntries}", gate: "mayWriteBooks",
    server: () => routePair(router("accounting.py"), "post", "/vouchers/import") },
  { what: "Record Payment", file: [...C, "purchases", "page.tsx"], anchor: "onClick={() => (showForm ? closePaymentForm() : openPaymentForm())}", gate: "mayWriteBooks",
    server: () => routePair(router("purchase_payments.py"), "post", "") },
  { what: "payment Apply", file: [...C, "purchases", "page.tsx"], anchor: "onClick={() => setAllocateFor(p)}", gate: "mayWriteBooks",
    server: () => routePair(router("purchase_payments.py"), "patch", "/{payment_id}/allocate") },
  { what: "Add Asset", file: FA, anchor: "onClick={() => setShowAdd(true)}", gate: "mayWriteBooks", server: () => routePair(router("fixed_assets.py"), "post", "") },
  { what: "asset Correct", file: FA, anchor: "onClick={() => setCorrecting(a)}", gate: "mayWriteBooks", server: () => routePair(router("fixed_assets.py"), "patch", "/{asset_id}") },
  { what: "asset Delete", file: FA, anchor: "onClick={() => setDeleting(a)}", gate: "mayWriteBooks", server: () => routePair(router("fixed_assets.py"), "delete", "/{asset_id}") },
  { what: "Run depreciation", file: FA, anchor: "onClick={runDepreciation}", gate: "mayWriteBooks", server: () => routePair(router("fixed_assets.py"), "post", "/run-depreciation") },
  { what: "Post a month's depreciation", file: FA, anchor: "onClick={() => postDepreciation(r.asset_id)}", gate: "mayWriteBooks",
    server: () => routePair(router("fixed_assets.py"), "post", "/{asset_id}/depreciate") },
  { what: "Reverse a month's depreciation", file: FA, anchor: "onClick={() => reverseLastMonth(r.asset_id, r.depreciation_posted_through!)}", gate: "mayWriteBooks",
    server: () => routePair(router("fixed_assets.py"), "post", "/{asset_id}/depreciation/{period}/reverse") },
  { what: "Finish reversing a month", file: FA, anchor: "onClick={() => reverseLastMonth(r.asset_id, r.unfinished_reversal!.month)}", gate: "mayWriteBooks",
    server: () => routePair(router("fixed_assets.py"), "post", "/{asset_id}/depreciation/{period}/reverse") },
  { what: "stock Adjust", file: INV, anchor: `setRowAction({ item: i, kind: "adjust" }); }}`, gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "post", "/items/{service_catalogue_id}/adjust") },
  { what: "stock Write down", file: INV, anchor: `setRowAction({ item: i, kind: "writedown" }); }}`, gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "post", "/items/{service_catalogue_id}/writedown") },
  { what: "Physical count", file: INV, anchor: "onClick={startCount}", gate: "mayWriteBooks", server: () => routePair(router("inventory.py"), "post", "/count-sessions") },
  { what: "Adjust Stock (ledger)", file: INV, anchor: "onClick={() => setAdjustOpen(true)}", gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "post", "/items/{service_catalogue_id}/adjust") },
  { what: "Add godown", file: ["components", "inventory", "LocationsAndBatches.tsx"], anchor: "onClick={() => setAdding(true)}", gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "post", "/godowns") },
  { what: "Close a godown", file: ["components", "inventory", "LocationsAndBatches.tsx"], anchor: "onClick={() => closeGodown(g)}", gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "delete", "/godowns/{godown_id}") },
  { what: "Add lot", file: ["components", "inventory", "LocationsAndBatches.tsx"], anchor: "onClick={() => setAddingBatch(true)}", gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "post", "/batches") },
  { what: "New CWIP project", file: ["components", "fixed-assets", "CwipTab.tsx"], anchor: "<Plus size={12} /> New project", gate: "mayWriteBooks",
    server: () => routePair(router("cwip.py"), "post", "") },
  { what: "CWIP Add cost", file: ["components", "fixed-assets", "CwipTab.tsx"], anchor: "onClick={() => setCostFor(p)}", gate: "mayWriteBooks",
    server: () => routePair(router("cwip.py"), "post", "/{cwip_id}/costs") },
  { what: "CWIP Capitalise", file: ["components", "fixed-assets", "CwipTab.tsx"], anchor: "onClick={() => setCapitalising(p)}", gate: "mayWriteBooks",
    server: () => routePair(router("cwip.py"), "post", "/{cwip_id}/capitalise") },
  { what: "Record an asset movement", file: ["components", "fixed-assets", "AssetMovements.tsx"], anchor: "onClick={openForm}", gate: "mayWriteBooks",
    server: () => routePair(router("fixed_asset_movements.py"), "post", "/{asset_id}/movements") },
  { what: "asset Dispose", file: FA, anchor: "<Trash2 size={11} /> Dispose", gate: "mayWriteBooks",
    server: () => routePair(router("fixed_assets.py"), "patch", "/{asset_id}/dispose") },
  { what: "Complete the stock", file: ["components", "inventory", "UnrecordedStockPanel.tsx"], anchor: "onClick={() => complete(d)}", gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "post", "/stock-effects/retry") },
  { what: "Reopen a godown", file: ["components", "inventory", "LocationsAndBatches.tsx"], anchor: "onClick={() => reopenGodown(g)}", gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "post", "/godowns/{godown_id}/reopen") },
  { what: "bank reconciliation Adjustment", file: ["components", "banking", "ReconcileTab.tsx"], anchor: `<input aria-label="Adjustment (₹)"`, gate: "mayAdjust",
    server: () => routePair(router("banking.py"), "put", "/reconciliations/{recon_id}/adjustment") },
  { what: "Record the cost formula", file: ["components", "inventory", "CostFormulaPanel.tsx"], anchor: "onClick={begin}", gate: "mayWriteBooks",
    server: () => routePair(router("inventory.py"), "put", "/costing-policy") },
];

for (const row of ROWS) {
  test(`${row.what} is offered only to someone its route admits`, () => {
    const src = read(WEB, ...row.file);
    assert.equal(gatePair(src, row.gate), row.server(), `${row.what}: the screen asks a different pair from the route`);
    assert.ok(gatedBy(src, row.anchor, row.gate, row.nth ?? 0), `${row.what} is drawn without its gate`);
  });
}

test("the two GST tabs, the TDS tab and the MCA tab each ask the pair their gates name", () => {
  const gst = read(WEB, ...GST);
  assert.equal((gst.match(/const mayApprove = canDo\("gst", "approve"\);/g) ?? []).length, 2, "both GST tabs ask who may approve");
  assert.equal((gst.match(/const mayCompute = canDo\("gst", "compute"\);/g) ?? []).length, 3, "the two GST tabs and the GSTR-2B tab ask who may compute");
  assert.match(read(WEB, ...TDS), /const mayApprove = canDo\("tds", "approve"\);/);
  assert.match(read(WEB, ...MCA), /const mayApprove = canDo\("mca", "approve"\);/);
});

test("the vendor list's Deactivate and Delete permanently are offered only to someone who may delete a vendor", () => {
  const src = read(WEB, ...C, "purchases", "page.tsx");
  assert.match(src, /\.filter\(\(a\) => mayRemoveParty \|\| \(a\.id !== "deactivate" && a\.id !== "delete-permanent"\)\)/);
  const sales = read(WEB, ...C, "sales", "page.tsx");
  assert.match(sales, /\.\.\.\(mayRemoveParty \? \[/, "the customer list's bulk Deactivate and Delete permanently are not gated");
});

test("an ITR's loss records and an asset's disposal are drawn only for someone who may write them", () => {
  const filing = read(WEB, ...C, "tax", "filing", "page.tsx");
  // The notice is shown to everyone who can open the return; only its controls are for someone who may write the records.
  assert.match(filing, /selectedFiling\.status === "filed" && \(selectedFiling\.return_type \?\? "original"\) !== "updated" && \(/);
  assert.equal(gatePair(filing, "mayApprove"), routePair(router("itr_workspace.py"), "post", "/filings/{filing_id}/loss-records"));
  for (const anchor of ["onClick={() => updateLossRecords(selectedFiling, null)}", "onClick={() => updateLossRecords(selectedFiling, pinChoice)}", `id="itr-pin-computation" value=`]) {
    assert.ok(gatedBy(filing, anchor, "mayApprove"), `${anchor} is drawn without its gate`);
  }
  const fa = read(WEB, ...FA);
  assert.match(fa, /\{selected && mayWriteBooks && \(\n\s*<div className="bg-white rounded-xl border border-state-problem-border/);
  assert.equal(gatePair(fa, "mayWriteBooks"), routePair(router("fixed_assets.py"), "patch", "/{asset_id}/dispose"));
});

test("the gate helper reads a same-line gate and refuses one on a neighbour's line", () => {
  assert.equal(gatedBy(`mayX && <Thing label="A" />`, `label="A"`, "mayX"), true);
  assert.equal(gatedBy(`{mayX && <span>\n  <button onClick={a}>A</button>\n</span>}\n<button onClick={b}>B</button>`, "onClick={b}", "mayX"), false);
  assert.equal(gatePair(`{can("income_tax", "approve") && (`, `can("income_tax", "approve")`), "income_tax:approve");
  const twice = `{mayA && (\n<b onClick={go} />\n)}\n{true && (\n<b onClick={go} />\n)}`;
  assert.equal(gatedBy(twice, "onClick={go}", "mayA", 0), true);
  assert.equal(gatedBy(twice, "onClick={go}", "mayA", 1), false, "the second drawing of one call is checked on its own");
});

test("Prepare IRN and Prepare E-Way Bill are drawn only for someone who may prepare, and the reasons are drawn for everyone", () => {
  const src = read(WEB, "components", "invoices", "CompliancePanel.tsx");
  assert.equal(gatePair(src, "mayPrepare"), routePair(router("einvoice.py"), "post", "/records"));
  assert.equal(gatePair(src, "mayPrepare"), routePair(router("eway_bill.py"), "post", "/records"));
  assert.ok(gatedBy(src, "<PrimaryBtn disabled={!elig.eligible} onClick={onAction}>", "canAct"), "the button is drawn without canAct");
  assert.match(src, /actionLabel="Prepare IRN"[^\n]*canAct=\{mayPrepare\}/);
  assert.match(src, /actionLabel="Prepare E-Way Bill"[^\n]*canAct=\{mayPrepare\}/);
  assert.doesNotMatch(src, /mayPrepare && <EligibilityBlock/, "the blockers and warnings are information and are not hidden with the button");
});

test("the purchase bills list's bulk Cancel received is in the list only for someone the cancel route admits", () => {
  const src = read(WEB, ...C, "purchases", "page.tsx");
  assert.equal(gatePair(src, "mayCancelBill"), routePair(router("purchase_bills.py"), "post", "/{bill_id}/cancel"));
  assert.match(src, /\.filter\(\(a\) => a\.id !== "cancel" \|\| mayCancelBill\), \[handleBulkReceive, handleBulkDelete, handleBulkCancel, billColumns, mayCancelBill\]/);
  assert.match(src, /apiCall\(`\/api\/purchase-bills\/\$\{b\.id\}\/cancel`/, "the bulk action calls the cancel route");
});

test("the GSTR-3B tab's Recheck asks compute for any unfiled status and its Delete asks approve for an approved return", () => {
  const src = read(WEB, ...GST);
  assert.ok(gatedBy(src, "onClick={() => recheck(r.id as string)}", "mayCompute"), "Recheck is drawn without mayCompute");
  assert.match(src, /UNFILED\.includes\(r\.status as string\) && \(r\.status === "ca_approved" \? mayApprove : mayCompute\) && \(\n\s*<Button[^\n]*onClick=\{\(\) => deleteReturn\(/);
  const api = router("gst_workspace.py");
  assert.equal(gatePair(src, "mayCompute"), routePair(api, "post", "/gstr3b/{return_id}/recompute"));
  assert.match(routeBlockText(api, "/gstr3b/{return_id}/recompute"), /dry_run: bool = Query\(True/, "Recheck sends dry_run=true, which asks compute only");
  assert.equal(gatePair(src, "mayApprove"), innerPair(api, "patch", "/gstr3b/{return_id}/status"));
  assert.match(api, /def _approval_needed_to_change[^]*?can_user\(current_user, "gst", "approve"\)/);
});
function routeBlockText(src: string, path: string): string {
  const at = src.indexOf(`@router.post("${path}"`);
  assert.ok(at >= 0);
  return src.slice(at, src.indexOf("@router.", at + 1));
}

test("the journal editor draws its saving and posting only for someone who may write the books", () => {
  const page = read(WEB, ...C, "accounting", "journal", "[entryId]", "edit", "_page.tsx");
  const accounting = router("accounting.py");
  assert.equal(gatePair(page, "mayWrite"), routePair(accounting, "post", "/journal"));
  assert.equal(gatePair(page, "mayWrite"), routePair(accounting, "patch", "/journal/{entry_id}"));
  assert.match(page, /mayWrite=\{mayWrite\}/);
  const editor = read(WEB, "components", "journal", "JournalEditor.tsx");
  // POST-A-456 adds a third reason: an entry on the books, to someone the firm's approval rule does not let change one.
  assert.match(editor, /const readOnly = locked \|\| !mayWrite \|\| postedHeldForApproval;/);
  const footer = editor.indexOf(`{!readOnly && (\n          <div className="flex gap-3 justify-end pt-1">`);
  assert.ok(footer >= 0, "the footer is no longer drawn under !readOnly");
  for (const mode of ["correct", "draft", "post"]) assert.ok(editor.indexOf(`handleSave("${mode}")`) > footer, `${mode} is above the gated footer`);
  assert.match(editor, /\{!mayWrite && !locked && \(/, "a read-only reader is told why");
});

test("a sentence that says who acts names a permission and not a role", () => {
  const files = [
    ["app", "mca", "page.tsx"], ["app", "gst", "gstr1", "page.tsx"], ["app", "gst", "gstr3b", "page.tsx"], ["app", "tds", "returns", "page.tsx"],
    [...C, "compliance", "gst", "page.tsx"], [...C, "compliance", "tds", "page.tsx"], MCA, [...C, "payroll", "page.tsx"],
    [...C, "tax", "computation", "page.tsx"], [...C, "tax", "filing", "page.tsx"], [...C, "accounting", "page.tsx"],
    [...C, "year-end", "[engagementId]", "review", "_page.tsx"], [...C, "year-end", "[engagementId]", "adjustments", "_page.tsx"],
    ["components", "invoices", "CompliancePanel.tsx"], ["components", "journal", "JournalEditor.tsx"], ["components", "banking", "ReconcileTab.tsx"],
  ];
  const ROLE_SENTENCE = /(?:\bA|\ban|\bAn) (?:Manager|Partner|Executive)(?: or (?:a )?(?:Manager|Partner))? (?:approves|records|reviews|posts|moves|gives|finalises)|Awaiting a (?:Manager|Partner)|(?:are|is) for a Partner/;
  for (const f of files) assert.doesNotMatch(read(WEB, ...f), ROLE_SENTENCE, `${f.join("/")} says who acts by role`);
});

test("a permission-gating helper refuses a wrong second declaration, a prefix, a negation, an OR and a ternary branch", () => {
  const twice = `const mayX = canDo("gst", "compute");\nconst mayX = canDo("gst", "approve");`;
  assert.equal(gatePair(twice, "mayX"), null, "a wrong pair in a second declaration is seen");
  assert.equal(gatePair(`const mayX = canDo("gst", "compute");\nconst mayX = usePermissions().can("gst", "compute");`, "mayX"), "gst:compute");
  const at = (opener: string) => `${opener}\n  <button onClick={go} />\n)}`;
  assert.equal(gatedBy(at("{mayWriteBooks && ("), "onClick={go}", "mayWrite"), false, "a longer name is not the gate");
  assert.equal(gatedBy(at("{!mayX && ("), "onClick={go}", "mayX"), false, "a negated gate is not the gate");
  assert.equal(gatedBy(at("{mayX || other && ("), "onClick={go}", "mayX"), false, "one side of an OR is not the gate");
  assert.equal(gatedBy(at(`{r.s === "a" ? mayX : mayY && (`), "onClick={go}", "mayX"), false);
  assert.equal(gatedBy(at(`{r.s === "a" ? mayX : mayY && (`), "onClick={go}", "mayY"), false, "a ternary's branch is not the gate");
  assert.equal(gatedBy(at("{mayX && ("), "onClick={go}", "mayX"), true);
  assert.equal(gatedBy(`{mayX ? (\n  <b onClick={a} />\n) : (\n  <b onClick={go} />\n)}`, "onClick={go}", "mayX"), false, "the else branch is not gated by the condition");
  assert.equal(gatedBy(`{mayX ? (\n  <b onClick={a} />\n) : (\n  <b onClick={go} />\n)}`, "onClick={a}", "mayX"), true);
  assert.equal(gatedBy(`{c ? (\n  <b onClick={a} />\n) : mayX ? (\n  <b onClick={go} />\n) : null}`, "onClick={go}", "mayX"), true);
});
