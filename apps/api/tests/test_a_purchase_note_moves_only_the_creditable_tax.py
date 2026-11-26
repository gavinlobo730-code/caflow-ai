"""A purchase debit note or purchase credit note moves the credit ledgers by the creditable tax only (POST-A-459, migration 685).

WHAT WAS WRONG
    A purchase bill line says whether its credit is blocked under CGST Act s.17(5), and the bill's journal debits GST Input and the cess
    credit with the creditable tax only, putting the blocked tax on the cost. The two purchase notes had no such mark: a debit note (a
    return to the supplier) credited GST Input and the cess credit with its WHOLE tax and a purchase credit note (the supplier's
    increase) debited them with its whole tax, so a note against a blocked line moved the credit ledgers by tax that was never credit.
    GSTR-3B from the books netted the whole tax out of 4(A) and left 4(B)(1) alone, so 4(C) moved by the blocked tax too.

WHAT THIS HOLDS
    * the note line model takes the mark and refuses a blocked line with no reason, and still accepts a line built as before;
    * for both notes, end to end: a blocked line and an eligible one store their marks, the header's four blocked heads are the blocked
      line's, the draft issues, and the journal moves GST Input and the cess credit by the eligible line's tax only, the cost by the
      taxable value plus the blocked tax, and balances;
    * a note with no blocked line stores no new key (so it saves before the migration has run) and posts exactly as before;
    * an edit that takes the mark off sets the header's blocked heads back to nil;
    * the issue check refuses a header whose blocked heads are not its lines';
    * GSTR-3B from the books takes a blocked debit note's tax out of 4(B)(1) as well as 4(A), so 4(C) moves by the creditable tax only.

NEGATIVE CONTROL: against the code before this change the model drops the mark (an unknown field), so every blocked case finds no mark
and the full tax on the credit ledgers; 11 of the tests here fail.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.purchase_credit_notes as pcn
import routers.vendors as ve
from domain.accounting import draft_integrity as rule
from models.invoices import InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, PurchaseNoteLineIn
from tests.e2e_harness import FakeDB, seed_standard_coa, trial_balance, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
GSTIN = "27AAAAA0000A1Z2"
GST_INPUT, CESS_INPUT = None, "ACC-CESS-IN"

# Two lines of ₹1,000 at 18% with cess at 12%: the first is a club membership (blocked), the second ordinary.
RATE = 100_000
GST_LINE = RATE * 1_800 // 10_000            # 18,000 paise, 9,000 + 9,000
CESS_LINE = RATE * 1_200 // 10_000           # 12,000 paise


def _setup(monkeypatch) -> FakeDB:
    db = FakeDB()
    wire_e2e(monkeypatch, db, [dn, pb, pcn, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN, "state_code": "27", "gst_filing_frequency": None,
                        "financial_year_start": "2025-04-01"})
    db.seed("vendors", {"id": "VEND-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("chart_of_accounts", {"id": CESS_INPUT, "firm_id": FIRM, "client_id": "CLI", "system_account_key": "gst_cess_input",
                                  "account_name": "Compensation Cess Input Credit", "is_active": True})
    db.seed("service_catalogue", {"id": "SVC-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Membership", "kind": "service"})
    return db


def _line(blocked: bool, **over) -> PurchaseNoteLineIn:
    kw = dict(description="club membership" if blocked else "stationery", quantity=1, rate_paise=RATE, gst_rate_percent=18.0,
              service_catalogue_id="SVC-CLI", cess_rate_bps=1_200)
    if blocked:
        kw.update(itc_eligible=False, blocked_credit_reason="17_5_b_club_membership")
    kw.update(over)
    return PurchaseNoteLineIn(**kw)


def _received_bill(db) -> str:
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND-CLI", bill_date="2025-06-01", bill_no="BILL-1",
        lines=[PurchaseBillLineIn(description="club membership", quantity=1, rate_paise=RATE, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-CLI", cess_rate_bps=1_200, itc_eligible=False,
                                  blocked_credit_reason="17_5_b_club_membership"),
               PurchaseBillLineIn(description="stationery", quantity=1, rate_paise=RATE, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-CLI", cess_rate_bps=1_200)]), CALLER)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]["id"]


def _make_debit_note(db, lines):
    return dn.create_debit_note(dn.DebitNoteIn(client_id="CLI", vendor_id="VEND-CLI", debit_note_date="2025-06-05",
                                               purchase_bill_id=_received_bill(db), reason="returned", goods_returned=False,
                                               lines=lines), CALLER)


def _make_purchase_credit_note(db, lines):
    return pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(client_id="CLI", vendor_id="VEND-CLI",
                                                                    credit_note_date="2025-06-05", purchase_bill_id=_received_bill(db),
                                                                    reason="undercharged", lines=lines), CALLER)


# kind -> (header table, line table, key, make, issue, edit, the side the credit ledgers move on)
NOTES = {
    rule.DEBIT_NOTE: ("debit_notes", "debit_note_lines", "debit_note_id", _make_debit_note,
                      lambda i: dn.issue_debit_note(i, CALLER),
                      lambda i, ls: dn.update_debit_note(i, dn.DebitNoteUpdateIn(lines=ls), CALLER), "credit_paise"),
    rule.PURCHASE_CREDIT_NOTE: ("purchase_credit_notes", "purchase_credit_note_lines", "credit_note_id", _make_purchase_credit_note,
                                lambda i: pcn.issue_purchase_credit_note(i, CALLER),
                                lambda i, ls: pcn.update_purchase_credit_note(i, pcn.PurchaseCreditNoteUpdateIn(lines=ls), CALLER),
                                "debit_paise"),
}
BLOCKED_HEADS = ("ineligible_itc_cgst_paise", "ineligible_itc_sgst_paise", "ineligible_itc_igst_paise", "ineligible_itc_cess_paise")


def _row(db, table, doc_id):
    return next(r for r in db.rows(table) if r["id"] == doc_id)


def _account(db, key):
    return next(r["id"] for r in db.rows("chart_of_accounts") if r.get("system_account_key") == key and r.get("client_id") == "CLI")


def _note_legs(db, doc_id):
    (entry,) = [e["id"] for e in db.rows("journal_entries") if e.get("source_id") == doc_id]
    return [ln for ln in db.rows("journal_lines") if ln.get("journal_entry_id") == entry]


def _moved(legs, account, side):
    return sum(int(ln.get(side) or 0) for ln in legs if ln["account_id"] == account)


# ── the model ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_note_line_takes_the_mark_and_a_blocked_line_names_its_reason():
    assert _line(True).itc_eligible is False
    with pytest.raises(ValueError, match="blocked_credit_reason is required"):
        PurchaseNoteLineIn(description="x", rate_paise=1, service_catalogue_id="S", itc_eligible=False)
    old = InvoiceLineIn(description="x", rate_paise=1, service_catalogue_id="S")
    assert dn.DebitNoteIn(client_id="C", vendor_id="V", debit_note_date="2025-06-05", lines=[old]).lines[0].itc_eligible is True, \
        "a line built as before is read and is eligible"


# ── both notes, end to end ───────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", list(NOTES))
def test_a_blocked_line_is_stored_with_its_mark_and_the_header_carries_its_tax(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, lines_table, fk, make, *_ = NOTES[kind]
    res = make(db, [_line(True), _line(False)])
    assert res["success"] is True, res
    note = _row(db, header_table, res["data"]["id"])
    assert tuple(note[h] for h in BLOCKED_HEADS) == (GST_LINE // 2, GST_LINE // 2, 0, CESS_LINE)
    lines = sorted((ln for ln in db.rows(lines_table) if ln.get(fk) == note["id"]), key=lambda ln: ln["description"])
    assert [(ln["description"], ln["itc_eligible"], ln["blocked_credit_reason"]) for ln in lines] == [
        ("club membership", False, "17_5_b_club_membership"), ("stationery", True, None)]


@pytest.mark.parametrize("kind", list(NOTES))
def test_the_journal_moves_the_credit_ledgers_by_the_creditable_tax_and_the_cost_by_the_rest(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, _lt, _fk, make, issue, _edit, side = NOTES[kind]
    note_id = make(db, [_line(True), _line(False)])["data"]["id"]
    assert issue(note_id)["success"] is True
    legs = _note_legs(db, note_id)
    gst_input = _account(db, "gst_input")
    assert _moved(legs, gst_input, side) == GST_LINE, "only the eligible line's GST reaches GST Input"
    assert _moved(legs, CESS_INPUT, side) == CESS_LINE, "only the eligible line's cess reaches the cess credit"
    other = "debit_paise" if side == "credit_paise" else "credit_paise"
    payable = _account(db, "ap")
    cost = sum(int(ln.get(side) or 0) for ln in legs if ln["account_id"] not in (gst_input, CESS_INPUT, payable))
    assert cost == 2 * RATE + GST_LINE + CESS_LINE, "the blocked tax goes back to (or onto) the cost, as on the bill"
    assert _moved(legs, payable, other) == 2 * (RATE + GST_LINE + CESS_LINE)
    assert sum(int(ln.get("debit_paise") or 0) for ln in legs) == sum(int(ln.get("credit_paise") or 0) for ln in legs)
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


@pytest.mark.parametrize("kind", list(NOTES))
def test_a_note_with_no_blocked_line_stores_no_new_key_and_posts_as_before(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, lines_table, fk, make, issue, _edit, side = NOTES[kind]
    note_id = make(db, [_line(False), _line(False, description="toner")])["data"]["id"]
    note = _row(db, header_table, note_id)
    assert not any(h in note for h in BLOCKED_HEADS), "a header the database before migration 685 could not store"
    assert not any("itc_eligible" in ln for ln in db.rows(lines_table) if ln.get(fk) == note_id)
    assert issue(note_id)["success"] is True
    assert _moved(_note_legs(db, note_id), _account(db, "gst_input"), side) == 2 * GST_LINE


@pytest.mark.parametrize("kind", list(NOTES))
def test_an_edit_that_takes_the_mark_off_sets_the_blocked_heads_back_to_nil(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, lines_table, fk, make, issue, edit, side = NOTES[kind]
    note_id = make(db, [_line(True), _line(False)])["data"]["id"]
    res = edit(note_id, [_line(False, description="club membership"), _line(False)])
    assert res["success"] is True, res
    assert tuple(_row(db, header_table, note_id)[h] for h in BLOCKED_HEADS) == (0, 0, 0, 0)
    assert issue(note_id)["success"] is True, "the issue check agrees with what the edit wrote"
    assert _moved(_note_legs(db, note_id), _account(db, "gst_input"), side) == 2 * GST_LINE


@pytest.mark.parametrize("kind", list(NOTES))
def test_the_issue_check_refuses_a_header_whose_blocked_heads_are_not_its_lines(monkeypatch, kind):
    db = _setup(monkeypatch)
    header_table, _lt, _fk, make, issue, *_ = NOTES[kind]
    note_id = make(db, [_line(True), _line(False)])["data"]["id"]
    _row(db, header_table, note_id)["ineligible_itc_cgst_paise"] = 0     # what a member's own token could write onto a draft
    with pytest.raises(HTTPException) as e:
        issue(note_id)
    assert e.value.status_code == 422 and "blocked-credit CGST" in e.value.detail


def test_the_pure_rule_holds_a_notes_blocked_heads_to_its_lines():
    header = {"taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0, "total_gst_paise": 18_000,
              "cess_paise": 0, "total_paise": 118_000, "ineligible_itc_cgst_paise": 9_000, "ineligible_itc_sgst_paise": 9_000}
    blocked = [{"taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0, "cess_paise": 0,
                "itc_eligible": False}]
    for kind in (rule.DEBIT_NOTE, rule.PURCHASE_CREDIT_NOTE):
        assert rule.problems(kind, header, blocked) == []
        assert rule.problems(kind, header, [{**blocked[0], "itc_eligible": True}]), kind
    assert rule.problems(rule.SALES_DEBIT_NOTE, header, [{**blocked[0], "itc_eligible": True}]) == [], \
        "a sales note carries no input credit and is not asked"


# ── the return ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_gstr3b_takes_a_blocked_debit_note_out_of_4b1_as_well_as_4a(monkeypatch):
    """The bill: ₹1,000 blocked + ₹1,000 eligible, ₹180 GST each. A return of the blocked line takes ₹180 out of 4(A) AND out of
    4(B)(1), so 4(C) stays at the eligible line's ₹180. Before, 4(A) fell by ₹180 and 4(B)(1) did not, and 4(C) read nil."""
    import services.gst_return_service as grs

    db = _setup(monkeypatch)
    note_id = _make_debit_note(db, [_line(True, cess_rate_bps=None)])["data"]["id"]
    assert dn.issue_debit_note(note_id, CALLER)["success"] is True
    out = grs.gstr3b_from_books(db, FIRM, "CLI", "062025", GSTIN)
    itc = out["payload"]["itc_elg"]
    four_a = sum(int(r["camt"]) + int(r["samt"]) for r in itc["itc_avl"])
    four_b1 = next(r for r in itc["itc_rev"] if r["ty"] == "RUL")
    assert four_a == 180, "the bill's ₹360 less the note's ₹180"
    assert int(four_b1["camt"]) + int(four_b1["samt"]) == 0, "the bill's ₹180 blocked less the note's ₹180 blocked"
    assert int(itc["itc_net"]["camt"]) + int(itc["itc_net"]["samt"]) == 180
    rows = grs.gstr3b_detail(db, FIRM, "CLI", "062025", "4B1")["rows"]
    noted = [r for r in rows if r["kind"] == "Blocked ITC (s.17(5)), debit note"]
    assert [(r["cgst_paise"], r["sgst_paise"]) for r in noted] == [(-GST_LINE // 2, -GST_LINE // 2)], \
        "the 4(B)(1) drill-down lists the note's blocked tax with its sign, so it foots to the line"
