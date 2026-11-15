"""A live IRN is checked against the GSTR-1 the books build for its period, and a record that no longer names its invoice is said
(POST-A-066).

WHAT WAS MISSING
    The e-invoice rail records an IRN a person obtained on the IRP and lists the invoices that owe one and have none. Nothing looked
    the other way: an IRN recorded as live for an invoice the period's return does not declare (deleted or cancelled in the books, a
    draft, a carried-over document, another period, a supply the return declares elsewhere or only within a total), or a record whose
    number or date is not its invoice's.

WHAT IS HELD
    * each reason, the record that differs from its invoice, more than one live record naming one invoice, and the cases that are not
      reported (a declared invoice, a record that is not live, a record of another period);
    * the invoice's OWN state is asked before its number: a deleted draft whose number a new invoice reused, and a cancelled invoice
      whose number differs only in case from a declared one, are reported and never passed as declared (an independent read found
      both shown clean);
    * an unlinked record is resolved to its invoice by its number and judged like a linked one;
    * "declared" is the B2B and export tables; a B2CL invoice is named as declared there; an invoice within a total is said to be,
      without the check guessing which total;
    * through the real GSTR-1 build on the in-memory books: a B2B invoice with its IRN is not reported, and a supply to an
      unregistered customer, a cancelled invoice, a record whose invoice moved to the next month, a deleted draft's reused number and an
      unlinked record whose invoice is in July are; another firm's record linked to the client's invoice is not read.
"""
from __future__ import annotations

from domain.gst import irn_against_return as rule

JUNE = ("2025-06-01", "2025-06-30")


def _payload(*b2b, exp=(), b2cl=()):
    return {"b2b": [{"ctin": "27BBBBB1111B1ZN", "inv": [{"inum": n, "idt": "10-06-2025"} for n in b2b]}],
            "exp": [{"exp_typ": "WOPAY", "inv": [{"inum": n} for n in exp]}],
            "b2cl": [{"pos": "29", "inv": [{"inum": n} for n in b2cl]}]}


def _record(no, day="2025-06-10", invoice_id=None, status="generated", rid=None, irn="default"):
    return {"id": rid or f"rec-{no}", "invoice_number": no, "invoice_date": day, "status": status,
            "irn": f"IRN-{no}" if irn == "default" else irn, "sales_invoice_id": invoice_id}


def _invoice(iid, no, day="2025-06-10", status="issued", **kw):
    return {iid: {"id": iid, "invoice_no": no, "invoice_date": day, "status": status, **kw}}


def _check(payload, records, invoices):
    return rule.compare(payload, records, invoices, *JUNE)


def test_a_declared_invoice_with_its_irn_is_not_reported():
    got = _check(_payload("INV/1"), [_record("INV/1", invoice_id="i1")], _invoice("i1", "INV/1"))
    assert (got["not_declared"], got["differs"], got["live_irns_compared"], got["declared_invoices"]) == ([], [], 1, 1)


def test_each_reason_is_named():
    invoices = {**_invoice("c", "C/1", status="cancelled"), **_invoice("d", "D/1", status="draft"),
                **_invoice("o", "O/1", is_opening=True), **_invoice("n", "N/1"), **_invoice("x", "X/1", status="draft",
                                                                                             deleted_at="2025-06-20"),
                **_invoice("l", "L/1")}
    records = [_record("C/1", invoice_id="c"), _record("D/1", invoice_id="d"), _record("O/1", invoice_id="o"),
               _record("N/1", invoice_id="n"), _record("X/1", invoice_id="x"), _record("U/9"), _record("L/1", invoice_id="l")]
    got = {r["record_number"]: r["reason"] for r in _check(_payload("A/1", b2cl=("L/1",)), records, invoices)["not_declared"]}
    assert got == {"C/1": "invoice_cancelled", "D/1": "invoice_not_issued", "O/1": "carried_over", "N/1": "not_declared",
                   "X/1": "invoice_deleted", "U/9": "no_invoice", "L/1": "declared_elsewhere"}


def test_a_deleted_drafts_number_reused_by_a_declared_invoice_is_not_passed_as_declared():
    """The record is linked to the deleted draft; a new invoice took its number and the return declares it. The state is asked first."""
    invoices = {**_invoice("old", "00002", status="draft", deleted_at="2025-06-05"), **_invoice("new", "00002")}
    got = _check(_payload("00002"), [_record("00002", invoice_id="old")], invoices)
    assert [r["reason"] for r in got["not_declared"]] == ["invoice_deleted"]


def test_a_cancelled_invoice_whose_number_differs_from_a_declared_one_only_in_case_is_reported():
    invoices = {**_invoice("low", "inv-a", status="cancelled"), **_invoice("up", "INV-A")}
    got = _check(_payload("INV-A"), [_record("inv-a", invoice_id="low")], invoices)
    assert [r["reason"] for r in got["not_declared"]] == ["invoice_cancelled"]


def test_an_unlinked_record_is_resolved_by_its_number_and_judged_like_a_linked_one():
    invoices = {**_invoice("c", "C/2", status="cancelled"), **_invoice("i", "I/2", day="2025-06-12"), **_invoice("e", "E/2")}
    records = [_record("C/2"), _record("I/2", day="2025-06-11"), _record("E/2", rid="e1"), _record("E/2", rid="e2")]
    got = _check(_payload("I/2", "E/2"), records, invoices)
    assert {r["record_number"]: r["reason"] for r in got["not_declared"]} == {"C/2": "invoice_cancelled"}
    assert [r["record_number"] for r in got["differs"]] == ["I/2"], "an unlinked record's date is compared too"
    assert [d["record_ids"] for d in got["duplicates"]] == [["e1", "e2"]]
    assert "2 live IRN records name invoice E/2" in got["duplicates"][0]["sentence"]


def test_a_generated_record_with_no_irn_is_not_live():
    got = _check(_payload(), [_record("N/9", irn=""), _record("N/8", irn=None)], {})
    assert (got["not_declared"], got["live_irns_compared"]) == ([], 0)


def test_an_invoice_that_moved_to_another_month_is_another_returns_and_the_record_differs():
    got = _check(_payload(), [_record("M/1", day="2025-06-28", invoice_id="m")], _invoice("m", "M/1", day="2025-07-02"))
    assert [r["reason"] for r in got["not_declared"]] == ["other_period"]
    assert "dated 02-07-2025, outside this return's period" in got["not_declared"][0]["sentence"]
    assert got["differs"][0]["sentence"] == "The IRN record says M/1 of 28-06-2025; the invoice it names is M/1 of 02-07-2025."


def test_a_record_whose_number_is_not_its_invoices_differs_even_when_the_invoice_is_declared():
    got = _check(_payload("INV/2"), [_record("INV/1", invoice_id="i")], _invoice("i", "INV/2"))
    assert got["not_declared"] == [] and [(r["record_number"], r["invoice_number"]) for r in got["differs"]] == [("INV/1", "INV/2")]


def test_a_record_that_is_not_live_or_belongs_to_another_period_is_not_compared():
    records = [_record("A/1", status="draft"), _record("A/2", status="cancelled"), _record("A/3", day="2025-05-31"),
               _record("A/4", day="2025-07-01")]
    got = _check(_payload(), records, {})
    assert (got["not_declared"], got["live_irns_compared"]) == ([], 0)


def test_a_record_dated_outside_the_period_whose_invoice_is_in_it_is_compared():
    got = _check(_payload(), [_record("B/1", day="2025-05-30", invoice_id="b")], _invoice("b", "B/1", day="2025-06-02"))
    assert [r["reason"] for r in got["not_declared"]] == ["not_declared"] and len(got["differs"]) == 1


def test_an_export_is_declared_and_a_record_with_no_invoice_is_matched_by_its_number():
    got = _check(_payload(exp=("EXP/1",)), [_record("EXP/1", invoice_id="e"), _record("exp/1 ", rid="loose")],
                 _invoice("e", "EXP/1"))
    assert got["not_declared"] == [] and got["declared_invoices"] == 1


def test_a_number_is_matched_as_written_and_not_by_dropping_its_separators():
    """`INV-1` and `INV/1` are two of this client's own numbers; pairing them would pass an invoice the return does not declare."""
    got = _check(_payload("INV-1"), [_record("INV/1", invoice_id="i")], _invoice("i", "INV/1"))
    assert [r["reason"] for r in got["not_declared"]] == ["not_declared"]
    unlinked = _check(_payload("INV-1"), [_record("INV/1")], {})
    assert [r["reason"] for r in unlinked["not_declared"]] == ["no_invoice"]
    assert "carries the record's number INV/1" in unlinked["not_declared"][0]["sentence"]


def test_the_answer_points_to_the_converse_and_names_what_it_does_not_compare():
    got = _check(_payload(), [], {})
    assert "missing-IRN list" in got["converse"] and "Credit and debit notes are not compared" in got["not_compared"]
    assert "as they stand now" in got["not_compared"]


# ── through the real GSTR-1 build ───────────────────────────────────────────

def test_through_the_real_build(monkeypatch):
    from services import irn_return_check_service as svc
    from tests.test_gst_return_reconciliation import GSTIN, PERIOD, _issue_invoice, _setup
    db = _setup(monkeypatch)
    db.seed("customers", {"id": "CUST2", "firm_id": "FIRM-A", "client_id": "CLI", "name": "Walk-in", "state_code": "27",
                          "is_active": True, "opening_balance_paise": 0})
    b2b = _issue_invoice(db, "INV/1", 100_000_00, 9_000_00, 9_000_00)
    walk_in = _issue_invoice(db, "INV/2", 50_000_00, 4_500_00, 4_500_00)
    next(r for r in db.rows("client_sales_invoices") if r["id"] == walk_in)["customer_id"] = "CUST2"
    gone = _issue_invoice(db, "INV/3", 10_000_00, 900_00, 900_00)
    next(r for r in db.rows("client_sales_invoices") if r["id"] == gone)["status"] = "cancelled"
    moved = _issue_invoice(db, "INV/4", 10_000_00, 900_00, 900_00, date="2025-07-02")
    for no, iid, day in (("INV/1", b2b, "2025-06-10"), ("INV/2", walk_in, "2025-06-10"), ("INV/3", gone, "2025-06-10"),
                         ("INV/4", moved, "2025-06-29")):
        db.seed("einvoice_records", {"firm_id": "FIRM-A", "client_id": "CLI", "sales_invoice_id": iid, "invoice_number": no,
                                     "invoice_date": day, "status": "generated", "irn": f"IRN-{no}"})
    # A draft whose IRN was recorded, deleted, and its number reused by an issued invoice the return declares.
    reused = _issue_invoice(db, "INV/5", 10_000_00, 900_00, 900_00)
    db.seed("client_sales_invoices", {"id": "draft-5", "firm_id": "FIRM-A", "client_id": "CLI", "customer_id": "CUST1",
                                      "invoice_no": "INV/5", "invoice_date": "2025-06-03", "status": "draft",
                                      "deleted_at": "2025-06-04T10:00:00+00:00", "total_paise": 0})
    db.seed("einvoice_records", {"firm_id": "FIRM-A", "client_id": "CLI", "sales_invoice_id": "draft-5", "invoice_number": "INV/5",
                                 "invoice_date": "2025-06-03", "status": "generated", "irn": "IRN-DRAFT-5"})
    # An unlinked record dated in June whose invoice (found by its number) is dated in July.
    july = _issue_invoice(db, "INV/6", 10_000_00, 900_00, 900_00, date="2025-07-05")
    db.seed("einvoice_records", {"firm_id": "FIRM-A", "client_id": "CLI", "sales_invoice_id": None, "invoice_number": "INV/6",
                                 "invoice_date": "2025-06-30", "status": "generated", "irn": "IRN-6"})
    # Another firm's record linked to this client's invoice is never read.
    db.seed("einvoice_records", {"firm_id": "FIRM-ELSE", "client_id": "CLI", "sales_invoice_id": walk_in, "invoice_number": "INV/2",
                                 "invoice_date": "2025-06-10", "status": "generated", "irn": "IRN-ELSE"})
    got = svc.check(db, "FIRM-A", "CLI", PERIOD, GSTIN)
    assert {r["record_number"]: r["reason"] for r in got["not_declared"]} == {
        "INV/2": "not_declared", "INV/3": "invoice_cancelled", "INV/4": "other_period", "INV/5": "invoice_deleted",
        "INV/6": "other_period"}
    assert sorted(r["record_number"] for r in got["differs"]) == ["INV/4", "INV/6"]
    assert (got["live_irns_compared"], got["declared_invoices"], got["period"]) == (6, 2, PERIOD)
    assert got["duplicates"] == [] and reused and july
