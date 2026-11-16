"""
A deduction typed on the /tds screen is NAMED on the 26Q built from the books, and a payee with no usable PAN is never pooled with another (POST-A-078, first part).

WHAT WAS WRONG
    1. `tds_26q_from_books` reads posted purchase bills and withholding advances. A deduction a CA types on the TDS screen is a `tds_deductions` row no bill wrote,
       and it never reached the statement, with no word about it: the statement read as a complete one while the register held tax withheld for the same quarter.
    2. `manual_register.prior_manual_aggregate` keys the year's earlier payments on the PAN, and it treated the placeholders a deductee without a PAN is filed
       under (`PANNOTAVBL`, `PANAPPLIED`) and any typed text as a PAN. Every payee typed under one placeholder was pooled as one person, so a stranger's
       payments pushed another over a threshold and the tax already withheld from one was credited to the other.
    3. A payee with NO PAN returned a year's total of nothing because nothing was looked for, and the screen worded that nil as "the year's total for this payee
       has not reached it either".

WHAT IS HELD HERE
    A PAN is a key only if it is one; the answer says whether the year was added up against the section's yearly limit (`aggregate_tested`); and the statement NAMES the
    typed deductions it carries (`typed_on_statement`: count, payment, tax, each row) and the ones it leaves out (`excluded_typed`: rows recorded for another
    statement), and the keying sheet names both.

SINCE POST-A-078'S LAST PART the statement CARRIES the typed deductions as deductee rows (they were named and never added until then); how they are carried is held in
`test_a_typed_deduction_is_a_deductee_row_on_the_statement_built_from_the_books.py`. What is still not done, and is still ledger line POST-A-078: a payee with no supplier
and no usable PAN is keyed by nothing, and a shape-valid dummy PAN is still a key.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from domain.tds import manual_register
from domain.tds.manual_register import (
    GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN, GAP_MESSAGES, GAP_NO_SUPPLIER, usable_pan_key,
)
from tests.e2e_harness import FakeDB

FIRM = "F1"
CLIENT = "C1"
EXEC = {"id": "u2", "firm_id": FIRM, "role": "Executive", "email": "e@f1.test", "auth_user_id": "auth-exec"}
MANAGER = {"id": "u1", "firm_id": FIRM, "role": "Manager", "email": "m@f1.test", "auth_user_id": "auth-mgr"}
PAN_COMPANY = "AAACA1234A"
#: A day in FY 2025-26, the latest year the registry's rates are confirmed for; 2026-06-15 is FY 2026-27 (not confirmed) and 2024-06-15 is FY 2024-25 (not held).
CONFIRMED_DAY = "2025-06-15"
UNCONFIRMED_DAY = "2026-06-15"
NOT_HELD_DAY = "2024-06-15"


# ── a PAN is a key only if it is one ─────────────────────────────────────────

@pytest.mark.parametrize("typed", [
    None, "", "   ", "PANNOTAVBL", "pannotavbl", " PANAPPLIED ", "PANAPPLIED",
    "NOTAPAN", "ABC", "AAACA1234", "AAACA12345", "AAACA1234AA", "1234567890", "AAAAA99999", "AAACA1234!",
])
def test_what_is_not_a_pan_is_not_a_key(typed):
    assert usable_pan_key(typed) is None


@pytest.mark.parametrize("typed, key", [
    ("AAACA1234A", "AAACA1234A"), (" aaaca1234a ", "AAACA1234A"), ("AAGCP7788R", "AAGCP7788R"),
])
def test_a_real_pan_is_the_key_in_capitals(typed, key):
    assert usable_pan_key(typed) == key


class _SpyDB:
    """Records that the register was (or was not) read."""

    def __init__(self):
        self.tables: list[str] = []

    def table(self, name):
        self.tables.append(name)
        raise AssertionError(f"the register must not be read for a payee with no usable PAN (asked for {name})")


@pytest.mark.parametrize("typed", ["PANNOTAVBL", "PANAPPLIED", "NOTAPAN", "", None])
def test_the_year_is_not_looked_up_for_a_payee_with_no_usable_pan(typed):
    from datetime import date
    spy = _SpyDB()
    got = manual_register.prior_manual_aggregate(
        spy, firm_id=FIRM, client_id=CLIENT, section="194H", deductee_pan=typed, on=date(2026, 6, 15))
    assert got == (0, 0)
    assert spy.tables == []


# ── through the door ─────────────────────────────────────────────────────────

@pytest.fixture
def app_db(monkeypatch):
    import routers.tds_workspace as mod
    db = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: None)   # the privileged reader is this same fake (POST-A-409's document read)
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    app = FastAPI()
    app.include_router(mod.router)
    return app, db


def _post(app, **over):
    body = {"client_id": CLIENT, "deductee_name": "Acme Services", "deductee_pan": PAN_COMPANY, "section": "194H",
            "payment_amount_paise": 15_000_00, "transaction_date": CONFIRMED_DAY}
    body.update(over)
    app.dependency_overrides[get_current_user] = lambda: EXEC
    return TestClient(app, raise_server_exceptions=False).post("/api/tds-workspace/deductions", json=body)


@pytest.mark.parametrize("placeholder", ["PANNOTAVBL", "PANAPPLIED"])
def test_two_payees_typed_under_a_placeholder_are_not_one_person(app_db, placeholder):
    """Two Rs.15,000 commissions to two different strangers, both filed under the placeholder. Pooled they would be Rs.30,000, over s.194H's aggregate, and the
    second would be charged on a total that belongs to nobody."""
    app, _ = app_db
    first = _post(app, deductee_pan=placeholder, deductee_name="Stranger One").json()["data"]
    second = _post(app, deductee_pan=placeholder, deductee_name="Stranger Two").json()["data"]
    assert first["explain"]["fy_prior_taxable_paise"] == 0
    assert second["explain"]["fy_prior_taxable_paise"] == 0, "a placeholder is not a payee"
    assert second["explain"]["fy_prior_tds_paise"] == 0
    assert second["tds_paise"] == 0, "Rs.15,000 is under s.194H's own limit and no other payee's money counts toward it"


def test_the_same_real_pan_still_pools_its_own_payments(app_db):
    """The change must not undo the aggregate for a payee who has one: Rs.15,000 twice to one PAN is Rs.30,000 for that payee."""
    app, _ = app_db
    _post(app, deductee_pan=PAN_COMPANY)
    second = _post(app, deductee_pan=PAN_COMPANY).json()["data"]
    assert second["explain"]["fy_prior_taxable_paise"] == 15_000_00
    assert second["tds_paise"] > 0


@pytest.mark.parametrize("pan", [None, "PANNOTAVBL", "PANAPPLIED", "NOTAPAN"])
def test_the_answer_says_the_year_was_not_looked_at(app_db, pan):
    app, _ = app_db
    d = _post(app, deductee_pan=pan).json()["data"]["explain"]
    assert d["aggregate_tested"] is False
    assert GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN in d["gaps"]
    assert GAP_MESSAGES[GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN] in d["gap_messages"]
    # Not both: "its year is added up with the other deductions typed for this PAN" is false where nothing was added up (POST-A-078).
    assert GAP_NO_SUPPLIER not in d["gaps"], "a payee with no usable PAN was told its year was added up by its PAN"


def test_the_answer_for_a_real_pan_says_the_year_was_looked_at(app_db):
    app, _ = app_db
    d = _post(app, deductee_pan=PAN_COMPANY).json()["data"]["explain"]
    assert d["aggregate_tested"] is True
    assert GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN not in d["gaps"]


def test_the_preview_and_the_correction_say_it_too(app_db):
    """Three doors resolve a typed row (save, preview, correction) and all three answer through `_resolve_manual_deduction`."""
    app, db = app_db
    app.dependency_overrides[get_current_user] = lambda: EXEC
    client = TestClient(app, raise_server_exceptions=False)
    body = {"client_id": CLIENT, "deductee_name": "Acme Services", "deductee_pan": "PANNOTAVBL", "section": "194H",
            "payment_amount_paise": 15_000_00, "transaction_date": CONFIRMED_DAY}
    preview = client.post("/api/tds-workspace/deductions/preview", json=body).json()["data"]["explain"]
    assert preview["aggregate_tested"] is False
    saved = client.post("/api/tds-workspace/deductions", json=body).json()["data"]
    fixed = client.patch(f"/api/tds-workspace/deductions/{saved['id']}", json={"deductee_pan": PAN_COMPANY}).json()["data"]["explain"]
    assert fixed["aggregate_tested"] is True
    again = client.patch(f"/api/tds-workspace/deductions/{saved['id']}", json={"deductee_pan": "PANAPPLIED"}).json()["data"]["explain"]
    assert again["aggregate_tested"] is False


# ── the statement names what the register holds and it left out ──────────────

def _typed(rid, *, day="2025-10-12", section="194J", pan="AAACA1234A", name="Acme Services",
           payment=1_00_000_00, tds=10_000_00, bill=None, client=CLIENT, firm=FIRM):
    return {"id": rid, "firm_id": firm, "client_id": client, "deductee_name": name, "deductee_pan": pan, "section": section,
            "transaction_date": day, "payment_amount_paise": payment, "tds_paise": tds, "purchase_bill_id": bill}


def _books(db, *, bill=True, fy="2025-26", quarter="Q3"):
    from services.tds_return_service import tds_26q_from_books
    if bill:
        db.seed("vendors", {"id": "v1", "firm_id": FIRM, "name": "Pinnacle Engineering", "pan": "AAGCP7788R",
                            "residential_status": "resident"})
        db.seed("purchase_bills", {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1", "bill_no": "BILL-1",
                                   "bill_date": "2025-10-25", "status": "received", "taxable_amount_paise": 18_000_00,
                                   "tds_paise": 360_00, "tds_rate_bps": 200, "tds_section": "194C", "journal_entry_id": None})
    return tds_26q_from_books(db, FIRM, CLIENT, fy, quarter, "MUMP12345A", "Client Pvt Ltd", "AAACC1111C", "Mumbai")


def test_a_statement_with_no_typed_deduction_says_none():
    out = _books(FakeDB())
    for key in ("typed_on_statement", "excluded_typed"):
        typed = out[key]
        assert typed["count"] == 0 and typed["tds_paise"] == 0 and typed["payment_paise"] == 0 and typed["deductions"] == [], key


def test_the_quarters_typed_deductions_are_counted_summed_and_listed_in_order():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t2", day="2025-12-05", section="194H", payment=40_000_00, tds=80_000, name="Late Co"))
    db.seed("tds_deductions", _typed("t1"))
    typed = _books(db)["typed_on_statement"]
    assert typed["count"] == 2
    assert typed["payment_paise"] == 1_00_000_00 + 40_000_00
    assert typed["tds_paise"] == 10_000_00 + 80_000
    assert [d["id"] for d in typed["deductions"]] == ["t1", "t2"], "oldest first, by date then id"
    assert typed["deductions"][0] == {
        "id": "t1", "deductee_name": "Acme Services", "deductee_pan": "AAACA1234A", "section": "194J", "section_1961": "194J",
        "transaction_date": "2025-10-12", "payment_amount_paise": 1_00_000_00, "tds_paise": 10_000_00}
    from services.tds_return_service import TYPED_ON_STATEMENT_REASON
    assert typed["reason"].startswith(TYPED_ON_STATEMENT_REASON), "the note says what is different about these rows"
    assert "outside it" in typed["reason"]


def test_a_2025_act_statement_labels_a_typed_row_by_its_own_act_and_keeps_the_routing_key_beside_it():
    """TDS-17: the label goes out as `section` and the stored code beside it as `section_1961`, translated at the emission and never in the store. A code the
    period's Act has no entry for keeps its own code and is named once in the statement's gaps."""
    db = FakeDB()
    db.seed("tds_deductions", _typed("a", day="2026-05-12", section="194J"))
    db.seed("tds_deductions", _typed("b", day="2026-05-20", section="193"))
    out = _books(db, bill=False, fy="2026-27", quarter="Q1")
    rows = {d["id"]: d for d in out["typed_on_statement"]["deductions"]}
    assert (rows["a"]["section"], rows["a"]["section_1961"]) == ("393(1)", "194J")
    assert (rows["b"]["section"], rows["b"]["section_1961"]) == ("193", "193")
    assert len([g for g in out["statutory_gaps"] if "recorded for 193" in g]) == 1
    assert not [g for g in out["statutory_gaps"] if "recorded for 194J" in g]


def test_a_section_missing_from_both_the_deductees_and_the_typed_rows_is_named_once():
    """One call labels both lists, so one gap sentence covers a section wherever it appears."""
    db = FakeDB()
    db.seed("tds_deductions", _typed("a", day="2026-05-12", section="193"))
    db.seed("vendors", {"id": "v9", "firm_id": FIRM, "name": "Odd Co", "pan": "AAGCP7788R", "residential_status": "resident"})
    db.seed("purchase_bills", {"id": "b9", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v9", "bill_no": "B-9", "bill_date": "2026-05-15",
                               "status": "received", "taxable_amount_paise": 18_000_00, "tds_paise": 360_00, "tds_rate_bps": 200,
                               "tds_section": "193", "journal_entry_id": None})
    out = _books(db, bill=False, fy="2026-27", quarter="Q1")
    assert out["deductee_count"] == 2 and {d["section_1961"] for d in out["deductees"]} == {"193"}
    assert len([g for g in out["statutory_gaps"] if "recorded for 193" in g]) == 1


def test_the_listing_is_in_date_order_when_the_ids_run_the_other_way():
    """The read is paged in id order; the list a person reads is in the order the deductions happened, with the id only to break a tie."""
    db = FakeDB()
    db.seed("tds_deductions", _typed("a", day="2025-12-05"))
    db.seed("tds_deductions", _typed("b", day="2025-10-12"))
    db.seed("tds_deductions", _typed("c", day="2025-10-12"))
    assert [d["id"] for d in _books(db)["typed_on_statement"]["deductions"]] == ["b", "c", "a"]


def test_a_typed_deduction_is_on_the_statement_and_outside_the_tie_out():
    """The statement's totals now hold the typed tax (it is a deduction the deductor made), and the tie-out with the TDS Payable account compares the documents' tax
    alone, because no journal stands behind a typed deduction: the typed tax is reported beside it."""
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1"))
    out = _books(db)
    assert out["typed_on_statement"]["count"] == 1 and out["excluded_typed"]["count"] == 0
    assert out["deductee_count"] == 2
    assert sorted(d["deductee_name"] for d in out["deductees"]) == ["Acme Services", "Pinnacle Engineering"]
    assert out["total_tds_deducted_paise"] == 360_00 + 10_000_00
    assert out["total_payment_paise"] == 18_000_00 + 1_00_000_00
    assert out["reconciliation"]["books_paise"] == 360_00, "the documents' tax, which is what a journal holds"
    assert out["reconciliation"]["typed_paise"] == 10_000_00


def test_a_statement_with_only_typed_deductions_carries_them_and_ties_out_at_nothing():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1"))
    out = _books(db, bill=False)
    assert out["deductee_count"] == 1 and out["total_tds_deducted_paise"] == 10_000_00
    assert out["typed_on_statement"]["count"] == 1 and out["typed_on_statement"]["tds_paise"] == 10_000_00
    assert out["reconciliation"]["books_paise"] == 0 and out["reconciliation"]["ledger_paise"] == 0
    assert out["reconciliation"]["typed_paise"] == 10_000_00


@pytest.mark.parametrize("label, row", [
    ("a row a purchase bill wrote", _typed("x", bill="b1")),
    ("a salary row (a typed section 192 is refused at the door and belongs to 24Q)", _typed("x", section="192")),
    ("the day before the quarter", _typed("x", day="2025-09-30")),
    ("the day after the quarter", _typed("x", day="2026-01-01")),
    ("another client's row", _typed("x", client="C2")),
    ("another firm's row", _typed("x", firm="F2")),
])
def test_what_the_quarter_does_not_hold_is_not_counted(label, row):
    db = FakeDB()
    db.seed("tds_deductions", row)
    out = _books(db)
    assert out["typed_on_statement"]["count"] == 0 and out["excluded_typed"]["count"] == 0, label


def test_the_first_and_last_day_of_the_quarter_are_in():
    db = FakeDB()
    db.seed("tds_deductions", _typed("a", day="2025-10-01"))
    db.seed("tds_deductions", _typed("b", day="2025-12-31"))
    assert _books(db)["typed_on_statement"]["count"] == 2


# ── a row a document wrote is not a typed one (the first review of this change) ──────────────

def _advance_register_row(rid="r-adv", *, tds=10_000_00, payment_id="p1", section="194C", day="2025-11-10", payment=5_00_000_00):
    """The row `tds_register_service.sync_for_payment` writes for a vendor advance (migration 358): `purchase_payment_id` set and `purchase_bill_id` NULL."""
    return {"id": rid, "firm_id": FIRM, "client_id": CLIENT, "deductee_name": "Pinnacle Engineering", "deductee_pan": "AAGCP7788R", "section": section,
            "transaction_date": day, "payment_amount_paise": payment, "tds_paise": tds, "purchase_bill_id": None, "purchase_payment_id": payment_id}


def test_a_vendor_advance_is_on_the_statement_and_is_not_called_a_deduction_it_leaves_out():
    """The review's scenario: a Rs.5,00,000 section 194C advance to a resident vendor, tax Rs.10,000. The statement carries it as a deductee, and its register row (the
    advance wrote it) must not also be offered as 'typed on the TDS screen and not on this statement', which would have the CA key it a second time."""
    db = FakeDB()
    db.seed("vendors", {"id": "v1", "firm_id": FIRM, "name": "Pinnacle Engineering", "pan": "AAGCP7788R", "residential_status": "resident"})
    db.seed("purchase_payments", {"id": "p1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1", "payment_no": "PAY-1", "payment_date": "2025-11-10",
                                  "tds_base_paise": 5_00_000_00, "tds_paise": 10_000_00, "tds_rate_bps": 200, "tds_section": "194C", "is_reversed": False,
                                  "journal_entry_id": None})
    db.seed("tds_deductions", _advance_register_row())
    out = _books(db, bill=False)
    assert out["deductee_count"] == 1 and out["total_tds_deducted_paise"] == 10_000_00, "the advance is on the statement"
    assert out["typed_on_statement"]["count"] == 0 and out["typed_on_statement"]["tds_paise"] == 0
    assert out["excluded_typed"]["count"] == 0
    assert not [g for g in out["keying_sheet"]["gaps"] if "typed on the TDS screen" in g]


def test_a_non_residents_nil_advance_row_is_not_a_typed_deduction_either():
    """The review's second probe: a nil section 195 advance writes a register row (a 27Q remittance, with a reason) that is neither tax withheld nor typed."""
    db = FakeDB()
    db.seed("tds_deductions", _advance_register_row("r-nil", tds=0, payment_id="p2", section="195", payment=5_00_000_00))
    db.seed("tds_deductions", _advance_register_row("r-adv", tds=10_000_00, payment_id="p1"))
    assert _books(db, bill=False)["typed_on_statement"]["count"] == 0


def test_the_document_that_wrote_a_row_decides_not_the_bill_alone():
    from domain.tds.manual_register import written_by_a_document
    assert written_by_a_document({"purchase_bill_id": "b1"}) is True
    assert written_by_a_document({"purchase_payment_id": "p1"}) is True
    assert written_by_a_document({"purchase_bill_id": None, "purchase_payment_id": None}) is False
    assert written_by_a_document({}) is False


def test_a_payment_recorded_at_nothing_is_not_a_deduction_left_out():
    """A statement reports deductions. A Rs.10,000 section 194H payment under its limit is a register entry with no tax: it counts toward the year's total and is
    nothing to key."""
    db = FakeDB()
    db.seed("tds_deductions", _typed("t0", tds=0, payment=10_000_00, section="194H"))
    out = _books(db, bill=False)
    assert out["typed_on_statement"]["count"] == 0 and out["deductee_count"] == 0
    assert not [g for g in out["keying_sheet"]["gaps"] if "typed on the TDS screen" in g]
    db.seed("tds_deductions", _typed("t1"))
    assert _books(db, bill=False)["typed_on_statement"]["count"] == 1, "a row that withheld tax is still on the statement beside it"


def _register_row(rid, **over):
    return {"id": rid, "firm_id": FIRM, "client_id": CLIENT, "section": "194J", "deductee_name": "V", "deductee_pan": PAN_COMPANY,
            "payment_amount_paise": 1_00_000_00, "tds_paise": 10_000_00, "tds_rate_pct": 10, "transaction_date": "2026-06-15", **over}


def test_the_correct_and_remove_doors_refuse_a_row_an_advance_wrote(app_db):
    """The same question the statement's note asks: a vendor advance's register row follows the payment (a reversed payment loses it), so changing it here would
    be put back and removing it would leave the register short of a payment the books hold."""
    app, db = app_db
    db.seed("tds_deductions", _register_row("D-adv", purchase_payment_id="p1"))
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    client = TestClient(app, raise_server_exceptions=False)
    patched = client.patch("/api/tds-workspace/deductions/D-adv", json={"payment_amount_paise": 1}).json()
    assert patched["success"] is False and patched["error"] == "This deduction came from a vendor payment (an advance). It follows the payment and cannot be changed here."
    removed = client.delete("/api/tds-workspace/deductions/D-adv").json()
    assert removed["success"] is False and removed["error"] == "This deduction came from a vendor payment (an advance). It follows the payment and cannot be removed here."
    assert len(db.rows("tds_deductions")) == 1 and db.rows("tds_deductions")[0]["payment_amount_paise"] == 1_00_000_00


def test_the_two_doors_keep_their_words_for_a_bill_and_still_change_a_typed_row(app_db):
    app, db = app_db
    db.seed("tds_deductions", _register_row("D-bill", purchase_bill_id="B1"))
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    client = TestClient(app, raise_server_exceptions=False)
    assert client.patch("/api/tds-workspace/deductions/D-bill", json={"payment_amount_paise": 1}).json()["error"] == (
        "This deduction came from a purchase bill. Edit the bill instead — the register is rebuilt from it on every receive.")
    assert client.delete("/api/tds-workspace/deductions/D-bill").json()["error"] == "This deduction came from a purchase bill. Cancel or edit the bill instead."
    typed = _post(app, section="194H", payment_amount_paise=1_00_000_00).json()["data"]
    app.dependency_overrides[get_current_user] = lambda: MANAGER                  # _post spoke as an Executive; removing a register row is a Manager's
    assert client.patch(f"/api/tds-workspace/deductions/{typed['id']}", json={"payment_amount_paise": 2_00_000_00}).json()["success"] is True
    assert client.delete(f"/api/tds-workspace/deductions/{typed['id']}").json()["success"] is True


# ── POST-A-409: a row its own document no longer carries can be removed, by the document's own sync ───────

def test_a_row_a_reversed_advance_left_behind_is_removed_by_the_payments_own_sync(app_db):
    """A failed sync of a reversed advance left its register row behind, and the remove door refused every row a document wrote, so nothing removed it."""
    app, db = app_db
    db.seed("purchase_payments", {"id": "p1", "firm_id": FIRM, "client_id": CLIENT, "is_reversed": True, "tds_paise": 10_000_00, "tds_base_paise": 1_00_000_00})
    db.seed("tds_deductions", _register_row("D-adv", purchase_payment_id="p1"))
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    out = TestClient(app, raise_server_exceptions=False).delete("/api/tds-workspace/deductions/D-adv").json()
    assert out["success"] is True and out["data"]["removed_because"].startswith("The vendor payment this deduction recorded has been reversed")
    assert db.rows("tds_deductions") == []


def test_a_row_a_live_advance_wrote_is_still_refused_and_kept(app_db):
    app, db = app_db
    db.seed("purchase_payments", {"id": "p1", "firm_id": FIRM, "client_id": CLIENT, "is_reversed": False, "tds_paise": 10_000_00, "tds_base_paise": 1_00_000_00})
    db.seed("tds_deductions", _register_row("D-adv", purchase_payment_id="p1"))
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    out = TestClient(app, raise_server_exceptions=False).delete("/api/tds-workspace/deductions/D-adv").json()
    assert out["success"] is False and out["error"].endswith("It follows the payment and cannot be removed here.")
    assert len(db.rows("tds_deductions")) == 1


def test_a_payment_of_another_client_does_not_release_the_row(app_db):
    """The payment is read under the ROW's own firm and client, so a reversed payment of the same id elsewhere cannot vouch for removing it."""
    app, db = app_db
    db.seed("purchase_payments", {"id": "p1", "firm_id": FIRM, "client_id": "C-other", "is_reversed": True})
    db.seed("tds_deductions", _register_row("D-adv", purchase_payment_id="p1"))
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    assert TestClient(app, raise_server_exceptions=False).delete("/api/tds-workspace/deductions/D-adv").json()["success"] is False
    assert len(db.rows("tds_deductions")) == 1


@pytest.mark.parametrize("status,deleted_at,removed", [("cancelled", None, True), ("draft", None, True), ("received", "2026-07-01T00:00:00+00:00", True),
                                                       ("received", None, False), ("paid", None, False)])
def test_a_bills_row_is_removed_only_when_the_bill_has_left_the_books(app_db, status, deleted_at, removed):
    app, db = app_db
    db.seed("purchase_bills", {"id": "B1", "firm_id": FIRM, "client_id": CLIENT, "status": status, "deleted_at": deleted_at, "tds_paise": 10_000_00})
    db.seed("tds_deductions", _register_row("D-bill", purchase_bill_id="B1"))
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    out = TestClient(app, raise_server_exceptions=False).delete("/api/tds-workspace/deductions/D-bill").json()
    assert out["success"] is removed
    assert (db.rows("tds_deductions") == []) is removed
    if not removed:
        assert out["error"] == "This deduction came from a purchase bill. Cancel or edit the bill instead."


def test_the_register_list_names_the_rows_their_document_left_behind_and_only_those(app_db):
    """The screen offers to remove a row only where the list says its document no longer carries it, and a typed row or a live document's row says nothing."""
    app, db = app_db
    for table, row in (("purchase_payments", {"id": "p-rev", "firm_id": FIRM, "client_id": CLIENT, "is_reversed": True}),
                       ("purchase_payments", {"id": "p-live", "firm_id": FIRM, "client_id": CLIENT, "is_reversed": False}),
                       ("purchase_bills", {"id": "B-cancel", "firm_id": FIRM, "client_id": CLIENT, "status": "cancelled"}),
                       ("purchase_bills", {"id": "B-live", "firm_id": FIRM, "client_id": CLIENT, "status": "received"}),
                       ("tds_deductions", _register_row("D1", purchase_payment_id="p-rev")), ("tds_deductions", _register_row("D2", purchase_payment_id="p-live")),
                       ("tds_deductions", _register_row("D3", purchase_bill_id="B-cancel")), ("tds_deductions", _register_row("D4", purchase_bill_id="B-live")),
                       ("tds_deductions", _register_row("D5"))):
        db.seed(table, row)
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    out = TestClient(app, raise_server_exceptions=False).get(f"/api/tds-workspace/deductions?client_id={CLIENT}").json()["data"]
    assert out["left_behind_checked"] is True
    said = {d["id"]: d["left_behind_by_its_document"] for d in out["deductions"]}
    assert said == {"D1": "The vendor payment this deduction recorded has been reversed, so it no longer belongs on the register.", "D2": None,
                    "D3": "The purchase bill this deduction recorded is no longer in the books, so it no longer belongs on the register.", "D4": None, "D5": None}


def test_a_list_that_could_not_read_the_documents_says_so_and_names_nothing(app_db, monkeypatch):
    import routers.tds_workspace as mod
    app, db = app_db
    db.seed("tds_deductions", _register_row("D1", purchase_payment_id="p-rev"))
    monkeypatch.setattr(mod, "_mark_left_behind", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("read failed")))
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    out = TestClient(app, raise_server_exceptions=False).get(f"/api/tds-workspace/deductions?client_id={CLIENT}").json()["data"]
    assert out["left_behind_checked"] is False and "left_behind_by_its_document" not in out["deductions"][0]


def test_a_sync_that_fails_again_is_a_refusal_that_says_so_and_keeps_the_row(app_db, monkeypatch):
    from services import tds_register_service
    app, db = app_db
    monkeypatch.setattr(tds_register_service, "sync_for_payment", lambda *a, **k: {"synced": False, "reason": "boom"})
    db.seed("purchase_payments", {"id": "p1", "firm_id": FIRM, "client_id": CLIENT, "is_reversed": True})
    db.seed("tds_deductions", _register_row("D-adv", purchase_payment_id="p1"))
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    res = TestClient(app, raise_server_exceptions=False).delete("/api/tds-workspace/deductions/D-adv")
    assert res.status_code == 409 and "could not be removed just now" in res.json()["detail"]
    assert len(db.rows("tds_deductions")) == 1


# ── the year was added up only if the register was asked and the section has a yearly limit ───────

def _registry_sections(fy="2025-26"):
    from domain.tds.section_rates import tds_rates_for
    return sorted(tds_rates_for(fy).sections.items())


def test_the_year_is_said_to_be_added_up_exactly_for_the_sections_that_have_a_yearly_limit(monkeypatch):
    """Four sections deliberately have none (s.194I tests a month, s.194B one transaction, s.192 and s.206C are not computed here), so for them the year was
    never compared with anything however much was read. Derived from the registry for EVERY section it holds, so a section added later is judged too."""
    import routers.tds_workspace as mod
    from fastapi import HTTPException
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    judged = {"with": 0, "without": 0}
    for code, rule in _registry_sections():
        body = {"client_id": CLIENT, "deductee_name": "Acme Services", "deductee_pan": PAN_COMPANY, "section": code,
                "payment_amount_paise": 15_000_00, "transaction_date": CONFIRMED_DAY}
        try:
            explain = mod._resolve_manual_deduction(FakeDB(), FIRM, CLIENT, body)["explain"]
        except HTTPException:
            continue                                   # a section the typed door refuses (salary, tax collected at source, one the engine does not hold)
        has_limit = rule.aggregate_threshold_paise is not None
        assert explain["aggregate_tested"] is has_limit, f"section {code}: aggregate_tested {explain['aggregate_tested']} but the registry says a yearly limit is {has_limit}"
        judged["with" if has_limit else "without"] += 1
    assert judged["with"] >= 5 and judged["without"] >= 2, f"the registry loop judged too little to mean anything: {judged}"


def test_a_year_nobody_has_confirmed_is_never_called_added_up_and_says_so(app_db):
    """The review's reproduction: s.194J at Rs 40,000 typed for FY 2024-25 comes back nil from the substituted year's bar (Rs 4,000 was due), and the typed door said
    nothing, as the bill and advance paths do. FY 2026-27 (the current year) is held but not confirmed. Both get the gap and neither is told the year was added up."""
    from domain.tds.residency import GAP_RESIDENT_RATES_UNVERIFIED
    app, _ = app_db
    for day in (NOT_HELD_DAY, UNCONFIRMED_DAY):
        explain = _post(app, section="194J", payment_amount_paise=40_000_00, transaction_date=day).json()["data"]["explain"]
        assert explain["aggregate_tested"] is False, day
        assert GAP_RESIDENT_RATES_UNVERIFIED in explain["gaps"], day
        assert GAP_MESSAGES[GAP_RESIDENT_RATES_UNVERIFIED] in explain["gap_messages"], day
        assert "deduction's financial year" in GAP_MESSAGES[GAP_RESIDENT_RATES_UNVERIFIED]
    confirmed = _post(app, section="194J", payment_amount_paise=40_000_00, transaction_date=CONFIRMED_DAY).json()["data"]["explain"]
    assert confirmed["aggregate_tested"] is True and GAP_RESIDENT_RATES_UNVERIFIED not in confirmed["gaps"]


def test_the_register_is_not_said_to_have_been_asked_when_it_could_not_be(monkeypatch):
    """`prior_manual_aggregate` returns at once, without a query, for a blank firm, client or section; a crafted call with a blank client used to be told the year was added up."""
    import routers.tds_workspace as mod
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    body = {"client_id": "", "deductee_name": "Acme Services", "deductee_pan": PAN_COMPANY, "section": "194H", "payment_amount_paise": 15_000_00, "transaction_date": CONFIRMED_DAY}
    assert mod._resolve_manual_deduction(FakeDB(), FIRM, "", body)["explain"]["aggregate_tested"] is False
    assert mod._resolve_manual_deduction(FakeDB(), "", CLIENT, body)["explain"]["aggregate_tested"] is False
    assert mod._resolve_manual_deduction(FakeDB(), FIRM, CLIENT, body)["explain"]["aggregate_tested"] is True


@pytest.mark.parametrize("typed, says", [
    (PAN_COMPANY, "PAN 4th character C."),
    ("PANNOTAVBL", "no PAN is on file"), ("PANAPPLIED", "no PAN is on file"), (None, "no PAN is on file"), ("ABC", "no PAN is on file"),
    ("NOTAPAN", "read from the 4th character of what was typed in the PAN box. That text is not a PAN"),
])
def test_the_rate_basis_never_calls_what_is_not_a_pan_a_pan(app_db, typed, says):
    """'PAN 4th character N' beside 'No usable PAN is recorded' was one box contradicting itself."""
    app, _ = app_db
    explain = _post(app, deductee_pan=typed).json()["data"]["explain"]
    assert says in explain["rate_basis"], explain["rate_basis"]
    if typed != PAN_COMPANY:
        assert "PAN 4th character" not in explain["rate_basis"]


@pytest.mark.parametrize("section", ["194I", "194I(A)", "194I(B)", "194B"])
def test_a_section_with_no_yearly_limit_is_never_said_to_have_had_the_year_added_up(app_db, section):
    app, _ = app_db
    explain = _post(app, section=section, payment_amount_paise=10_000_00).json()["data"]["explain"]
    assert explain["aggregate_tested"] is False
    assert GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN not in explain["gaps"], "the payee has a PAN: what was not tested is the section's, not the payee's"


# ── the year was looked at only if the register was asked ────────────────────

@pytest.mark.parametrize("mock_mode, has_db, expected", [(False, True, True), (True, True, False), (False, False, False), (True, False, False)])
def test_the_year_is_said_to_be_looked_at_only_when_the_register_was_asked(monkeypatch, mock_mode, has_db, expected):
    import routers.tds_workspace as mod
    monkeypatch.setattr(mod, "_USE_MOCK", mock_mode)
    body = {"client_id": CLIENT, "deductee_name": "Acme Services", "deductee_pan": PAN_COMPANY, "section": "194H",
            "payment_amount_paise": 15_000_00, "transaction_date": CONFIRMED_DAY}
    explain = mod._resolve_manual_deduction(FakeDB() if has_db else None, FIRM, CLIENT, body)["explain"]
    assert explain["aggregate_tested"] is expected
    assert GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN not in explain["gaps"], "a payee WITH a PAN is never told it has none, whether or not the register was asked"


# ── and the sheet the CA keys from says so too ───────────────────────────────

def test_the_keying_sheet_says_which_typed_deductions_it_holds_and_which_it_does_not():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1"))
    db.seed("tds_deductions", _typed("t2", day="2025-12-05", payment=40_000_00, tds=80_000))
    db.seed("tds_deductions", {**_typed("t3", day="2025-11-05", payment=10_000_00, tds=2_000_00), "return_type": "27Q"})
    gaps = _books(db)["keying_sheet"]["gaps"]
    named = [g for g in gaps if "typed on the TDS screen" in g]
    assert len(named) == 2
    held = next(g for g in named if "are on this sheet" in g)
    assert held.startswith("2 deduction(s) typed on the TDS screen for this quarter, with ₹10,800.00 of tax withheld, are on this sheet")
    assert "No journal stands behind a typed deduction" in held
    left = next(g for g in named if "are not on this sheet" in g)
    assert left.startswith("1 deduction(s) typed on the TDS screen for this quarter, with ₹2,000.00 of tax withheld, are not on this sheet")
    assert "another statement" in left
    assert gaps[-1].startswith("This is a keying sheet"), "the standing sentence stays last"


def test_the_keying_sheet_of_a_statement_with_none_says_nothing_about_them():
    gaps = _books(FakeDB())["keying_sheet"]["gaps"]
    assert not [g for g in gaps if "typed on the TDS screen" in g]


def test_a_sheet_built_without_the_key_says_nothing_either_way():
    from domain.tds import keying_sheet
    assert not [g for g in keying_sheet.build({"deductees": [], "challans": []})["gaps"] if "typed on the TDS screen" in g]


# ── it is a read of the quarter, scoped to the firm and the client ───────────

def test_the_read_is_scoped_to_the_firm_and_the_client_and_pages():
    import inspect
    from services import tds_return_service as m
    src = inspect.getsource(m._typed_deductions_in_quarter)
    assert '.eq("firm_id", firm_id).eq("client_id", client_id)' in src
    assert "fetch_all(" in src
    assert '.gte("transaction_date", start).lte("transaction_date", end)' in src


def test_only_the_26q_builder_carries_the_key():
    import inspect
    from services import tds_return_service as m
    for key in ("excluded_typed", "typed_on_statement"):
        assert key in inspect.getsource(m.tds_26q_from_books)
        assert key not in inspect.getsource(m.tds_27q_from_books)
        assert key not in inspect.getsource(m.tds_24q_from_books)


# ── the browser drive speaks the server's sentences ──────────────────────────

DRIVE = Path(__file__).resolve().parents[3] / "apps" / "web" / "scripts" / "drive" / "scenarios" / "typedDeductionsNamed.mjs"


def _drive_literal(name: str) -> str:
    """The text of `const NAME = "...";` in the drive's scenario file (the same way tests/test_the_drives_filing_sentences_are_the_servers.py reads a constant)."""
    m = re.search(rf'const {name} = "((?:[^"\\]|\\.)*)";', DRIVE.read_text(encoding="utf-8"))
    assert m, f"{name} is no longer written as a constant in typedDeductionsNamed.mjs, so the drive's copy of the server's sentence cannot be compared"
    return m.group(1)


def test_the_drives_copy_of_the_note_sentence_is_the_servers():
    from services.tds_return_service import EXCLUDED_TYPED_REASON
    assert _drive_literal("TYPED_REASON") == EXCLUDED_TYPED_REASON


def test_the_drives_copies_of_the_two_gap_sentences_are_the_servers():
    assert _drive_literal("GAP_NO_PAN") == GAP_MESSAGES[GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN]
    assert _drive_literal("GAP_NO_SUPPLIER") == GAP_MESSAGES[GAP_NO_SUPPLIER]
