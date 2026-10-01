"""The GSTR-1 the screen builds is the GSTR-1 a CA uploads (gst-33).

WHAT WAS WRONG
    `POST /gstr1/from-books` built the period's own return and nothing else. The
    corrections CGST Act §37 makes a LATER return carry — 9A for invoices, 9C for
    notes, 10 for B2C-others — were produced by a second route,
    `/gstr1/with-amendments`, and downloaded from a different tab under a
    different file name. A CA had to know which of two files carried the month's
    corrections, and the one the GSTR-1 screen built was the one without them.

WHAT MAKES DEFAULT-ON SAFE, AND WAS NOT TRUE BEFORE
    `outstanding_amendments` diffs every earlier filed return's FROZEN payload
    against the books as they stand. A filed payload never changes, so a
    correction July declared left June exactly as different from the books as it
    was — and August proposed it AGAIN, and September, for as long as June's
    §37(3) window stayed open. Harmless while the merged file was something a CA
    asked for by name; once the main build carries amendments it would have
    re-declared the same correction in every month's upload. So the question
    "has a later FILED return already declared this entry?" is now asked where
    the proposals are made, and the answer comes back as `already_declared`
    rather than vanishing.

WHAT IS ASSERTED
    * the default build carries the b2ba entry; `include_amendments=false` does
      not, and says `included: false`;
    * the build and `/gstr1/with-amendments` return the same payload — one
      implementation, through the real endpoints;
    * a period with nothing outstanding is byte-identical to the plain return;
    * a correction a later SUBMITTED return declared is not proposed again, and
      is named; one the books have since moved on from IS; a saved-but-unfiled
      return suppresses nothing; a return before the source suppresses nothing;
    * an out-of-time correction and one needing a decision stay out, as before;
    * if the amendments cannot be worked out the build FAILS naming the switch,
      and the switch still builds.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.gst as gst_router
import services.gst_amendment_service as svc
import services.gst_return_service as grs
from tests.test_gstr1_amendments_reach_the_payload import (  # noqa: F401  (db is a fixture)
    CALLER, CLIENT, FIRM, GSTIN, _drifted_june, _file, _invoice, db)


def _build(period="072025", **over):
    res = gst_router.gstr1_from_books_endpoint(
        gst_router.GSTR1FromBooksRequest(client_id=CLIENT, period=period, **over), CALLER)
    assert res["success"] is True, res
    return res["data"]


def _with_amendments_route(period="072025"):
    res = gst_router.gstr1_with_amendments_endpoint(
        gst_router.FromBooksRequest(client_id=CLIENT, period=period), CALLER)
    assert res["success"] is True, res
    return res["data"]


def _file_with_amendments(db, period, declared_payload, *, status="submitted"):
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": period, "gstin": GSTIN,
        "status": status, "payload_json": declared_payload,
        "submitted_at": "2025-08-11T00:00:00Z" if status == "submitted" else None,
        "arn": f"ARN{period}" if status == "submitted" else None})


# ── default on, switch off ───────────────────────────────────────────────────

def test_the_default_build_carries_the_amendment(db):
    _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)
    data = _build()
    assert "b2ba" in data["payload"], (
        "the GSTR-1 screen's own build still leaves the corrections out")
    assert data["payload"]["b2ba"], "b2ba present but empty"
    block = data["amendments"]
    assert block["included"] is True
    assert block["counts"]["amendments"] == 1
    assert block["sections"] == ["b2ba"]
    assert block["source_periods"] == ["062025"]


def test_the_switch_builds_the_return_without_them(db):
    _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)
    data = _build(include_amendments=False)
    assert "b2ba" not in data["payload"]
    assert data["amendments"] == {"included": False}


def test_the_default_is_on_for_every_caller_that_says_nothing():
    """A caller predating the field gets the amendments — the point of the item."""
    assert gst_router.GSTR1FromBooksRequest(
        client_id="C", period="072025").include_amendments is True


def test_an_excluded_build_computes_no_amendments_at_all(db, monkeypatch):
    """It must keep working when the amendment walk cannot."""
    def boom(*a, **k):
        raise RuntimeError("the walk is broken")
    monkeypatch.setattr(svc, "outstanding_amendments", boom)
    data = _build(include_amendments=False)
    assert data["amendments"] == {"included": False}


def test_the_switch_changes_only_the_amendment_tables(db):
    _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)
    with_ = _build()
    without = _build(include_amendments=False)
    for section in ("b2b", "b2cs", "b2cl", "cdnr", "hsn", "doc_issue"):
        assert with_["payload"].get(section) == without["payload"].get(section), section
    # The period's OWN totals and reconciliation are not amendments.
    for key in ("summary", "invoice_count", "taxable_total_paise", "tax_total_paise",
                "reconciliation"):
        assert with_[key] == without[key], key
    assert set(with_["payload"]) - set(without["payload"]) == {"b2ba"}


def test_the_build_and_the_amendments_tab_file_are_the_same_file(db):
    """ONE implementation: a CA who used to download `with-amendments` gets
    exactly what the GSTR-1 screen builds now."""
    _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)
    a, b = _build(), _with_amendments_route()
    assert a["payload"] == b["payload"]
    assert a["amendments"] == b["amendments"]


def test_a_period_with_nothing_outstanding_is_the_plain_return(db):
    _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)
    plain = _build(include_amendments=False)
    default = _build()
    assert default["payload"] == plain["payload"]
    assert default["amendments"]["counts"]["amendments"] == 0
    assert default["amendments"]["sections"] == []


# ── what a later filed return has already said is not said again ─────────────

def _july_declares_the_june_amendment(db):
    _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)
    base = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    july = svc.apply_amendments(base, svc.outstanding_amendments(db, FIRM, CLIENT, "072025"))
    assert "b2ba" in july, "the fixture produced no amendment to declare"
    return july


def test_a_correction_july_declared_is_not_proposed_again_in_august(db):
    july = _july_declares_the_june_amendment(db)
    _file_with_amendments(db, "072025", july)
    _invoice(db, "INV-3", "2025-08-05", 60_000, 5_400, 5_400)

    data = _build("082025")

    assert "b2ba" not in data["payload"], (
        "August re-declared the June correction that July's filed return "
        "already declared")
    assert data["amendments"]["counts"]["amendments"] == 0
    named = data["amendments"]["already_declared"]
    assert len(named) == 1
    assert (named[0]["section"], named[0]["table"]) == ("b2ba", "9A")
    assert (named[0]["from_period"], named[0]["declared_in"]) == ("062025", "072025")
    assert named[0]["original_ref"] == "INV-1"
    assert data["amendments"]["counts"]["already_declared"] == 1


def test_the_premise_without_the_later_return_it_IS_proposed(db):
    """Guard for the test above: it must pass because July DECLARED it, not
    because August stopped seeing the drift."""
    july = _july_declares_the_june_amendment(db)
    _file_with_amendments(db, "072025", july, status="draft")   # saved, never filed
    _invoice(db, "INV-3", "2025-08-05", 60_000, 5_400, 5_400)
    data = _build("082025")
    assert data["payload"].get("b2ba"), (
        "a SAVED-BUT-UNFILED return suppressed a correction nobody has declared")
    assert data["amendments"]["counts"]["already_declared"] == 0


def test_a_correction_the_books_have_moved_on_from_is_proposed_again(db):
    """An amendment re-declares the whole entry, so a different corrected figure
    is a different statement and still owed."""
    row = _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)
    base = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    july = svc.apply_amendments(base, svc.outstanding_amendments(db, FIRM, CLIENT, "072025"))
    _file_with_amendments(db, "072025", july)
    # The invoice is edited AGAIN after July was filed.
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 175_000}).eq("id", row["id"]).execute()
    _invoice(db, "INV-3", "2025-08-05", 60_000, 5_400, 5_400)

    data = _build("082025")

    assert data["payload"].get("b2ba"), "a fresh correction was suppressed as if declared"
    assert data["amendments"]["counts"]["amendments"] == 1
    assert data["amendments"]["already_declared"] == []


def test_a_return_before_the_source_period_suppresses_nothing(db):
    """A return filed BEFORE the drifted period cannot have declared a
    correction to it; matching on a stored payload regardless of period order
    would hide a real correction behind an unrelated one."""
    july = _july_declares_the_june_amendment(db)
    # The same declaration sits in a return for MAY — earlier than June.
    _file_with_amendments(db, "052025", july)
    _invoice(db, "INV-3", "2025-08-05", 60_000, 5_400, 5_400)
    data = _build("082025")
    assert data["payload"].get("b2ba")
    assert data["amendments"]["counts"]["already_declared"] == 0


def test_the_return_being_built_does_not_suppress_its_own_amendments(db):
    """The target period is the return being prepared, not one filed before it."""
    july = _july_declares_the_june_amendment(db)
    _file_with_amendments(db, "072025", july)
    out = svc.outstanding_amendments(db, FIRM, CLIENT, "072025")
    assert out["counts"]["amendments"] == 1
    assert out["already_declared"] == []


def test_the_tab_stops_offering_what_is_already_declared(db):
    """`GET /gstr1/amendments` reads the same function."""
    july = _july_declares_the_june_amendment(db)
    _file_with_amendments(db, "072025", july)
    out = svc.outstanding_amendments(db, FIRM, CLIENT, "082025")
    assert out["sections"] == {}
    assert out["counts"]["already_declared"] == 1


def test_the_reverse_of_grouping_finds_every_section_shape():
    """`declared_entries` is the inverse of `group_amendments`; a section added
    to one and not the other would make a declared correction look outstanding."""
    from domain.gst.amendments import group_amendments
    entries = [
        {"section": "b2ba", "group": "27BBBBB1111B1ZN", "node": {"oinum": "A", "val": 1.0}},
        {"section": "b2cla", "group": "27", "node": {"oinum": "B"}},
        {"section": "expa", "group": "WPAY", "node": {"oinum": "C"}},
        {"section": "cdnra", "group": "27BBBBB1111B1ZN", "node": {"ont_num": "D"}},
        {"section": "cdnura", "group": "", "node": {"ont_num": "E"}},
        {"section": "b2csa", "group": "", "node": {"omon": "062025"}},
    ]
    round_trip = svc.declared_entries(group_amendments(entries))
    key = lambda e: (e["section"], e["group"], str(e["node"]))   # noqa: E731
    assert sorted(map(key, round_trip)) == sorted(map(key, entries))
    assert set(svc._NESTED_SECTIONS) | set(svc._FLAT_SECTIONS) == {e["section"] for e in entries}


# ── what stays out, as before ────────────────────────────────────────────────

def test_an_out_of_time_correction_is_still_never_folded_in(db):
    from datetime import date
    _drifted_june(db)
    out = svc.outstanding_amendments(db, FIRM, CLIENT, "072025", as_of=date(2027, 1, 1))
    assert out["counts"]["expired_periods"] == 1 and out["counts"]["amendments"] == 0
    base = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    assert "b2ba" not in svc.apply_amendments(base, out)


def test_a_document_needing_a_decision_is_reported_and_not_filed(db):
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    db.table("client_sales_invoices").update({"status": "cancelled"}).eq("id", row["id"]).execute()
    data = _build()
    assert data["amendments"]["needs_decision"], data["amendments"]
    assert "b2ba" not in data["payload"]


# ── failure is loud, and the switch is the way out ───────────────────────────

def test_if_the_amendments_cannot_be_worked_out_the_build_fails_naming_the_switch(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("the walk is broken")
    monkeypatch.setattr(svc, "outstanding_amendments", boom)
    with pytest.raises(HTTPException) as e:
        _build()
    assert e.value.status_code == 500
    assert "switched off" in e.value.detail and "NOT built" in e.value.detail
    assert "the walk is broken" not in e.value.detail, "the exception text reached the CA"
    # ...and the deliberate way out still builds.
    assert _build(include_amendments=False)["amendments"] == {"included": False}


def test_a_failed_fold_never_falls_back_to_the_plain_return_silently(db, monkeypatch):
    """The negative of the silent fallback: no success response without the flag."""
    monkeypatch.setattr(svc, "outstanding_amendments",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(HTTPException):
        gst_router.gstr1_from_books_endpoint(
            gst_router.GSTR1FromBooksRequest(client_id=CLIENT, period="072025"), CALLER)
