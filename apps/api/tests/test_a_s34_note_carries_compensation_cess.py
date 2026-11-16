"""A s.34 credit or debit note carries GST compensation cess (POST-A-058, migration 615).

WHAT WAS WRONG
    Migration 374 gave the sales invoice and the purchase bill a compensation cess and deliberately did not give the four s.34 note tables
    one: the shared line model the notes use had no cess field, so a note against a cess-bearing invoice or bill adjusted the value and
    the three GST heads and left the cess. The receivable or payable, the cess ledgers and the returns kept the full charge of a supply
    the note had reduced (or added to). The GSTR-1 build named the sales-side case in `cess_gaps`; the purchase side was not named.

WHAT THIS HOLDS
    * the shared line model takes both limbs, refuses a negative one, and the invoice still has them through it;
    * for each of the four notes, driven end to end on the e2e harness: the lines store both limbs and the derived cess, the header's
      cess is their sum and is in the total, the draft issues (the issue check agrees with what the API wrote), and the journal posts the
      cess to its OWN ledger on the right side (Compensation Act s.11(2) proviso: never the GST ledgers) and balances;
    * an edit that takes the cess off a draft takes it off the header and the total;
    * the issue check refuses a note header whose cess is not its lines';
    * the GSTR-1 gap names a note with NO cess against a cess-bearing invoice and no longer names one that carries its own.

NEGATIVE CONTROL: against the code before this change the model drops the two limbs (pydantic ignores an unknown field), so every
end-to-end case finds no cess on the note and fails; the issue-check and gap cases fail on their own assertions.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
import routers.sales_invoices as si
import routers.vendors as ve
from domain.accounting import draft_integrity as rule
from domain.gst import compensation_cess
from models.invoices import (
    InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, SalesInvoiceIn, SalesInvoiceLineIn,
)
from tests.e2e_harness import FakeDB, seed_standard_coa, trial_balance, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}

# ₹1,000 at 18% with cess at 12% ad valorem plus ₹4 a unit on 3 units: the ad valorem limb floors on the taxable value, the specific
# limb is quantity x the per-unit figure, and the cess is their sum (Compensation Act s.8(2)).
QTY, RATE = 3, 100_000
TAXABLE = QTY * RATE                         # 3,00,000 paise
AD_VALOREM = TAXABLE * 1_200 // 10_000       # 36,000
SPECIFIC = QTY * 400                         # 1,200
CESS = AD_VALOREM + SPECIFIC                 # 37,200
GST = TAXABLE * 1_800 // 10_000              # 54,000


# ── the model ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_shared_line_model_takes_both_limbs_and_the_invoice_has_them_through_it():
    line = InvoiceLineIn(description="x", rate_paise=1, service_catalogue_id="S", cess_rate_bps=1_200,
                         cess_specific_paise_per_unit=400)
    assert (line.cess_rate_bps, line.cess_specific_paise_per_unit) == (1_200, 400)
    assert "cess_rate_bps" in SalesInvoiceLineIn.model_fields and "cess_specific_paise_per_unit" in SalesInvoiceLineIn.model_fields
    assert "cess_paise" not in InvoiceLineIn.model_fields, "the AMOUNT is derived, never typed"


@pytest.mark.parametrize("field", ["cess_rate_bps", "cess_specific_paise_per_unit"])
def test_a_negative_limb_is_refused_on_a_note_line(field):
    with pytest.raises(ValueError, match="cannot be negative"):
        InvoiceLineIn(description="x", rate_paise=1, service_catalogue_id="S", **{field: -1})


def test_the_line_columns_are_the_one_derivation_and_a_document_is_their_sum():
    cols = compensation_cess.line_columns({"cess_rate_bps": 1_200, "cess_specific_paise_per_unit": 400},
                                          taxable_paise=TAXABLE, quantity=QTY)
    assert cols == {"cess_rate_bps": 1_200, "cess_specific_paise_per_unit": 400, "cess_paise": CESS}
    assert compensation_cess.line_columns({}, taxable_paise=TAXABLE, quantity=QTY) == {
        "cess_rate_bps": 0, "cess_specific_paise_per_unit": 0, "cess_paise": 0}
    assert compensation_cess.lines_cess([{"cess_paise": 5}, {"cess_paise": 7}, {}]) == 12
    assert compensation_cess.lines_cess(None) == 0


# ── the four notes, end to end ───────────────────────────────────────────────────────────────────────────────────────────

def _setup(monkeypatch) -> FakeDB:
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn, dn, pb, pcn, sdn, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "is_active": True,
                          "opening_balance_paise": 0})
    db.seed("vendors", {"id": "VEND-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    # The two ledgers migration 374 seeds for every firm (and coa_seed_service for a new one), by their own names and keys.
    db.seed("chart_of_accounts", {"id": "ACC-CESS-OUT", "firm_id": FIRM, "client_id": "CLI", "system_account_key": "gst_cess_output",
                                  "account_name": "Compensation Cess Payable", "is_active": True})
    db.seed("chart_of_accounts", {"id": "ACC-CESS-IN", "firm_id": FIRM, "client_id": "CLI", "system_account_key": "gst_cess_input",
                                  "account_name": "Compensation Cess Input Credit", "is_active": True})
    db.seed("service_catalogue", {"id": "SVC-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Aerated water", "kind": "good"})
    return db


def _cess_line(**over):
    kw = dict(description="aerated water", quantity=QTY, rate_paise=RATE, gst_rate_percent=18.0, service_catalogue_id="SVC-CLI",
              cess_rate_bps=1_200, cess_specific_paise_per_unit=400)
    kw.update(over)
    return InvoiceLineIn(**kw)


def _issued_invoice(db) -> str:
    res = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST-CLI", invoice_no="INV-1", invoice_date="2025-06-01", supply_state_code="27",
        lines=[SalesInvoiceLineIn(description="aerated water", quantity=QTY, rate_paise=RATE, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-CLI", cess_rate_bps=1_200, cess_specific_paise_per_unit=400)]), CALLER)
    assert res["success"] is True, res
    assert si.issue_invoice(res["data"]["id"], CALLER)["success"] is True
    return res["data"]["id"]


def _received_bill(db) -> str:
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND-CLI", bill_date="2025-06-01", bill_no="BILL-1",
        lines=[PurchaseBillLineIn(description="aerated water", quantity=QTY, rate_paise=RATE, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-CLI", cess_rate_bps=1_200, cess_specific_paise_per_unit=400)]), CALLER)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]["id"]


def _make_credit_note(db, lines):
    return cn.create_credit_note(cn.CreditNoteIn(client_id="CLI", customer_id="CUST-CLI", credit_note_date="2025-06-05",
                                                 sales_invoice_id=_issued_invoice(db), reason="returned", goods_returned=False,
                                                 lines=lines), CALLER)


def _make_debit_note(db, lines):
    return dn.create_debit_note(dn.DebitNoteIn(client_id="CLI", vendor_id="VEND-CLI", debit_note_date="2025-06-05",
                                               purchase_bill_id=_received_bill(db), reason="returned", goods_returned=False,
                                               lines=lines), CALLER)


def _make_sales_debit_note(db, lines):
    return sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(client_id="CLI", customer_id="CUST-CLI", debit_note_date="2025-06-05",
                                                            sales_invoice_id=_issued_invoice(db), reason="undercharged",
                                                            lines=lines), CALLER)


def _make_purchase_credit_note(db, lines):
    return pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(client_id="CLI", vendor_id="VEND-CLI",
                                                                    credit_note_date="2025-06-05", purchase_bill_id=_received_bill(db),
                                                                    reason="undercharged", lines=lines), CALLER)


# kind -> (header table, line table and its key, make, issue, edit, the cess ledger, the side the cess is posted on)
NOTES = {
    rule.CREDIT_NOTE: ("credit_notes", "credit_note_lines", "credit_note_id", _make_credit_note,
                       lambda i: cn.issue_credit_note(i, CALLER),
                       lambda i, ls: cn.update_credit_note(i, cn.CreditNoteUpdateIn(lines=ls), CALLER),
                       "ACC-CESS-OUT", "debit_paise"),
    rule.SALES_DEBIT_NOTE: ("sales_debit_notes", "sales_debit_note_lines", "debit_note_id", _make_sales_debit_note,
                            lambda i: sdn.issue_sales_debit_note(i, CALLER),
                            lambda i, ls: sdn.update_sales_debit_note(i, sdn.SalesDebitNoteUpdateIn(lines=ls), CALLER),
                            "ACC-CESS-OUT", "credit_paise"),
    rule.DEBIT_NOTE: ("debit_notes", "debit_note_lines", "debit_note_id", _make_debit_note,
                      lambda i: dn.issue_debit_note(i, CALLER),
                      lambda i, ls: dn.update_debit_note(i, dn.DebitNoteUpdateIn(lines=ls), CALLER),
                      "ACC-CESS-IN", "credit_paise"),
    rule.PURCHASE_CREDIT_NOTE: ("purchase_credit_notes", "purchase_credit_note_lines", "credit_note_id", _make_purchase_credit_note,
                                lambda i: pcn.issue_purchase_credit_note(i, CALLER),
                                lambda i, ls: pcn.update_purchase_credit_note(i, pcn.PurchaseCreditNoteUpdateIn(lines=ls), CALLER),
                                "ACC-CESS-IN", "debit_paise"),
}


def _row(db, table, doc_id):
    return next(r for r in db.rows(table) if r["id"] == doc_id)


def _note_journal_lines(db, header_table, doc_id):
    """The lines of the one journal the note's issue posted, found by the source the kernel stamps on it."""
    (entry,) = [e["id"] for e in db.rows("journal_entries") if e.get("source_id") == doc_id]
    return [ln for ln in db.rows("journal_lines") if ln.get("journal_entry_id") == entry]


@pytest.mark.parametrize("kind", list(NOTES))
def test_a_note_stores_the_cess_on_its_lines_and_its_header_and_the_total_carries_it(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, lines_table, fk, make, *_ = NOTES[kind]
    res = make(db, [_cess_line()])
    assert res["success"] is True, res
    note = _row(db, header_table, res["data"]["id"])
    assert note["cess_paise"] == CESS
    assert note["total_paise"] == TAXABLE + GST + CESS
    assert note["total_gst_paise"] == GST, "the cess is its own levy and never part of the GST (Compensation Act s.11(2))"
    (line,) = [ln for ln in db.rows(lines_table) if ln.get(fk) == note["id"]]
    assert (line["cess_rate_bps"], line["cess_specific_paise_per_unit"], line["cess_paise"]) == (1_200, 400, CESS)
    assert line["line_total_paise"] == TAXABLE + GST + CESS


@pytest.mark.parametrize("kind", list(NOTES))
def test_a_note_with_cess_issues_and_posts_the_cess_to_its_own_ledger_on_the_right_side(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, _lt, _fk, make, issue, _edit, ledger, side = NOTES[kind]
    note_id = make(db, [_cess_line()])["data"]["id"]
    res = issue(note_id)
    assert res["success"] is True, res
    legs = _note_journal_lines(db, header_table, note_id)
    cess_legs = [ln for ln in legs if ln["account_id"] == ledger]
    assert len(cess_legs) == 1, legs
    other = "credit_paise" if side == "debit_paise" else "debit_paise"
    assert (int(cess_legs[0][side]), int(cess_legs[0].get(other) or 0)) == (CESS, 0)
    assert sum(int(ln.get("debit_paise") or 0) for ln in legs) == sum(int(ln.get("credit_paise") or 0) for ln in legs)
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


@pytest.mark.parametrize("kind", list(NOTES))
def test_a_note_with_no_cess_posts_no_cess_leg_and_is_what_it_was(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, _lt, _fk, make, issue, _edit, ledger, _side = NOTES[kind]
    note_id = make(db, [_cess_line(cess_rate_bps=None, cess_specific_paise_per_unit=None)])["data"]["id"]
    assert _row(db, header_table, note_id)["cess_paise"] == 0
    assert _row(db, header_table, note_id)["total_paise"] == TAXABLE + GST
    assert issue(note_id)["success"] is True
    assert not [ln for ln in _note_journal_lines(db, header_table, note_id) if ln["account_id"] == ledger]


@pytest.mark.parametrize("kind", list(NOTES))
def test_an_edit_that_takes_the_cess_off_a_draft_takes_it_off_the_header_and_the_total(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, _lt, _fk, make, issue, edit, *_ = NOTES[kind]
    note_id = make(db, [_cess_line()])["data"]["id"]
    res = edit(note_id, [_cess_line(cess_rate_bps=0, cess_specific_paise_per_unit=0)])
    assert res["success"] is True, res
    note = _row(db, header_table, note_id)
    assert (note["cess_paise"], note["total_paise"]) == (0, TAXABLE + GST)
    res = edit(note_id, [_cess_line(cess_specific_paise_per_unit=0)])
    assert _row(db, header_table, note_id)["cess_paise"] == AD_VALOREM
    assert issue(note_id)["success"] is True, "the issue check agrees with what the edit wrote"


@pytest.mark.parametrize("kind", list(NOTES))
def test_the_issue_check_refuses_a_note_whose_cess_is_not_its_lines(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, _lt, _fk, make, issue, *_ = NOTES[kind]
    note_id = make(db, [_cess_line()])["data"]["id"]
    row = _row(db, header_table, note_id)
    row["cess_paise"] -= 1              # what a member's own token could write onto a draft
    row["total_paise"] -= 1
    with pytest.raises(HTTPException) as e:
        issue(note_id)
    assert e.value.status_code == 422 and "cess" in e.value.detail


@pytest.mark.parametrize("kind", [rule.CREDIT_NOTE, rule.DEBIT_NOTE, rule.PURCHASE_CREDIT_NOTE, rule.SALES_DEBIT_NOTE])
def test_a_notes_cess_enters_its_total_in_the_pure_rule(kind):
    header = {"taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0, "total_gst_paise": 18_000,
              "cess_paise": 1_200, "total_paise": 119_200}
    lines = [{"taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0, "cess_paise": 1_200}]
    assert rule.problems(kind, header, lines) == []
    found = rule.problems(kind, dict(header, total_paise=118_000), lines)
    assert found and "plus the tax and cess" in found[0].text


# ── the return names only a note with no cess ────────────────────────────────────────────────────────────────────────────

def test_the_gstr1_gap_names_a_note_with_no_cess_against_a_cess_invoice_and_not_one_that_carries_its_own():
    import services.gst_return_service as grs

    parents = {"INV-1": {"cess_paise": 12_000}, "INV-2": {"cess_paise": 0}}
    notes = [{"sales_invoice_id": "INV-1", "credit_note_no": "CN-1", "cess_paise": 0},
             {"sales_invoice_id": "INV-1", "credit_note_no": "CN-3", "cess_paise": 1_200},
             {"sales_invoice_id": "INV-2", "credit_note_no": "CN-2", "cess_paise": 0},
             {"sales_invoice_id": "INV-1", "debit_note_no": "DN-1"}]          # a note recorded before 615 reads no key at all
    gaps = grs._note_cess_not_carried(notes, parents)
    joined = " ".join(gaps)
    assert len(gaps) == 2 and "CN-1" in joined and "DN-1" in joined
    assert "CN-3" not in joined and "CN-2" not in joined
    assert "₹120.00" in gaps[0] and "carries no compensation cess" in gaps[0] and "paise" not in gaps[0]
