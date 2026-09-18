"""§16(2)(aa) is a condition on EACH invoice, and Rule 36(4) was applied to a
per-head SUM (GST-19).

The defect the finding names, exactly: a month with one bill the supplier never
filed and another where GSTR-2B carries MORE tax than the books nets to zero,
the aggregate cap never fires, and the return claims credit on an invoice
nobody furnished. `test_a_month_that_nets_to_zero_still_withholds_the_unfiled_bill`
is that case and fails against the previous code.

The second half of the finding is what a CA is TOLD. The old answer was one
sentence — "credit was trimmed to the GSTR-2B figure" — with no list, so
finding out which documents were disallowed meant cross-referencing the
GSTR-2B Recon tab by hand.
"""
import pytest

from domain.gst import rule_36_4 as r36
from domain.gst.gstr3b_computer import (GSTR2ARecord, PurchaseTransaction,
                                        SalesTransaction, compute_gstr3b)


def _book(doc_id, label, cgst=0, sgst=0, igst=0, cess=0, rcm=False,
          examined=True):
    return r36.BookDocument(document_id=doc_id, label=label, supplier="Acme",
                            cgst_paise=cgst, sgst_paise=sgst, igst_paise=igst,
                            cess_paise=cess, is_reverse_charge=rcm,
                            was_examined=examined)


def _purchase(doc_id, label, igst=0, blocked_igst=0):
    """One posted purchase bill as the return service builds it."""
    return PurchaseTransaction(
        taxable_amount_paise=1_000_000, cgst_paise=0, sgst_paise=0,
        igst_paise=igst, cess_paise=0, is_reverse_charge=False,
        ineligible_igst_paise=blocked_igst,
        document_id=doc_id, document_label=label)


def _filed(cgst=0, sgst=0, igst=0, cess=0, available="Y", reason=""):
    return r36.TwoBDocument(matched=True, itc_available=available,
                            reason_code=reason, cgst_paise=cgst,
                            sgst_paise=sgst, igst_paise=igst, cess_paise=cess)


# ═════════════════════════════════════════════════════════════════════════════
# THE DEFECT
# ═════════════════════════════════════════════════════════════════════════════

def test_a_month_that_nets_to_zero_still_withholds_the_unfiled_bill():
    """THE FINDING, AS A NUMBER. Two bills of ₹18,000 IGST each. The supplier
    of the first never filed it; the second was filed with ₹36,000 against it.
    Per-head the books total ₹36,000 and 2B totals ₹36,000, so the aggregate
    cap sees nothing to trim — and the return claims credit on an invoice
    §16(2)(aa) withholds."""
    got = r36.assess(
        [_book("b1", "INV/1", igst=1_800_000),
         _book("b2", "INV/2", igst=1_800_000)],
        {"b2": _filed(igst=3_600_000)},
        have_2b=True)

    assert got.applied
    assert got.allowed_igst_paise == 1_800_000, (
        "the credit on the bill nobody filed must not survive because another "
        "bill happens to be over-filed by the same amount")
    assert got.withheld_igst_paise == 1_800_000
    assert [(v.label, v.verdict) for v in got.withheld] == [("INV/1", "not_in_2b")]
    # And the over-filed one is NOT capped UP to the 2B figure: the rule
    # withholds, it never grants.
    allowed = {v.label: v.allowed_igst_paise for v in got.verdicts}
    assert allowed["INV/2"] == 1_800_000


def test_the_return_itself_takes_the_lower_of_the_two_tests():
    """BOTH tests apply and the LOWER survives. §16(2)(aa) and Rule 36(4) are
    two conditions, not one with two implementations, so the per-document pass
    can only ever withhold MORE — never release credit the aggregate cap held
    back."""
    purchases = [
        _purchase("b1", "INV/1", igst=1_800_000),
        _purchase("b2", "INV/2", igst=1_800_000),
    ]
    two_a = [GSTR2ARecord(cgst_paise=0, sgst_paise=0, igst_paise=3_600_000)]

    aggregate_only = compute_gstr3b([], purchases, two_a, have_2b=True)
    per_document = compute_gstr3b([], purchases, two_a, have_2b=True,
                                  two_b_by_document={"b2": _filed(igst=3_600_000)})

    assert aggregate_only.itc_igst == 3_600_000, "the defect, preserved as the premise"
    assert per_document.itc_igst == 1_800_000
    assert per_document.itc_capped_by_2a is True
    assert aggregate_only.itc_capped_by_2a is False


def test_nothing_is_released_that_the_aggregate_cap_held_back():
    """The other direction of the same rule. Books carry ₹36,000 IGST over two
    bills and the whole 2B carries ₹18,000 — but the per-document map (say a
    partially reconciled file) knows about only one of them. The aggregate cap
    still binds."""
    purchases = [
        _purchase("b1", "INV/1", igst=1_800_000),
        _purchase("b2", "INV/2", igst=1_800_000),
    ]
    got = compute_gstr3b([], purchases, [GSTR2ARecord(cgst_paise=0, sgst_paise=0, igst_paise=1_800_000)],
                         have_2b=True,
                         two_b_by_document={"b1": _filed(igst=1_800_000),
                                            "b2": _filed(igst=1_800_000)})
    assert got.itc_igst == 1_800_000


# ═════════════════════════════════════════════════════════════════════════════
# THE FIVE ANSWERS, AND WHY NONE COLLAPSES INTO ANOTHER
# ═════════════════════════════════════════════════════════════════════════════

def test_a_reverse_charge_bill_is_never_withheld_and_says_why():
    """§16(2)(aa) conditions the credit on a SUPPLIER's furnished invoice. A
    §9(3)/(4) supply is self-assessed by the recipient and discharged in cash,
    so 2B structurally cannot carry it — withholding it takes back credit on
    tax the client has already paid over."""
    got = r36.assess([_book("b1", "RCM/1", cgst=900_000, sgst=900_000, rcm=True)],
                     {}, have_2b=True)
    assert got.withheld_total_paise == 0
    assert got.allowed_cgst_paise == 900_000
    v, = got.verdicts
    assert v.verdict == r36.SELF_ASSESSED
    assert "self-assessed" in v.reason


def test_reverse_charge_is_asked_before_the_key():
    """A §9(4) supply from an UNREGISTERED supplier has no 2B row by
    construction, so testing the key first would send it to `not_in_2b` and
    withhold the credit."""
    got = r36.assess([_book(None, "RCM/unregistered", cgst=900_000, rcm=True)],
                     {}, have_2b=True)
    assert got.verdicts[0].verdict == r36.SELF_ASSESSED
    assert got.withheld_total_paise == 0


@pytest.mark.parametrize("code,fragment", [
    ("P", "place of supply"),
    ("C", "§16(4) cut-off"),
])
def test_a_document_2b_refuses_is_not_a_document_2b_lacks(code, fragment):
    """THE TWO VERDICTS ARE NOT INTERCHANGEABLE, and the reason is what the CA
    does next. A document GSTR-2B does not carry means phoning the supplier; one
    GSTR-2B carries and refuses means reading the document. Reading the second
    as the first sends them to phone somebody who has done nothing wrong."""
    got = r36.assess([_book("b1", "INV/1", igst=1_800_000)],
                     {"b1": _filed(igst=1_800_000, available="N", reason=code)},
                     have_2b=True)
    v, = got.verdicts
    assert v.verdict == r36.BLOCKED_BY_2B
    assert v.verdict != r36.NOT_IN_2B
    assert fragment in v.reason
    assert got.withheld_igst_paise == 1_800_000


def test_an_unknown_reason_code_is_reported_as_itself():
    """A code the portal emits and this module does not hold is NAMED rather
    than translated into one of the two it does: guessing which it meant tells
    a CA to fix the wrong thing."""
    got = r36.assess([_book("b1", "INV/1", igst=100)],
                     {"b1": _filed(igst=100, available="N", reason="Z")},
                     have_2b=True)
    v, = got.verdicts
    assert v.verdict == r36.BLOCKED_BY_2B
    assert "Z" in v.reason
    assert "place of supply" not in v.reason


def test_more_than_2b_is_capped_per_head_and_never_on_the_total():
    """A bill booked as IGST that the supplier filed as CGST+SGST is not a
    matching total, it is two wrong heads. Netting them would claim IGST credit
    GSTR-2B does not communicate."""
    got = r36.assess([_book("b1", "INV/1", igst=1_800_000)],
                     {"b1": _filed(cgst=900_000, sgst=900_000)},
                     have_2b=True)
    assert got.allowed_igst_paise == 0
    assert got.withheld_igst_paise == 1_800_000
    # And nothing is granted on the heads the books did not claim.
    assert got.allowed_cgst_paise == 0 and got.allowed_sgst_paise == 0
    assert got.verdicts[0].verdict == r36.MORE_THAN_2B


def test_a_negative_book_figure_is_not_capped_up():
    """A note reducing credit is fed in as negative tax. `min(book, filed)` is
    the rule — the cap withholds, it never grants — so a −₹5,000 line against a
    ₹18,000 2B row stays −₹5,000."""
    got = r36.assess([_book("b1", "DN/1", igst=-500_000)],
                     {"b1": _filed(igst=1_800_000)}, have_2b=True)
    assert got.allowed_igst_paise == -500_000
    assert got.withheld_igst_paise == 0
    assert got.verdicts[0].verdict == r36.ALLOWED


def test_the_five_reasons_are_all_different():
    """Stated on the ANSWERS rather than on the data, so moving a sentence in
    or out cannot make this vacuous."""
    reasons = set()
    for doc, two_b in (
        (_book("b1", "A", igst=100, rcm=True), None),
        (_book("b2", "B", igst=100), None),
        (_book("b3", "C", igst=100), _filed(igst=100, available="N", reason="P")),
        (_book("b4", "D", igst=100), _filed(igst=50)),
        (_book("b5", "E", igst=100, examined=False), None),
    ):
        got = r36.assess([doc], {doc.document_id: two_b} if two_b else {},
                         have_2b=True)
        reasons.add(got.verdicts[0].reason)
    assert len(reasons) == 5


# ═════════════════════════════════════════════════════════════════════════════
# WHAT THE PASS REFUSES TO DECIDE
# ═════════════════════════════════════════════════════════════════════════════

def test_no_2b_on_file_withholds_nothing_and_says_so():
    """Where nothing has been reconciled there is nothing to compare against,
    and withholding every credit because nobody uploaded a file would refuse a
    return the client is entitled to file."""
    got = r36.assess([_book("b1", "INV/1", igst=1_800_000)], None, have_2b=False)
    assert got.applied is False
    assert got.withheld_total_paise == 0
    assert got.allowed_igst_paise == 1_800_000
    assert any("No GSTR-2B has been reconciled" in n for n in got.notes)


def test_an_import_and_a_bank_charge_keep_their_aggregate_treatment():
    """Neither has a supplier invoice to key a 2B row on: an import is
    communicated in 2B's own `impg` section against a bill of entry, and a bank
    line carries no supplier GSTIN at all (BANK-24). They are passed through
    and NAMED in one sentence rather than once per row."""
    got = r36.assess([_book(None, "BOE/1", igst=5_000_000),
                      _book(None, "Bank charge", cgst=900, sgst=900)],
                     {}, have_2b=True)
    assert got.withheld_total_paise == 0
    assert got.allowed_igst_paise == 5_000_000
    assert sum("purchase bill to match" in n for n in got.notes) == 1


def test_the_import_figure_is_added_back_before_the_comparison():
    """Table 4(A)(1) is OUTSIDE the per-document pass, so the per-document
    total is short of it by construction. Comparing without adding it back
    would make the per-document answer lower every single time and silently
    withhold the whole import credit."""
    from domain.gst.gstr3b_computer import ImportOfGoods

    purchases = [_purchase("b1", "INV/1", igst=180_000)]
    got = compute_gstr3b([], purchases, [GSTR2ARecord(cgst_paise=0, sgst_paise=0, igst_paise=5_180_000)],
                         have_2b=True,
                         two_b_by_document={"b1": _filed(igst=180_000)},
                         imports_of_goods=[ImportOfGoods(igst_paise=5_000_000)])
    assert got.itc_igst == 5_180_000
    assert got.rule_36_4.withheld_total_paise == 0


def test_blocked_17_5_credit_is_subtracted_before_the_document_is_assessed():
    """§17(5) is a per-line fact the bill already carries. A document whose
    whole tax is blocked has nothing left to withhold and must not be reported
    twice."""
    purchases = [_purchase("b1", "INV/1", igst=180_000, blocked_igst=180_000)]
    got = compute_gstr3b([], purchases, [GSTR2ARecord(cgst_paise=0, sgst_paise=0, igst_paise=180_000)],
                         have_2b=True, two_b_by_document={})
    assert got.rule_36_4.withheld_total_paise == 0
    # AND IT IS NOT IN THE LIST. Without the zero-credit branch this reads as
    # `not_in_2b` and appears among the documents withheld with ₹0 against it —
    # a row the CA can do nothing about, on the one screen whose whole value is
    # that every row needs an action.
    assert got.rule_36_4.verdicts[0].verdict == r36.ALLOWED
    assert got.rule_36_4.withheld == []


# ═════════════════════════════════════════════════════════════════════════════
# A DOCUMENT NOBODY LOOKED AT IS NOT A DOCUMENT NOBODY FILED
# ═════════════════════════════════════════════════════════════════════════════

def test_a_bill_recorded_after_the_reconciliation_is_not_withheld():
    """`purchase_bill_id` is written ONCE, at upload, against the bills that
    existed then. A bill entered afterwards carries no keyed row and is
    indistinguishable — by the map alone — from one the supplier never filed.

    THE DIRECTION OF THE ERROR DECIDES IT. Withholding wrongly costs the client
    real money on a return they are about to file and is invisible; allowing
    wrongly leaves the aggregate cap doing what it did before, with a sentence
    telling the CA to re-reconcile."""
    got = r36.assess([_book("b1", "INV/late", igst=1_800_000, examined=False)],
                     {}, have_2b=True)
    v, = got.verdicts
    assert v.verdict == r36.NOT_ASSESSED
    assert got.withheld_total_paise == 0
    assert got.allowed_igst_paise == 1_800_000
    assert got.not_assessed == [v]
    assert v not in got.withheld, (
        "an unexamined bill is not a supplier's failure and must not appear "
        "in the list of documents a CA is told to chase")
    assert any("recorded after" in n for n in got.notes)


def test_the_service_names_the_bills_the_reconciliation_never_saw():
    from services.gst_return_service import _documents_the_recon_never_saw

    when = {"042026": "2026-05-14T10:00:00+00:00"}
    bills = [
        {"id": "before", "bill_date": "2026-04-03", "created_at": "2026-04-03T09:00:00+00:00"},
        {"id": "after", "bill_date": "2026-04-28", "created_at": "2026-05-20T09:00:00+00:00"},
        # No timestamp at all: the safe direction.
        {"id": "undated", "bill_date": "2026-04-10"},
        # A period with no reconciliation cannot reach here with the pass on,
        # but if it did the bill is not asserted to have been examined.
        {"id": "othermonth", "bill_date": "2026-05-02", "created_at": "2026-05-02T09:00:00+00:00"},
    ]
    assert _documents_the_recon_never_saw(bills, when) == {"after", "undated", "othermonth"}


def test_created_at_and_not_updated_at():
    """`updated_at` moves on a payment allocation, a TDS correction and a status
    change — none of which touches anything §16(2)(aa) matches on. Using it
    would report most of a busy client's register as unexamined and make the
    whole pass inert."""
    from services.gst_return_service import _documents_the_recon_never_saw

    when = {"042026": "2026-05-14T10:00:00+00:00"}
    paid_later = [{"id": "b1", "bill_date": "2026-04-03",
                   "created_at": "2026-04-03T09:00:00+00:00",
                   "updated_at": "2026-08-01T09:00:00+00:00"}]
    assert _documents_the_recon_never_saw(paid_later, when) == set()


def test_the_header_stamps_its_own_reconciled_at():
    """Migration 341's `DEFAULT now()` fires against a real Postgres and
    against nothing else, so mock mode wrote a header with no timestamp — and
    every bill then read as unexamined, making the pass inert there while it
    fires in production. That is a statutory figure differing between the two."""
    from domain.gst.gstr2b import GSTR2BFile
    from services.gst_2b_reconciliation_service import _header_row

    row = _header_row(GSTR2BFile(gstin="27AAAAA0000A1Z5",
                                      return_period="042026",
                                      generated_on="14-05-2026"), 0, 0, [])
    assert row.get("reconciled_at"), (
        "the header must carry its own timestamp, not rely on a column default "
        "only one of the two write paths reaches")


# ═════════════════════════════════════════════════════════════════════════════
# END TO END — because building the map and dropping it passed every test above
# ═════════════════════════════════════════════════════════════════════════════
#
# NEGATIVE CONTROL B, RUN AND FAILED. With `two_b_by_document=two_b_by_document`
# changed to `=None` at the one call site, everything above still passed: the
# service fetched the 2B rows, built the map, and handed the computer nothing,
# and no test could see it. That is the SIXTH time in this codebase a guard has
# matched the presence of a call rather than the use of its RESULT.
#
# So these two go through `gstr3b_from_books` — the function a CA's return is
# actually built by — and read the figure off the return.

FIRM_E2E = "FIRM-E2E"
CALLER_E2E = {"firm_id": FIRM_E2E, "id": "u-e", "auth_user_id": "auth-e",
              "email": "ca@e.test", "role": "Partner"}
GSTIN_E2E = "27AAAAA0000A1Z2"
JUNE = "062025"


def _e2e(monkeypatch):
    import routers.credit_notes as cn
    import routers.purchase_bills as pb
    import routers.purchase_credit_notes as pcn
    import routers.sales_debit_notes as sdn
    import routers.sales_invoices as si
    from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, pb, cn, sdn, pcn])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM_E2E, "gstin": GSTIN_E2E,
                        "state_code": "27", "gst_filing_frequency": None,
                        "financial_year_start": "2025-04-01"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM_E2E, "client_id": "CLI",
                        "name": "Cosmos Traders", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False})
    seed_standard_coa(db, FIRM_E2E, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM_E2E,
                                  "client_id": "CLI", "name": "Materials",
                                  "kind": "good"})
    return db


def _receive(db, no, rate_paise, bill_date):
    import routers.purchase_bills as pb
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn

    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date=bill_date, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1",
                                  description="mat", rate_paise=rate_paise,
                                  quantity=1, gst_rate_percent=18.0)],
    ), CALLER_E2E)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER_E2E)["success"] is True
    return res["data"]["id"]


def _set_created_at(db, bill_id, when):
    for row in db.rows("purchase_bills"):
        if row.get("id") == bill_id:
            row["created_at"] = when
            return
    raise AssertionError(f"no such bill: {bill_id}")


def _after_every_bill(db) -> str:
    """A reconciliation timestamp later than every bill the harness created.

    The harness stamps `created_at` at test-run time, so the fixture asserts
    the ORDER of two timestamps rather than their absolute values — which is
    what the rule is about. Deriving it from the rows keeps the test from
    quietly going stale the way a hardcoded year would.
    """
    from datetime import timedelta

    from services.gst_return_service import _as_instant

    latest = max(_as_instant(r.get("created_at"))
                 for r in db.rows("purchase_bills"))
    assert latest is not None, "the harness must stamp created_at"
    return (latest + timedelta(minutes=1)).isoformat()


def test_a_timestamp_written_the_other_way_round_is_the_same_instant():
    """`2026-05-14T10:00:00+00:00` and `...Z` are one instant, and `+` sorts
    before `Z`, so a string comparison would read the second as LATER than the
    first and silently change a bill's verdict."""
    from services.gst_return_service import _as_instant, _documents_the_recon_never_saw

    assert _as_instant("2026-05-14T10:00:00Z") == _as_instant("2026-05-14T10:00:00+00:00")
    # Naive reads as UTC rather than raising on the comparison.
    assert _as_instant("2026-05-14T10:00:00") == _as_instant("2026-05-14T10:00:00Z")
    assert _as_instant("not a timestamp") is None
    assert _as_instant(None) is None
    # And the same instant either way round is NOT "recorded after".
    assert _documents_the_recon_never_saw(
        [{"id": "b1", "bill_date": "2026-04-03",
          "created_at": "2026-05-14T10:00:00Z"}],
        {"042026": "2026-05-14T10:00:00+00:00"}) == set()


def _reconcile_at(db, period, reconciled_at, rows):
    """A reconciliation, exactly as `_persist` writes one."""
    db.seed("gstr2b_reconciliations", {
        "id": f"REC-{period}", "firm_id": FIRM_E2E, "client_id": "CLI",
        "return_period": period, "reconciled_at": reconciled_at})
    for i, row in enumerate(rows):
        db.seed("gstr2a_records", {
            "id": f"2A-{period}-{i}", "firm_id": FIRM_E2E, "client_id": "CLI",
            "return_period": period, "taxable_value_paise": 0,
            "igst_paise": 0, "cess_paise": 0, "itc_available": "Y",
            "itc_unavailable_reason_code": "", "match_status": "matched",
            **row})


def test_end_to_end_the_return_withholds_the_bill_nobody_filed(monkeypatch):
    """THE FINDING, THROUGH THE FUNCTION A RETURN IS BUILT BY.

    Two ₹2,000 bills, ₹360 tax each (₹180 CGST + ₹180 SGST). The supplier of
    the first never filed it; the second was filed for DOUBLE. Per head the
    books total ₹360 and 2B totals ₹360, so the aggregate cap sees nothing —
    and before this the return claimed the whole ₹360.
    """
    import services.gst_return_service as grs

    db = _e2e(monkeypatch)
    _receive(db, "B-ONE", 2_00000, "2025-06-10")
    filed = _receive(db, "B-TWO", 2_00000, "2025-06-11")
    _reconcile_at(db, JUNE, _after_every_bill(db), [
        {"purchase_bill_id": filed, "cgst_paise": 36000, "sgst_paise": 36000,
         "invoice_number": "B-TWO"},
    ])

    out = grs.gstr3b_from_books(db, FIRM_E2E, "CLI", JUNE, GSTIN_E2E)
    w = out["working"]["itc"]
    assert int(w["cgst_paise"]) + int(w["sgst_paise"]) == 36000 + 36000, (
        "the per-document pass must reach the return: one bill's credit is "
        "withheld and the other's stands, even though the two heads net")

    per_doc = out["working"]["rule_36_4"]["per_document"]
    assert per_doc["applied"] is True
    assert [(d["label"], d["verdict"]) for d in per_doc["withheld"]] == [
        ("B-ONE", "not_in_2b")]
    assert per_doc["withheld"][0]["supplier"] == "Cosmos Traders", (
        "a list of document ids a CA cannot read is not an answer")
    assert per_doc["withheld_total_paise"] == 36000


def test_end_to_end_a_bill_entered_after_the_reconciliation_keeps_its_credit(monkeypatch):
    """The other half, and the one that costs money if it is wrong. The 2B was
    reconciled on 14 July and the bill was entered on the 20th, so nothing
    examined it — withholding its credit would refuse a claim the client is
    entitled to, on a return they are about to file."""
    import services.gst_return_service as grs

    db = _e2e(monkeypatch)
    late = _receive(db, "B-LATE", 2_00000, "2025-06-28")
    # The reconciliation ran on 14 July; the bill was entered on the 20th.
    _set_created_at(db, late, "2025-07-20T09:00:00+00:00")
    _reconcile_at(db, JUNE, "2025-07-14T10:00:00+00:00", [])

    out = grs.gstr3b_from_books(db, FIRM_E2E, "CLI", JUNE, GSTIN_E2E)
    per_doc = out["working"]["rule_36_4"]["per_document"]
    assert per_doc["withheld"] == []
    assert [d["label"] for d in per_doc["not_assessed"]] == ["B-LATE"]
    assert any("recorded after" in n for n in per_doc["notes"])


def test_end_to_end_a_document_2b_refuses_reads_as_refused(monkeypatch):
    """NEGATIVE CONTROL C, RUN AND FAILED. Putting `.neq("itc_available", "N")`
    back into `_gstr2a_for_periods` — which looks like a tidy-up towards the
    query the aggregate cap wants — broke nothing: the ceiling was still right,
    the withheld TOTAL was still right, and the only thing that changed was the
    SENTENCE, from "GSTR-2B marks this ITC-unavailable" to "no GSTR-2B document
    matched this bill".

    That sentence is the answer. One says read the document; the other says
    phone the supplier, who has done nothing wrong and has the filing to prove
    it. The figures cannot distinguish them, so a test on the figures cannot
    either.
    """
    import services.gst_return_service as grs

    db = _e2e(monkeypatch)
    blocked = _receive(db, "B-BLOCKED", 2_00000, "2025-06-12")
    _reconcile_at(db, JUNE, _after_every_bill(db), [
        {"purchase_bill_id": blocked, "cgst_paise": 18000, "sgst_paise": 18000,
         "invoice_number": "B-BLOCKED", "itc_available": "N",
         "itc_unavailable_reason_code": "P"},
    ])

    out = grs.gstr3b_from_books(db, FIRM_E2E, "CLI", JUNE, GSTIN_E2E)
    per_doc = out["working"]["rule_36_4"]["per_document"]
    withheld, = per_doc["withheld"]
    assert withheld["verdict"] == "blocked_by_2b", (
        "a document GSTR-2B carries and REFUSES must not read as one GSTR-2B "
        "does not carry — the CA's next action is opposite")
    assert "place of supply" in withheld["reason"]
    assert withheld["withheld_total_paise"] == 36000
    # And the ceiling still excludes it: a refused document must not raise the
    # aggregate cap by the very credit §16(2)(aa) withholds.
    assert out["working"]["rule_36_4"]["gstr2a_cgst_paise"] == 0
