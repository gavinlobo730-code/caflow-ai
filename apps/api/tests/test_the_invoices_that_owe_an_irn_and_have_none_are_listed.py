"""
GST-20 — invoices that need an IRN and have none, with the reporting-window clock.

WHAT WAS WRONG
    `irn_scope.assess` decides, for the ONE invoice somebody has open, whether
    CGST Rule 48(4) reaches it. Nothing listed, across a client or a practice,
    the in-scope invoices that have no recorded IRN — and under Rule 48(5) an
    invoice that needed one and has none "shall not be treated as an invoice", so
    the recipient's input credit goes with it. The router's own header notes the
    IRP's thirty-day reporting limit for turnover of ₹10 crore and over, and
    nothing counted a day against it.

WHAT THIS ASSERTS
    * THE FINDING'S OWN VERIFY LINE: of three in-scope invoices — one with an
      IRN, one 29 days old, one 31 days old — the two without are listed, the
      31-day-old one is flagged as past the window, and an out-of-scope B2C
      invoice is not listed;
    * the two limbs are kept APART: Rule 48(4)'s ₹5 crore decides whether an IRN
      is owed, the IRP's ₹10 crore decides whether there is a clock, so a ₹7
      crore client's invoice is listed with NO deadline rather than dropped;
    * an unrecorded turnover is never read as "below the floor";
    * the e-invoicing ratchet (a client who crossed once is in for good) reaches
      the clock too;
    * what a cancelled or half-prepared record means is told apart from "never
      attempted";
    * the read is proportional to the answer, tenanted by firm, and scoped to the
      caller's own clients;
    * the window's figures are named, [S]-graded constants — not inline literals.
"""
from __future__ import annotations

import inspect
from datetime import date

import pytest

import routers.einvoice as router
import services.irn_worklist_service as svc
from domain.gst import irn_scope, irn_worklist as wl
from tests.e2e_harness import FakeDB

FIRM = "FIRM-I"
OTHER_FIRM = "FIRM-OTHER"
CLIENT = "CLI-BIG"
TODAY = date(2026, 10, 1)
B2B_GSTIN = "27BBBBB1111B1ZN"


def d(days_old: int) -> str:
    return date.fromordinal(TODAY.toordinal() - days_old).isoformat()


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Big Co",
                       "legal_name": "Big Company Pvt Ltd"})
    # The turnover the Rule 48(4) limb reads: ₹20 crore recorded for last year.
    x.seed("client_gst_turnover", {"firm_id": FIRM, "client_id": CLIENT,
                                   "financial_year": "2025-26",
                                   "aggregate_turnover_paise": 20_00_00_000_00})
    x.seed("customers", {"id": "CUST-B2B", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Registered Buyer", "gstin": B2B_GSTIN})
    x.seed("customers", {"id": "CUST-B2C", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Walk-in", "gstin": None})
    return x


def _invoice(db, no, days_old, *, customer="CUST-B2B", client=CLIENT, firm=FIRM,
             status="issued", **extra):
    return db.seed("client_sales_invoices", {
        "firm_id": firm, "client_id": client, "customer_id": customer,
        "invoice_no": no, "invoice_date": d(days_old), "status": status,
        "total_paise": 1_18_000_00, "igst_paise": 0,
        "supply_type": "taxable", "invoice_type": "Regular",
        "is_opening": False, "deleted_at": None, **extra})


def _record(db, invoice, *, status="generated", irn="a" * 64, link=True, **extra):
    return db.seed("einvoice_records", {
        "firm_id": FIRM, "client_id": invoice["client_id"],
        "sales_invoice_id": invoice["id"] if link else None,
        "invoice_number": invoice["invoice_no"],
        "invoice_date": invoice["invoice_date"], "status": status, "irn": irn,
        **extra})


def _list(db, **kw):
    kw.setdefault("as_at", TODAY)
    return svc.worklist(db, FIRM, **kw)


def _by_no(out):
    return {r["invoice_no"]: r for r in out["invoices"]}


# ── THE FINDING'S VERIFY LINE ────────────────────────────────────────────────

def test_the_two_invoices_without_an_irn_are_listed_and_the_late_one_is_flagged(db):
    with_irn = _invoice(db, "INV-WITH-IRN", 10)
    _record(db, with_irn)
    _invoice(db, "INV-29", 29)
    _invoice(db, "INV-31", 31)
    _invoice(db, "INV-B2C", 5, customer="CUST-B2C")          # out of scope

    out = _list(db)

    rows = _by_no(out)
    assert set(rows) == {"INV-29", "INV-31"}, (
        "the invoice with an IRN and the B2C invoice must not be listed")
    assert rows["INV-29"]["window"]["status"] == "within_window"
    assert rows["INV-29"]["window"]["days_left"] == 1
    assert rows["INV-31"]["window"]["status"] == "past_window"
    assert rows["INV-31"]["window"]["days_left"] == -1
    assert out["counts"]["within_window"] == 1
    assert out["counts"]["past_window"] == 1
    assert out["counts"]["total"] == 2


def test_oldest_first(db):
    _invoice(db, "INV-NEW", 3)
    _invoice(db, "INV-OLD", 27)
    _invoice(db, "INV-MID", 12)
    assert [r["invoice_no"] for r in _list(db)["invoices"]] == [
        "INV-OLD", "INV-MID", "INV-NEW"]


def test_the_thirtieth_day_is_the_last_day_and_is_its_own_state(db):
    _invoice(db, "INV-30", 30)
    row = _by_no(_list(db))["INV-30"]
    assert row["window"]["status"] == "last_day"
    assert row["window"]["days_left"] == 0
    assert row["window"]["deadline"] == TODAY.isoformat()


# ── what is in scope ─────────────────────────────────────────────────────────

def test_an_export_to_a_buyer_with_no_gstin_is_in_scope(db):
    """Rule 48(4)'s supply limb names exports: a foreign buyer holds no GSTIN
    and the rule still reaches the invoice."""
    _invoice(db, "EXP-1", 8, customer="CUST-B2C", supply_type="zero_rated",
             igst_paise=0)
    assert "EXP-1" in _by_no(_list(db))


@pytest.mark.parametrize("extra", [
    {"status": "draft"}, {"status": "cancelled"},
    {"is_opening": True}, {"deleted_at": "2026-09-30T00:00:00Z"}])
def test_only_issued_live_non_opening_invoices_are_listed(db, extra):
    """A draft has not been issued, a cancelled one is no supply, a deleted one
    is gone, and a carried-over opening document was issued — and its IRN
    obtained — on the system the client migrated from."""
    _invoice(db, "INV-X", 5, **extra)
    assert _list(db)["invoices"] == []


def test_a_malformed_customer_gstin_is_read_as_registered_and_is_still_listed(db):
    db.seed("customers", {"id": "CUST-BAD", "firm_id": FIRM, "client_id": CLIENT,
                          "name": "Typo Ltd", "gstin": "27BBBBB1111B1Z"})
    _invoice(db, "INV-BAD", 5, customer="CUST-BAD")
    out = _list(db)
    assert "INV-BAD" in _by_no(out), (
        "reading a mistyped GSTIN as unregistered would take a required IRN off the list")
    assert any("not a well-formed GSTIN" in c or "not well-formed" in c
               for c in out["caveats"])


# ── what "no IRN" means ──────────────────────────────────────────────────────

def test_a_cancelled_irn_is_told_apart_from_one_never_attempted(db):
    never = _invoice(db, "INV-NEVER", 9)
    cancelled = _invoice(db, "INV-CANCELLED", 9)
    prepared = _invoice(db, "INV-PREPARED", 9)
    _record(db, cancelled, status="cancelled")
    _record(db, prepared, status="draft", irn=None)
    rows = _by_no(_list(db))
    assert rows["INV-NEVER"]["irn_state"] == "none"
    assert rows["INV-CANCELLED"]["irn_state"] == "irn_cancelled"
    assert rows["INV-PREPARED"]["irn_state"] == "record_prepared_not_generated"
    assert never["id"] and rows["INV-NEVER"]["invoice_id"] == never["id"]


def test_a_record_not_linked_to_the_invoice_is_matched_by_number(db):
    """`sales_invoice_id` is optional — a record may be prepared for an invoice
    without being linked — and numbers are unique per client (migration 151)."""
    inv = _invoice(db, "INV-UNLINKED", 9)
    _record(db, inv, link=False)
    assert _list(db)["invoices"] == []


def test_a_generated_record_with_no_irn_is_not_a_live_irn(db):
    inv = _invoice(db, "INV-EMPTY", 9)
    _record(db, inv, status="generated", irn="")
    assert "INV-EMPTY" in _by_no(_list(db))


# ── the two limbs are different instruments ──────────────────────────────────

def test_a_seven_crore_client_owes_an_irn_but_has_no_reporting_clock(db):
    """Rule 48(4)'s threshold is ₹5 crore; the IRP's thirty days is for ₹10
    crore and over. The invoice STILL has no IRN and Rule 48(5) still bites, so
    it is listed — with no deadline, because nobody imposes one."""
    db.rows("client_gst_turnover")[0]["aggregate_turnover_paise"] = 7_00_00_000_00
    _invoice(db, "INV-SEVEN", 45)
    row = _by_no(_list(db))["INV-SEVEN"]
    assert row["window"]["status"] == "no_reporting_limit"
    assert row["window"]["deadline"] is None and row["window"]["days_left"] is None
    assert row["window"]["applies"] is False and row["window"]["assumed"] is False


def test_a_client_that_never_exceeded_the_lowest_threshold_is_never_read(db, monkeypatch):
    db.rows("client_gst_turnover")[0]["aggregate_turnover_paise"] = 3_00_00_000_00
    _invoice(db, "INV-SMALL", 5)
    seen = []
    real = svc.fetch_all_in

    def spy(make, column, values, *a, **k):
        seen.append((k.get("label"), column, sorted(values)))
        return real(make, column, values, *a, **k)

    monkeypatch.setattr(svc, "fetch_all_in", spy)
    out = _list(db)
    assert out["invoices"] == []
    assert out["clients_below_threshold"] == 1
    assert not [s for s in seen if s[0] == "irn_worklist.invoices"], (
        "a client outside Rule 48(4) on every date must cost no invoice read")


def test_the_ratchet_reaches_the_clock(db):
    """Rule 48(4) reads on ANY preceding year from 2017-18, so e-invoicing
    latches: ₹20 crore in 2022-23 and ₹4 crore since is still in. The clock's
    ₹10 crore floor is judged on the same highest figure."""
    db.rows("client_gst_turnover")[0].update(
        financial_year="2025-26", aggregate_turnover_paise=4_00_00_000_00)
    db.seed("client_gst_turnover", {"firm_id": FIRM, "client_id": CLIENT,
                                    "financial_year": "2022-23",
                                    "aggregate_turnover_paise": 20_00_00_000_00})
    _invoice(db, "INV-LATCHED", 31)
    row = _by_no(_list(db))["INV-LATCHED"]
    assert row["window"]["applies"] is True
    assert row["window"]["status"] == "past_window"


def test_an_unrecorded_turnover_is_never_read_as_below_the_floor(db):
    """None is a third state. Reading it as 'below the floor' would hide the
    clock from exactly the client nobody has looked at."""
    db.rows("client_gst_turnover").clear()
    _invoice(db, "INV-UNKNOWN", 31)

    # FIRM-WIDE: not assessed, and NAMED — strict-reading every B2B invoice of
    # every unrecorded client would bury the clients really over the line.
    firm = _list(db)
    assert firm["invoices"] == []
    assert [c["client_id"] for c in firm["clients_not_assessed"]] == [CLIENT]
    assert "Record it" in firm["clients_not_assessed"][0]["reason"]

    # ONE CLIENT: the CA is looking at it, so the invoices are listed, flagged,
    # and the clock is shown as ASSUMED.
    one = _list(db, client_id=CLIENT)
    row = _by_no(one)["INV-UNKNOWN"]
    assert one["client_status"] == "turnover_not_recorded"
    assert row["turnover_unknown"] is True
    assert row["window"]["assumed"] is True and row["window"]["applies"] is None
    assert row["window"]["status"] == "past_window"
    assert any("marked assumed" in c for c in one["caveats"])


# ── bounded, tenanted, scoped ────────────────────────────────────────────────

def test_the_look_back_is_bounded_and_said(db):
    _invoice(db, "INV-RECENT", 20)
    _invoice(db, "INV-ANCIENT", wl.DEFAULT_LOOKBACK_DAYS + 40)
    out = _list(db)
    assert set(_by_no(out)) == {"INV-RECENT"}
    assert out["listed_since"] == d(wl.DEFAULT_LOOKBACK_DAYS)
    wider = _list(db, since=d(400))
    assert set(_by_no(wider)) == {"INV-RECENT", "INV-ANCIENT"}
    assert wider["listed_since"] == d(400)


def test_a_bad_since_is_refused_in_words(db):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _list(db, since="last tuesday")


def test_another_firms_invoices_are_never_read(db):
    db.seed("clients", {"id": "CLI-OTHER", "firm_id": OTHER_FIRM,
                        "client_name": "Theirs"})
    db.seed("client_gst_turnover", {"firm_id": OTHER_FIRM, "client_id": "CLI-OTHER",
                                    "financial_year": "2025-26",
                                    "aggregate_turnover_paise": 50_00_00_000_00})
    db.seed("customers", {"id": "CUST-O", "firm_id": OTHER_FIRM,
                          "client_id": "CLI-OTHER", "name": "O", "gstin": B2B_GSTIN})
    _invoice(db, "THEIRS", 5, customer="CUST-O", client="CLI-OTHER", firm=OTHER_FIRM)
    _invoice(db, "OURS", 5)
    assert set(_by_no(_list(db))) == {"OURS"}


def test_a_caller_sees_only_their_own_clients(db):
    db.seed("clients", {"id": "CLI-2", "firm_id": FIRM, "client_name": "Second"})
    db.seed("client_gst_turnover", {"firm_id": FIRM, "client_id": "CLI-2",
                                    "financial_year": "2025-26",
                                    "aggregate_turnover_paise": 50_00_00_000_00})
    _invoice(db, "INV-A", 5)
    _invoice(db, "INV-B", 5, client="CLI-2")
    assert set(_by_no(_list(db))) == {"INV-A", "INV-B"}
    assert set(_by_no(_list(db, scope={CLIENT}))) == {"INV-A"}
    # An EMPTY set means nothing — never "no filter".
    assert _list(db, scope=set())["invoices"] == []


# ── the router ───────────────────────────────────────────────────────────────

CALLER = {"firm_id": FIRM, "id": "u-i", "auth_user_id": "auth-i",
          "email": "ca@i.test", "role": "Partner"}


def test_the_endpoint_is_read_gated_and_asserts_the_client(monkeypatch, db):
    import core.supabase_client as sc
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    _invoice(db, "INV-29", 29)
    out = router.invoices_that_owe_an_irn_and_have_none(client_id=CLIENT, since=None,
                                                        current_user=CALLER)
    assert out["success"] is True
    assert [r["invoice_no"] for r in out["data"]["invoices"]] == ["INV-29"]

    src = inspect.getsource(router.invoices_that_owe_an_irn_and_have_none)
    assert "assert_client_access" in src
    assert "effective_client_ids" in src
    # Wired to rbac("gst", "read") — a read, because nothing is written.
    from fastapi.routing import APIRoute
    route = next(r for r in router.router.routes
                 if isinstance(r, APIRoute) and r.path == "/api/einvoice/missing-irn")
    assert route.methods == {"GET"}
    deps = [getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies]
    assert deps, "rbac() must guard the route"


def test_a_bad_since_is_a_422_at_the_door(monkeypatch, db):
    import core.supabase_client as sc
    from fastapi import HTTPException
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    with pytest.raises(HTTPException) as e:
        router.invoices_that_owe_an_irn_and_have_none(
            client_id=None, since="soon", current_user=CALLER)
    assert e.value.status_code == 422


# ── the window's figures are named, graded constants ─────────────────────────

def test_the_reporting_window_is_a_named_unverified_constant():
    assert wl.REPORTING_WINDOW_DAYS == 30
    assert wl.WINDOW_IN_FORCE_FROM == "2025-04-01"
    assert wl.WINDOW_TURNOVER_FLOOR_PAISE == 10_00_00_000_00
    assert wl.VERIFIED is False


def test_the_two_thresholds_are_two_instruments():
    """Rule 48(4)'s ₹5 crore and the IRP's ₹10 crore must not be collapsed."""
    assert wl.WINDOW_TURNOVER_FLOOR_PAISE == 2 * min(t[1] for t in irn_scope.THRESHOLDS)
    src = inspect.getsource(wl)
    assert "THRESHOLDS" not in src.split('"""', 2)[2].replace("irn_scope.THRESHOLDS", ""), (
        "the window's floor must not be read off Rule 48(4)'s table")


def test_the_window_before_it_was_in_force_is_not_a_deadline():
    w = wl.reporting_window("2025-01-01", 20_00_00_000_00, date(2025, 2, 1))
    assert w["status"] == wl.NOT_IN_FORCE and w["deadline"] is None


def test_every_answer_says_what_it_cannot_see(db):
    out = _list(db)
    text = " ".join(out["caveats"])
    assert "[S]-graded" in text
    assert "Credit notes and debit notes are not listed" in text
    assert out["verified"] is False and out["ca_review_required"] is True
