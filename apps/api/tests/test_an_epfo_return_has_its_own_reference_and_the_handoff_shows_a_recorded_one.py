"""An EPFO return and its challan carry different references, and the hand-off can show a recorded return (POST-A-518, migration 769).

WHAT WAS WRONG
    1. The hand-off asked the CA for "the TRRN the portal gives back, and the date you filed" as ONE record. On EPFO's revamped
       system (User Manual for the Re-engineered ECR, v3.0, read 19-11-2026) the RETURN gets a Return File ID when the file passes
       its checks, the employer approves the return statement, and only then does the portal prepare the challan, which gets its
       TRRN when it is finalised and is then paid through a bank: two acts, two references. The form's box was labelled TRRN and
       the table's column said it was the return's.
    2. `run_handoff` built the "recorded as filed" row with `f.get("wage_month")` over the dataclasses `read_filings` returns,
       which have no `.get`. It raised AttributeError for a client the moment ANY return was recorded for it, so the panel that
       exists to show a settled month could never show one, and the endpoint answered 500 for every run of that client.

WHAT THE FIX DOES
    Migration 769 adds `epfo_ecr_filings.return_file_id`; the record form asks for the Return File ID and writes it there; `trrn`
    keeps its name and now means the challan's. The hand-off reads the month's settled return as a plain row, and only when it
    is approved and the month needs nothing further, so a Regular that is submitted but not approved, or a month that still
    needs a Supplementary, keeps the form on the screen. The panel says the payment is a second act and that this product
    records the return and not the payment.

NEGATIVE CONTROLS (each mutant was run and these fail)
    * write the Return File ID into `trrn`               — the stored-row tests fail
    * go back to `f.get` over the dataclasses            — every hand-off test after a recording raises
    * set `recorded` whatever the month still needs      — the submitted-only and the supplementary tests fail
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

import routers.payroll as pr
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-RFI518"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pr])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM, "client_id": "CLI",
                                       "payroll_enabled": True})
    d.seed("payroll_employees", {
        "id": "e-01", "firm_id": FIRM, "client_id": "CLI", "name": "Asha Kumar",
        "uan": "100200300401", "basic_paise": 15_000_00, "hra_percent": 0.0,
        "da_percent": 0.0, "other_allowances_paise": 0, "lta_paise": 0,
        "medical_paise": 0, "special_allowance_paise": 0, "pf_applicable": True,
        "eps_eligible": True, "esi_applicable": False, "pt_applicable": False,
        "is_active": True, "status": "active"})
    return d


def _finalised_run(db) -> str:
    out = pr.create_run(pr.PayrollRunIn(client_id="CLI", month="2026-08"), CALLER)
    assert out["success"] is True
    run_id = out["data"]["id"]
    for row in db.rows("payroll_runs"):
        if row["id"] == run_id:
            row["status"] = "finalized"
    return run_id


def _record(run_id: str, **over):
    body = dict(return_type="regular", status="approved",
                submitted_on="2026-09-10", approved_on="2026-09-11",
                return_file_id="250100001024")
    body.update(over)
    out = pr.record_ecr_filed(run_id, pr.ECRFiledIn(**body), CALLER)
    assert out["success"] is True
    return out["data"]["filing"]


def _epf_panel(run_id: str) -> dict:
    resp = pr.run_handoff(run_id=run_id, current_user=CALLER)
    assert resp["success"] is True
    return next(o for o in resp["data"]["obligations"] if o["key"] == "epf")


# ── the record ──────────────────────────────────────────────────────────────

def test_the_return_file_id_is_stored_as_the_returns_own_reference(db):
    filing = _record(_finalised_run(db))
    stored = db.rows("epfo_ecr_filings")[0]
    assert stored["return_file_id"] == "250100001024"
    assert "trrn" not in stored, "the challan's TRRN is not the return's reference and is not written unless it is given"
    assert filing["return_file_id"] == "250100001024"


def test_a_challan_trrn_recorded_beside_it_is_kept_apart(db):
    _record(_finalised_run(db), trrn="250113000000438")
    stored = db.rows("epfo_ecr_filings")[0]
    assert (stored["return_file_id"], stored["trrn"]) == ("250100001024", "250113000000438")


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_reference_writes_nothing(db, blank):
    _record(_finalised_run(db), return_file_id=blank)
    assert "return_file_id" not in db.rows("epfo_ecr_filings")[0]


def test_the_reference_is_trimmed(db):
    _record(_finalised_run(db), return_file_id="  250100001024  ")
    assert db.rows("epfo_ecr_filings")[0]["return_file_id"] == "250100001024"


def test_a_reference_far_longer_than_any_the_portal_issues_is_refused():
    with pytest.raises(ValidationError):
        pr.ECRFiledIn(return_file_id="9" * 65)


def test_the_list_of_recorded_returns_carries_the_return_file_id(db):
    run_id = _finalised_run(db)
    _record(run_id)
    resp = pr.client_ecr_sequence(client_id="CLI", current_user=CALLER)
    assert resp["success"] is True
    assert resp["data"]["filings"][0]["return_file_id"] == "250100001024"


# ── the hand-off after a recording (it raised AttributeError) ─────────────────

def test_the_handoff_no_longer_raises_once_a_return_is_recorded(db):
    run_id = _finalised_run(db)
    _record(run_id)
    panel = _epf_panel(run_id)         # raised AttributeError before: 'RecordedFiling' object has no attribute 'get'
    assert panel["key"] == "epf"


def test_a_settled_month_shows_its_return_with_its_reference(db):
    run_id = _finalised_run(db)
    _record(run_id)
    recorded = _epf_panel(run_id)["recorded"]
    assert recorded is not None
    assert recorded["return_file_id"] == "250100001024"
    assert recorded["return_type"] == "regular"
    assert recorded["status"] == "approved"


def test_a_return_submitted_and_not_approved_keeps_the_form_on_the_screen(db):
    """A Regular that is submitted but not approved still blocks the next month, and the form that records the approval has to
    stay until it is."""
    run_id = _finalised_run(db)
    _record(run_id, status="submitted", approved_on=None)
    assert _epf_panel(run_id)["recorded"] is None


def test_a_month_that_still_needs_a_supplementary_keeps_the_form_on_the_screen(db):
    run_id = _finalised_run(db)
    _record(run_id)
    for row in db.rows("epfo_ecr_filings"):
        row["members"] = []                 # the approved Regular carries nobody, so this month's member is new
    panel = _epf_panel(run_id)
    assert panel["record_options"] == ["supplementary"]
    assert panel["recorded"] is None


def test_a_later_return_that_is_only_submitted_is_not_the_one_shown_as_settled(db):
    """The panel shows the latest APPROVED return. A Revised submitted afterwards and not yet approved is in flight, and
    showing it as the month's record would put an unapproved return where the approved Regular is."""
    run_id = _finalised_run(db)
    _record(run_id)
    _record(run_id, return_type="revised", status="submitted", approved_on=None,
            submitted_on="2026-09-20", return_file_id="250100001099")
    recorded = _epf_panel(run_id)["recorded"]
    assert recorded is not None
    assert (recorded["return_type"], recorded["return_file_id"]) == ("regular", "250100001024")


def test_a_retracted_return_is_not_shown_as_recorded(db):
    run_id = _finalised_run(db)
    _record(run_id)
    for row in db.rows("epfo_ecr_filings"):
        row["deleted_at"] = "2026-09-12T00:00:00+00:00"
    assert _epf_panel(run_id)["recorded"] is None


# ── what the panel says ─────────────────────────────────────────────────────

def test_the_panel_asks_for_the_return_and_says_the_payment_is_a_second_act(db):
    panel = _epf_panel(_finalised_run(db))
    assert "Return File ID" in panel["record_back"]
    assert "TRRN" not in panel["record_back"], "the TRRN belongs to the challan, which this panel does not record"
    second = [w for w in panel["warnings"] if w.startswith("Paying is a second act")]
    assert len(second) == 1
    assert "TRRN" in second[0] and "records the return here and not the payment" in second[0]


def test_the_panel_cites_the_2026_scheme_and_not_the_replaced_one(db):
    panel = _epf_panel(_finalised_run(db))
    assert "Employees' Provident Funds Scheme, 2026" in panel["statute"]
    assert "1952" not in panel["statute"]
