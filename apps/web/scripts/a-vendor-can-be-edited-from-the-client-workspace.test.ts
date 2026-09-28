// apex-sales-purchases-05: the Vendors tab's row menu only offered
// Deactivate/Reactivate/Delete, and the "New Vendor" form was create-only —
// there was no way back into a vendor's own record, so none of a client's
// vendors could have their §195 residency status or TDS section corrected
// from inside the client workspace at all.
//
// THE FIX
//     The row menu gained an Edit action; the existing "New Vendor" form is
//     reused (not duplicated) via an `editingVendor` state, prefilling from
//     the row and saving through PATCH /api/vendors/{id} instead of POST.
//     `msme_status` / `msmed_agreement_days` are deliberately NOT added to
//     this form — they are recorded through a different screen and a
//     different write path (POST /api/accounting/schedule-iii/ageing/classify)
//     with its own RBAC, and duplicating that here is the exact
//     second-write-path shape CLAUDE.md's PUR-16 already warns against.
//     `tds_rate_bps` is likewise deliberately absent (PUR-06 — the field is
//     dead; the rate comes off the section through the FY registry).
//
// Run with:
//   node --experimental-strip-types --test scripts/a-vendor-can-be-edited-from-the-client-workspace.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const SRC = stripComments(fs.readFileSync(path.join(WEB, "app/clients/[id]/purchases/page.tsx"), "utf8"));

// The page defines several tabs' worth of near-identical row-menu blocks
// (Bills, Vendors, Payments, Debit/Credit Notes) — scope to the Vendors
// component specifically, or a test asserting something about ITS menu can
// silently pass by matching a sibling tab's instead.
const VENDORS_FN = /function Vendors\(\{ clientId \}: \{ clientId: string \}\) \{([\s\S]*?)\n\}\n\nfunction /.exec(SRC);
assert.ok(VENDORS_FN, "the Vendors component was not found");
const VENDORS_SRC = VENDORS_FN[1];

test("an editingVendor state exists, distinct from the create form's own fields", () => {
  assert.match(SRC, /const \[editingVendor, setEditingVendor\] = useState<VendorRow \| null>\(null\);/);
});

test("the row menu offers Edit, opening the vendor for editing", () => {
  const m = /\{menu && \(\(\) => \{([\s\S]*?)\n\s*\}\)\(\)\}/.exec(VENDORS_SRC);
  assert.ok(m, "the vendor row menu was not found");
  assert.match(m[1], /<button onClick=\{\(\) => \{ setMenu\(null\); openEdit\(v\); \}\}/);
  assert.match(m[1], /<Pencil size=\{13\} \/> Edit/);
});

test("openEdit prefills every field the task named, from the row", () => {
  const m = /function openEdit\(v: VendorRow\) \{([\s\S]*?)\n  \}/.exec(SRC);
  assert.ok(m, "openEdit not found");
  const body = m[1];
  assert.match(body, /setEditingVendor\(v\);/);
  for (const setter of [
    "setTdsApplicable(v.tds_applicable);",
    "setTdsSection(v.tds_section ?? \"194C\");",
    "setResidentialStatus(v.residential_status ?? \"\");",
    "setGstRegistrationStatus(v.gst_registration_status ?? \"\");",
  ]) {
    assert.ok(body.includes(setter), `openEdit is missing: ${setter}`);
  }
});

test("saving with a vendor being edited PATCHes /api/vendors/{id}, not POST /api/vendors/", () => {
  const m = /const result = editingVendor([\s\S]*?);\s*\n\s*if \(!result\.success\)/.exec(SRC);
  assert.ok(m, "the create/edit branch in handleSave was not found");
  const branch = m[1];
  assert.match(branch, /\? await apiCall\(`\/api\/vendors\/\$\{editingVendor\.id\}`, "PATCH", fields, token\)/);
  assert.match(branch, /: await apiCall\("\/api\/vendors\/", "POST", \{ client_id: clientId, \.\.\.fields \}, token\)/);
});

test("VendorRow carries the §195 fields the row-driven prefill needs (already fetched by select(\"*\"))", () => {
  const m = /interface VendorRow \{([\s\S]*?)\n\}/.exec(SRC);
  assert.ok(m, "VendorRow interface not found");
  const body = m[1];
  for (const field of [
    "gst_registration_status", "section_195_nature_of_income",
    "non_resident_payee_class", "treaty_rate_bps",
  ]) {
    assert.ok(body.includes(field), `VendorRow is missing ${field}`);
  }
});

test("the form's own submit button and heading reflect edit mode", () => {
  assert.match(SRC, /\{editingVendor \? `Edit \$\{editingVendor\.name\}` : "New Vendor"\}/);
  assert.match(SRC, /\{saving \? "Saving…" : editingVendor \? "Save Changes" : "Add Vendor"\}/);
});

test("tds_rate_bps is still not offered as an editable field (PUR-06 stands)", () => {
  assert.doesNotMatch(SRC, /TDS Rate/);
});

test("msme_status and msmed_agreement_days are deliberately absent from this form", () => {
  // They belong to the Schedule III ageing screen's own classify door, not
  // this one — see openEdit's own comment for why duplicating them here
  // would be a second write path.
  assert.doesNotMatch(SRC, /msme_status/);
  assert.doesNotMatch(SRC, /msmed_agreement_days/);
});
