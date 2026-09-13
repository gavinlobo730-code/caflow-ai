"""PUR-23 ≡ TDS-32 — a purchase return after the tax was already withheld.

A ₹5,00,000 §194J bill is booked, ₹50,000 is withheld and deposited, and the
vendor then issues a credit note for ₹2,00,000. Nothing revisited the register:
`routers/debit_notes.py` and `routers/purchase_credit_notes.py` contained no
occurrence of "tds" in any case, so the 26Q deductee row kept reporting
₹5,00,000 credited to that PAN and the vendor's 26AS showed income they did not
earn.

The FIGURES still do not move, and that is the decision this file pins: §194's
charge on the aggregate credited and §199's credit to the deductee for tax
already paid over point in opposite directions, and which applies turns on when
the challan went — a fact the books do not hold. What must not happen again is
the SILENCE.
"""
from datetime import date

import pytest

from domain.tds.purchase_return import (
    GAP_CREDIT_MOVED_AFTER_DEDUCTION, credit_moved_after_deduction,
)
from domain.tds.residency import GAP_MESSAGES, describe_gaps


# ── the rule ──────────────────────────────────────────────────────────────────

def _moved(**kw):
    base = dict(bill_no="BILL-7", section="194J",
                credited_paise=5_00_000_00, tds_paise=50_000_00,
                returned_taxable_paise=2_00_000_00)
    base.update(kw)
    return credit_moved_after_deduction(**base)


def test_a_return_against_a_bill_that_withheld_is_reported():
    m = _moved()
    assert m is not None
    assert m.net_credited_paise == 3_00_000_00
    assert m.code == GAP_CREDIT_MOVED_AFTER_DEDUCTION


def test_the_sentence_carries_both_figures_and_the_bill():
    m = _moved()
    assert "BILL-7" in m.sentence
    assert "₹5,00,000" in m.sentence, "the credited figure the deductee row reports"
    assert "₹2,00,000" in m.sentence, "what has been returned"
    assert "₹3,00,000" in m.sentence, "what actually stands credited"
    assert "₹50,000" in m.sentence, "the tax already withheld"
    assert "section 194J" in m.sentence


def test_the_sentence_names_both_lawful_answers_and_chooses_neither():
    m = _moved()
    assert "199" in m.sentence, "tax already paid over is the deductee's"
    assert "aggregate" in m.sentence, "the section charges the aggregate credited"
    assert "excess deposit" in m.sentence
    assert "adjusts either figure" in m.sentence, (
        "the whole point is that the software states the divergence and moves "
        "no number — see domain/tds/purchase_return")


def test_a_bill_that_withheld_nothing_has_no_deductee_row_to_be_wrong():
    assert _moved(tds_paise=0) is None


def test_a_bill_with_no_note_against_it_is_not_reported():
    assert _moved(returned_taxable_paise=0) is None


def test_a_supplier_undercharge_note_runs_the_other_way():
    """§34(3) INCREASES what was credited, so the aggregate the section charges
    on has grown and the deduction may be SHORT — the §201(1A) direction, and
    the expensive one. It is reported for that reason, not despite it."""
    m = _moved(returned_taxable_paise=0, increased_taxable_paise=25_000_00)
    assert m is not None
    assert m.net_credited_paise == 5_25_000_00
    assert "supplier credit note" in m.sentence
    assert "§34(3)" in m.sentence


def test_both_kinds_against_one_bill_net_and_both_are_named():
    m = _moved(returned_taxable_paise=1_00_000_00, increased_taxable_paise=30_000_00)
    assert m.net_credited_paise == 4_30_000_00
    assert "returned on a purchase return" in m.sentence
    assert "supplier credit note" in m.sentence


def test_a_bill_with_no_number_still_produces_a_readable_sentence():
    m = _moved(bill_no=None)
    assert m.sentence.startswith("Bill this bill credited")


def test_a_bill_with_no_section_does_not_invent_one():
    m = _moved(section=None)
    # Only the WITHHELD clause names the section. "under section 199" is part
    # of the fixed explanation and is there whatever the bill says — the first
    # draft of this test matched the bare phrase and passed on that instead.
    head = m.sentence.split(", and ")[0]
    assert head.endswith("withheld"), head
    assert "section" not in head


def test_the_figures_are_indian_grouped_and_never_western():
    """`f"{n:,}"` gives 500,000, which no Indian document uses — and the
    browser formats the same amount with Intl.NumberFormat("en-IN"), so a
    hand-rolled copy here would make the screen and the sentence disagree."""
    m = _moved(credited_paise=1_23_45_678_00, returned_taxable_paise=1_00_00_000_00)
    assert "₹1,23,45,678" in m.sentence
    assert "12,345,678" not in m.sentence


def test_the_gap_code_carries_a_ca_facing_message():
    assert GAP_CREDIT_MOVED_AFTER_DEDUCTION in GAP_MESSAGES
    msg = GAP_MESSAGES[GAP_CREDIT_MOVED_AFTER_DEDUCTION]
    assert "s.199" in msg and "aggregate" in msg
    assert describe_gaps([GAP_CREDIT_MOVED_AFTER_DEDUCTION])[0]["message"] == msg


# ── the register ──────────────────────────────────────────────────────────────

class _RegisterDB:
    """Enough of Supabase for sync_for_bill plus the two note tables."""

    def __init__(self, debit_notes=(), credit_notes=()):
        self.debit_notes = list(debit_notes)
        self.credit_notes = list(credit_notes)
        self.upserts: list[dict] = []
        self.reads: list[str] = []
        self._t = None

    def table(self, name):
        self._t = name
        self.reads.append(name)
        return self

    def select(self, *a, **k): return self
    def eq(self, *a): return self
    def in_(self, *a): return self
    def limit(self, *a): return self
    def order(self, *a, **k): return self
    def gt(self, *a): return self
    def delete(self): return self

    def upsert(self, payload, **k):
        self.upserts.append(payload)
        return self

    def execute(self):
        if self._t == "debit_notes":
            return type("R", (), {"data": list(self.debit_notes)})()
        if self._t == "purchase_credit_notes":
            return type("R", (), {"data": list(self.credit_notes)})()
        return type("R", (), {"data": []})()


def _bill(**kw):
    base = dict(id="b1", vendor_id="v1", bill_no="BILL-7", bill_date="2025-10-25",
                status="received", taxable_amount_paise=5_00_000_00,
                tds_paise=50_000_00, tds_rate_bps=1000, tds_section="194J",
                debited_paise=0, credit_note_paise=0)
    base.update(kw)
    return base


VENDOR = {"id": "v1", "name": "Pinnacle Engineering", "pan": "AAGCP7788R",
          "residential_status": "resident"}


def _sync(db, bill):
    from services import tds_register_service
    return tds_register_service.sync_for_bill(db, "f1", "c1", bill, VENDOR)


def test_the_register_names_the_return_and_changes_no_figure():
    db = _RegisterDB(debit_notes=[
        {"purchase_bill_id": "b1", "taxable_amount_paise": 2_00_000_00,
         "status": "issued", "deleted_at": None}])
    out = _sync(db, _bill(debited_paise=2_36_000_00))
    assert GAP_CREDIT_MOVED_AFTER_DEDUCTION in out["statutory_gaps"]
    row = db.upserts[-1]
    assert row["payment_amount_paise"] == 5_00_000_00, (
        "the deductee row still reports what was credited — the note does not "
        "rewrite a figure that may already be on a filed return")
    assert row["tds_paise"] == 50_000_00


def test_a_bill_with_no_notes_pays_for_no_extra_read():
    """The bill's own rollups are the CHEAP TEST. A freshly received bill has
    both at zero, so the ordinary path never touches the note tables."""
    db = _RegisterDB()
    _sync(db, _bill())
    assert "debit_notes" not in db.reads
    assert "purchase_credit_notes" not in db.reads


def test_a_noted_bill_does_read_the_notes():
    db = _RegisterDB()
    _sync(db, _bill(debited_paise=1_00))
    assert "debit_notes" in db.reads and "purchase_credit_notes" in db.reads


def test_a_draft_note_has_not_reversed_anything():
    db = _RegisterDB(debit_notes=[
        {"purchase_bill_id": "b1", "taxable_amount_paise": 2_00_000_00,
         "status": "draft", "deleted_at": None}])
    out = _sync(db, _bill(debited_paise=2_36_000_00))
    assert GAP_CREDIT_MOVED_AFTER_DEDUCTION not in (out.get("statutory_gaps") or [])


def test_a_deleted_note_has_not_reversed_anything_either():
    db = _RegisterDB(debit_notes=[
        {"purchase_bill_id": "b1", "taxable_amount_paise": 2_00_000_00,
         "status": "issued", "deleted_at": "2025-11-01T00:00:00Z"}])
    out = _sync(db, _bill(debited_paise=2_36_000_00))
    assert GAP_CREDIT_MOVED_AFTER_DEDUCTION not in (out.get("statutory_gaps") or [])


def test_the_note_tables_are_measured_on_taxable_value_not_the_total():
    """`payment_amount_paise` excludes GST (CBDT Circular 23/2017). Measuring
    the movement against a note TOTAL would overstate it by the tax on it —
    which is why the bill's `debited_paise` rollup is only the trigger."""
    from services.tds_register_service import notes_against_bill
    db = _RegisterDB(debit_notes=[
        {"purchase_bill_id": "b1", "taxable_amount_paise": 2_00_000_00,
         "total_paise": 2_36_000_00, "status": "issued", "deleted_at": None}])
    returned, increased = notes_against_bill(db, "f1", _bill(debited_paise=2_36_000_00))
    assert returned == 2_00_000_00 and increased == 0


def test_a_note_read_that_fails_degrades_to_no_notes_seen():
    """sync_for_bill's whole contract is that it never raises into a posting
    path. A gap that cannot be measured is better reported as absent than as
    a bill that will not post."""
    from services.tds_register_service import notes_against_bill

    class _Boom(_RegisterDB):
        def execute(self):
            raise RuntimeError("PostgREST is unhappy")

    assert notes_against_bill(_Boom(), "f1", _bill(debited_paise=1_00)) == (0, 0)


# ── the quarterly return ──────────────────────────────────────────────────────

class _BooksDB:
    def __init__(self, bills, vendors, debit_notes=(), credit_notes=()):
        self._bills, self._vendors = list(bills), list(vendors)
        self._dn, self._cn = list(debit_notes), list(credit_notes)
        self._t = None
        self._filters: dict = {}
        # Which tables were queried with a DATE bound. A date-ranged note read
        # is the mutation the by-id test could not otherwise see: this double
        # ignores .lte(), so without recording it the filter would be added and
        # every assertion would still pass.
        self.date_bounded: set[str] = set()

    def table(self, name):
        self._t = name
        self._filters = {}
        return self

    def select(self, *a, **k): return self
    def or_(self, *a): return self
    def limit(self, *a): return self
    def order(self, *a, **k): return self
    def gt(self, *a): return self

    def gte(self, *a):
        self.date_bounded.add(self._t)
        return self

    def lte(self, *a):
        self.date_bounded.add(self._t)
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._filters[col] = list(vals)
        return self

    def execute(self):
        if self._t == "purchase_bills":
            return type("R", (), {"data": list(self._bills)})()
        if self._t == "vendors":
            wanted = self._filters.get("id") or []
            return type("R", (), {"data": [v for v in self._vendors if v["id"] in wanted]})()
        if self._t == "debit_notes":
            return type("R", (), {"data": list(self._dn)})()
        if self._t == "purchase_credit_notes":
            return type("R", (), {"data": list(self._cn)})()
        return type("R", (), {"data": []})()


def _26q(bills, vendors, debit_notes=(), credit_notes=(), db_out=None):
    from services.tds_return_service import tds_26q_from_books
    db = _BooksDB(bills, vendors, debit_notes, credit_notes)
    if db_out is not None:
        db_out.append(db)
    return tds_26q_from_books(
        db, "f1", "c1", "2025-26", "Q3",
        "MUMP12345A", "Client Pvt Ltd", "AAACC1111C", "Mumbai")


def test_the_quarter_names_a_bill_whose_credit_a_note_has_moved():
    out = _26q([_bill()], [VENDOR],
               debit_notes=[{"purchase_bill_id": "b1",
                             "taxable_amount_paise": 2_00_000_00,
                             "status": "issued", "deleted_at": None}])
    named = [g for g in out["statutory_gaps"] if "BILL-7" in g]
    assert len(named) == 1, "the CA assembling the quarter must be told"
    assert "₹3,00,000" in named[0]
    # And the return itself is unchanged — the deductee row is what was filed.
    assert out["deductees"][0]["payment_amount_paise"] == 5_00_000_00


def test_a_quarter_with_no_notes_carries_no_such_gap():
    out = _26q([_bill()], [VENDOR])
    assert not [g for g in out["statutory_gaps"] if "purchase return" in g]


def test_a_note_raised_in_a_later_quarter_is_still_found():
    """The read is by BILL ID, not by date. A note raised in Q4 against a Q3
    bill is the case that matters most, and a date-ranged query is exactly the
    one that misses it."""
    seen: list = []
    out = _26q([_bill()], [VENDOR],
               debit_notes=[{"purchase_bill_id": "b1",
                             "taxable_amount_paise": 50_000_00,
                             "debit_note_date": "2026-02-14",
                             "status": "issued", "deleted_at": None}],
               db_out=seen)
    assert [g for g in out["statutory_gaps"] if "BILL-7" in g]
    # And asserted at the QUERY, because this double does not apply a date
    # bound — so the row above would come back regardless and the assertion
    # over it would pass on a query that misses the note in production.
    assert "debit_notes" not in seen[0].date_bounded
    assert "purchase_credit_notes" not in seen[0].date_bounded
    assert "purchase_bills" in seen[0].date_bounded, (
        "the BILLS are quarter-bounded and must stay so — this is what proves "
        "the assertion above is measuring something")


def test_a_note_against_some_other_bill_is_not_attributed_to_this_one():
    out = _26q([_bill()], [VENDOR],
               debit_notes=[{"purchase_bill_id": "SOMEONE-ELSE",
                             "taxable_amount_paise": 50_000_00,
                             "status": "issued", "deleted_at": None}])
    assert not [g for g in out["statutory_gaps"] if "BILL-7" in g]


# ── the routers, end to end ───────────────────────────────────────────────────
#
# The register can be right and the CA still never told, because nothing called
# it. `sync_for_bill`'s own docstring says it runs "on every transition rather
# than only on create"; issuing a note was the transition it was never called
# on, and these hold that closed.

E2E_FIRM = "FIRM-PR23"
E2E_CALLER = {"firm_id": E2E_FIRM, "id": "u1", "auth_user_id": "u1",
              "email": "ca@f.test", "role": "Partner"}


def _e2e(monkeypatch):
    import routers.vendors as ve
    import routers.purchase_bills as pb
    import routers.debit_notes as dn
    import routers.purchase_credit_notes as pcn
    from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ve, pb, dn, pcn])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("firms", {"id": E2E_FIRM})
    db.seed("clients", {"id": "CLI", "firm_id": E2E_FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, E2E_FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": E2E_FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    db.seed("vendors", {"id": "VEND1", "firm_id": E2E_FIRM, "client_id": "CLI",
                        "name": "Pinnacle Engineering", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "pan": "AAGCP7788R",
                        "residential_status": "resident",
                        "tds_applicable": True, "tds_section": "194J",
                        "opening_balance_paise": 0})
    return ve, pb, dn, pcn, db


def _e2e_bill(pb, rate_paise=5_00_000_00, bill_no="BILL-E2E"):
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-10-25", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc",
                                  rate_paise=rate_paise, quantity=1,
                                  gst_rate_percent=0.0)]), E2E_CALLER)["data"]
    assert pb.receive_purchase_bill(bill["id"], E2E_CALLER)["success"] is True
    return bill


def test_issuing_a_purchase_return_tells_the_ca_the_deductee_row_is_stale(monkeypatch):
    from models.invoices import InvoiceLineIn
    ve, pb, dn, pcn, db = _e2e(monkeypatch)
    bill = _e2e_bill(pb)
    assert int(bill.get("tds_paise") or 0) > 0, "the fixture must actually withhold"

    note = dn.create_debit_note(dn.DebitNoteIn(
        client_id="CLI", vendor_id="VEND1", purchase_bill_id=bill["id"],
        debit_note_date="2025-11-10", reason="Return",
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=2_00_000_00,
                             gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), E2E_CALLER)["data"]
    out = dn.issue_debit_note(note["id"], E2E_CALLER)
    assert out["success"] is True
    assert GAP_CREDIT_MOVED_AFTER_DEDUCTION in (out["data"].get("statutory_gaps") or []), (
        "the note was issued and nobody was told the 26Q deductee row is now "
        "reporting a credit that has been partly reversed")
    detail = [g for g in (out["data"].get("gap_details") or [])
              if g["code"] == GAP_CREDIT_MOVED_AFTER_DEDUCTION]
    assert detail and len(detail[0]["message"]) > 40


def test_issuing_a_supplier_credit_note_does_the_same(monkeypatch):
    from models.invoices import InvoiceLineIn
    ve, pb, dn, pcn, db = _e2e(monkeypatch)
    bill = _e2e_bill(pb, bill_no="BILL-E2E-CN")

    note = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
        client_id="CLI", vendor_id="VEND1", purchase_bill_id=bill["id"],
        credit_note_date="2025-11-10", reason="Undercharge",
        lines=[InvoiceLineIn(description="extra", quantity=1, rate_paise=25_000_00,
                             gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), E2E_CALLER)["data"]
    out = pcn.issue_purchase_credit_note(note["id"], E2E_CALLER)
    assert out["success"] is True
    assert GAP_CREDIT_MOVED_AFTER_DEDUCTION in (out["data"].get("statutory_gaps") or [])


def test_the_resync_never_fails_the_note(monkeypatch):
    """A note that posted correctly must not be rolled back because a register
    row could not be re-read — the same contract sync_for_bill itself has."""
    from models.invoices import InvoiceLineIn
    import services.tds_register_service as reg
    ve, pb, dn, pcn, db = _e2e(monkeypatch)
    bill = _e2e_bill(pb, bill_no="BILL-E2E-BOOM")
    note = dn.create_debit_note(dn.DebitNoteIn(
        client_id="CLI", vendor_id="VEND1", purchase_bill_id=bill["id"],
        debit_note_date="2025-11-10", reason="Return",
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=1_00_000_00,
                             gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), E2E_CALLER)["data"]

    def _boom(*a, **k):
        raise RuntimeError("register unavailable")
    monkeypatch.setattr(reg, "sync_for_bill", _boom)

    out = dn.issue_debit_note(note["id"], E2E_CALLER)
    assert out["success"] is True
    assert (out["data"].get("status") or "") == "issued"
