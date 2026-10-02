// Regression tests for the journal entry History panel's field descriptions
// (finding sweep-client-accounting-06: the panel printed raw audit_log
// column names, e.g. "Changed: rate_selected_by, base_currency, id"). Run
// with:
//   node --experimental-strip-types --test components/accounting/entryHistoryFields.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { describeChanges, type AuditRowLike } from "./entryHistoryFields.ts";

function row(over: Partial<AuditRowLike> = {}): AuditRowLike {
  return { action: "update", old_data: {}, new_data: {}, ...over };
}

test("a create shows no field diff — the badge already says Created", () => {
  const changes = describeChanges(row({
    action: "create",
    old_data: {},
    new_data: { id: "x", entry_date: "2026-03-15", narration: "Rent" },
  }));
  assert.deepEqual(changes, []);
});

test("a delete shows no field diff — the badge already says Deleted", () => {
  const changes = describeChanges(row({
    action: "delete",
    old_data: { id: "x", entry_date: "2026-03-15", narration: "Rent" },
    new_data: {},
  }));
  assert.deepEqual(changes, []);
});

test("internal/bookkeeping columns never appear, even when they moved", () => {
  const changes = describeChanges(row({
    old_data: {
      id: "a", client_id: "c1", rate_selected_by: "u1", base_currency: "AED",
      line_count: 2, source_type: "manual", updated_at: "2026-03-01T00:00:00Z",
    },
    new_data: {
      id: "b", client_id: "c2", rate_selected_by: "u2", base_currency: "USD",
      line_count: 3, source_type: "invoice", updated_at: "2026-03-02T00:00:00Z",
    },
  }));
  assert.deepEqual(changes, []);
});

test("only the fields that actually moved are reported", () => {
  const changes = describeChanges(row({
    old_data: { narration: "Rent", reference_no: "REF1" },
    new_data: { narration: "Rent paid", reference_no: "REF1" },
  }));
  assert.equal(changes.length, 1);
  assert.equal(changes[0].key, "narration");
});

test("known columns get a CA-facing label and their values formatted", () => {
  const changes = describeChanges(row({
    old_data: { entry_date: "2026-03-31", narration: "Rent", debit_paise: 150000 },
    new_data: { entry_date: "2026-04-01", narration: "Rent — April", debit_paise: 200000 },
  }));
  const byKey = Object.fromEntries(changes.map((c) => [c.key, c]));

  assert.equal(byKey.entry_date.label, "Date");
  assert.equal(byKey.entry_date.before, "31 Mar 2026");
  assert.equal(byKey.entry_date.after, "01 Apr 2026");

  assert.equal(byKey.narration.label, "Narration");
  assert.equal(byKey.narration.before, "Rent");
  assert.equal(byKey.narration.after, "Rent — April");

  assert.equal(byKey.debit_paise.label, "Debit");
  assert.equal(byKey.debit_paise.before, "₹1,500.00");
  assert.equal(byKey.debit_paise.after, "₹2,000.00");
});

test("a boolean column reads Yes/No, not true/false", () => {
  const changes = describeChanges(row({
    old_data: { is_posted: false },
    new_data: { is_posted: true },
  }));
  assert.equal(changes[0].label, "Posted");
  assert.equal(changes[0].before, "No");
  assert.equal(changes[0].after, "Yes");
});

test("an unmapped column is humanized rather than dropped or shown raw", () => {
  // A future migration could add a column this map has never heard of; it
  // must still read as English, and the real change must not disappear.
  const changes = describeChanges(row({
    old_data: { some_new_column: "before" },
    new_data: { some_new_column: "after" },
  }));
  assert.equal(changes.length, 1);
  assert.equal(changes[0].label, "Some New Column");
  assert.equal(changes[0].before, "before");
  assert.equal(changes[0].after, "after");
});

test("a null value reads as an em dash, not the word null", () => {
  const changes = describeChanges(row({
    old_data: { reference_no: null },
    new_data: { reference_no: "REF-9" },
  }));
  assert.equal(changes[0].before, "—");
  assert.equal(changes[0].after, "REF-9");
});

test("posted_at renders a stored UTC instant in IST", () => {
  // 2026-03-31T18:35:00Z is 2026-04-01 00:05 IST (UTC+5:30).
  const changes = describeChanges(row({
    old_data: { posted_at: null },
    new_data: { posted_at: "2026-03-31T18:35:00Z" },
  }));
  assert.equal(changes[0].after, "01 Apr 2026, 12:05 am");
});

test("an unreadable date is shown as it was stored, not as a placeholder", () => {
  const changes = describeChanges(row({
    old_data: { entry_date: "2026-03-31" },
    new_data: { entry_date: "31/03/2026" },
  }));
  assert.equal(changes[0].after, "31/03/2026");
});
