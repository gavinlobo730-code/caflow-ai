"""
A deduction a CA types in is computed by the engine, not by the browser.

WHAT WAS WRONG (TDS-05)
    apps/web/app/tds/page.tsx carried its own section/rate table and its own
    arithmetic — `Math.round((grossPaise * tdsRate) / 100)` — and inserted the
    result straight into tds_deductions over PostgREST. There was no endpoint
    anywhere in apps/api that created such a row, so the browser was the only
    thing that could, and rbac() never ran on the path it used.

    The table was wrong in eight ways, not the two the finding named. Every one
    below is asserted against the engine rather than described:

      s.194C   flat 2%   -> 1% for an individual/HUF. Double.
      s.194D   flat 5%   -> 2% individual, 10% company. Wrong BOTH ways, and the
                            company case UNDER-deducts, which is the direction
                            that disallows the expenditure under s.40(a)(ia).
      s.194H   5%        -> 2%. Finance (No. 2) Act 2024. 2.5x.
      s.194Q   0.1% of the whole sum -> 0.1% of the EXCESS over Rs.50 lakh.
      s.194IA  offered at 1% -> not in the registry at all; the engine raises.
      s.192    selecting it left the PREVIOUS rate in the box, so salary was
               written at 10% into a register 26Q is assembled from.
      every section: no threshold test at all.
      every section: no FY aggregate, so nothing was ever credited under s.200.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user

FIRM = "F1"
CLIENT = "C1"
EXEC = {"id": "u2", "firm_id": FIRM, "role": "Executive",
        "email": "e@f1.test", "auth_user_id": "auth-exec"}
MANAGER = {"id": "u1", "firm_id": FIRM, "role": "Manager",
           "email": "m@f1.test", "auth_user_id": "auth-mgr"}
REVIEWER = {"id": "u3", "firm_id": FIRM, "role": "Reviewer",
            "email": "r@f1.test", "auth_user_id": "auth-rev"}

# 4th char P = individual, C = company (is_company_pan reads exactly that).
PAN_INDIVIDUAL = "AAAPA1234A"
PAN_COMPANY = "AAACA1234A"


@pytest.fixture
def app_db(monkeypatch):
    import routers.tds_workspace as mod
    db = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    app = FastAPI()
    app.include_router(mod.router)
    return app, db


def _client(app, user=EXEC):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _post(app, user=EXEC, **over):
    body = {"client_id": CLIENT, "deductee_name": "Acme Services",
            "deductee_pan": PAN_COMPANY, "section": "194J",
            "payment_amount_paise": 1_00_000_00,
            "transaction_date": "2026-06-15"}
    body.update(over)
    return _client(app, user).post("/api/tds-workspace/deductions", json=body)


# ── the eight wrong numbers, each asserted ───────────────────────────────────

def test_194c_charges_an_individual_one_percent_not_two(app_db):
    """The browser charged everyone the company rate."""
    app, db = app_db
    r = _post(app, section="194C", deductee_pan=PAN_INDIVIDUAL,
              payment_amount_paise=5_00_000_00)   # Rs.5,00,000, over both limbs
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["tds_rate_pct"] == 1.0, "s.194C is 1% for an individual/HUF"
    assert d["tds_paise"] == 5_00_000_00 // 100      # 1%
    # ...and the browser would have said:
    assert round(5_00_000_00 * 2 / 100) == 2 * d["tds_paise"]


def test_194d_is_two_percent_for_an_individual_and_ten_for_a_company(app_db):
    """The browser's flat 5% was wrong in both directions. The company case is
    the dangerous one: under-deducting disallows the whole expenditure."""
    app, db = app_db
    ind = _post(app, section="194D", deductee_pan=PAN_INDIVIDUAL,
                payment_amount_paise=1_00_000_00).json()["data"]
    assert ind["tds_rate_pct"] == 2.0

    db2 = _post(app, section="194D", deductee_pan=PAN_COMPANY,
                payment_amount_paise=1_00_000_00).json()["data"]
    assert db2["tds_rate_pct"] == 10.0, "s.194D is 10% for a domestic company"
    assert db2["tds_paise"] > round(1_00_000_00 * 5 / 100), (
        "the browser's 5% UNDER-deducted a company by half")


def test_194h_is_two_percent(app_db):
    """Finance (No. 2) Act 2024 cut it from 5%."""
    app, _ = app_db
    d = _post(app, section="194H", payment_amount_paise=1_00_000_00).json()["data"]
    assert d["tds_rate_pct"] == 2.0
    assert d["tds_paise"] == 2_000_00


def test_194q_is_charged_on_the_excess_not_the_whole_sum(app_db):
    """s.194Q(1): '0.1 per cent of such sum EXCEEDING fifty lakh rupees'."""
    app, _ = app_db
    d = _post(app, section="194Q", payment_amount_paise=60_00_000_00).json()["data"]
    assert d["tds_paise"] == 10_00_000_00 // 1000, "0.1% of the Rs.10L excess"
    assert d["tds_paise"] == 1_000_00
    # the browser charged 0.1% of the whole Rs.60L — six times as much
    assert round(60_00_000_00 * 0.1 / 100) == 6 * d["tds_paise"]


def test_a_section_the_engine_does_not_hold_is_refused(app_db):
    """s.194IA was in the old dropdown at 1% and is absent from the registry.
    Every row recorded under it was a number no backend path could reproduce."""
    app, db = app_db
    r = _post(app, section="194IA", payment_amount_paise=50_00_000_00)
    assert r.status_code == 422
    assert "194IA" in r.json()["detail"]
    assert db.rows("tds_deductions") == []


def test_below_the_threshold_nothing_is_deducted(app_db):
    """The browser applied a rate from the first rupee. s.194J's threshold is
    Rs.50,000, so a Rs.20,000 fee carries nothing."""
    app, _ = app_db
    d = _post(app, section="194J", payment_amount_paise=20_000_00).json()["data"]
    assert d["tds_paise"] == 0
    assert d["explain"]["applies"] is False
    assert d["explain"]["reason"] == "below_threshold"
    # The RATE stored is 0 too, not 10 — a s.203 certificate must not later
    # claim a rate was applied when nothing was deducted.
    assert d["tds_rate_pct"] == 0


def test_no_pan_floors_the_rate_at_twenty_percent(app_db):
    """IT Act s.206AA. The browser had no PAN awareness at all."""
    app, _ = app_db
    d = _post(app, section="194H", deductee_pan=None,
              payment_amount_paise=1_00_000_00).json()["data"]
    assert d["tds_rate_pct"] == 20.0
    assert d["tds_paise"] == 20_000_00


# ── the aggregate, which the browser had no notion of ────────────────────────

def test_the_fy_aggregate_triggers_and_credits_what_was_already_withheld(app_db):
    """Four Rs.30,000 fees under s.194J. Nothing crosses the Rs.50,000 single
    threshold, but the FY aggregate limb does — and once it does the charge is
    on the WHOLE aggregate, with s.200 crediting what earlier entries withheld.
    """
    app, db = app_db
    paid = []
    for n in range(4):
        d = _post(app, section="194J", payment_amount_paise=30_000_00,
                  transaction_date=f"2026-0{5 + n}-10").json()["data"]
        paid.append(d["tds_paise"])

    # 1st and 2nd: below the aggregate too (Rs.30k, Rs.60k > Rs.50k at the 2nd).
    assert paid[0] == 0, "first Rs.30,000 is under both limbs"
    # The one that crosses carries the year's tax on the whole aggregate...
    assert paid[1] == 6_000_00, "10% of the Rs.60,000 aggregate"
    # ...and each later one charges the new aggregate less what is already in.
    assert paid[2] == 3_000_00, "10% of Rs.90,000 less the Rs.6,000 already held"
    assert paid[3] == 3_000_00
    assert sum(paid) == 12_000_00, "10% of the Rs.1,20,000 year, once"


def test_the_aggregate_is_per_payee_and_per_section(app_db):
    """A second payee's payments must not push the first over a threshold."""
    app, _ = app_db
    _post(app, section="194J", deductee_pan=PAN_COMPANY,
          payment_amount_paise=45_000_00)
    other = _post(app, section="194J", deductee_pan="AAACB9999B",
                  deductee_name="Other Co",
                  payment_amount_paise=20_000_00).json()["data"]
    assert other["tds_paise"] == 0, "a stranger's payments are not this payee's"


def test_a_row_with_no_pan_is_never_aggregated_with_another(app_db):
    """Two unrelated payees both missing a PAN are not the same person."""
    app, _ = app_db
    _post(app, section="194H", deductee_pan=None, payment_amount_paise=15_000_00)
    second = _post(app, section="194H", deductee_pan=None,
                   deductee_name="Someone Else",
                   payment_amount_paise=15_000_00).json()["data"]
    assert second["explain"]["fy_prior_taxable_paise"] == 0


# ── what it stores, and what it says about itself ────────────────────────────

def test_the_quarter_is_the_one_vocabulary_the_bill_path_uses(app_db):
    """The screen used to write "Q1 (Apr-Jun)" and the bill path "Q3 2026-27" —
    three spellings on a column that had no CHECK, matched by nothing
    downstream. Migration 347 settles it on the schema's own: the bare quarter
    here, the year in financial_year, as on the other three TDS tables."""
    app, db = app_db
    _post(app, transaction_date="2026-11-20", payment_amount_paise=1_00_000_00)
    from services.tds_register_service import fy_label, fy_quarter
    from datetime import date
    row = db.rows("tds_deductions")[0]
    assert row["quarter"] == fy_quarter(date(2026, 11, 20)) == "Q3"
    assert row["financial_year"] == fy_label(date(2026, 11, 20)) == "2026-27"


def test_the_unified_aggregate_gap_is_reported_on_every_row(app_db):
    """The aggregate counts hand-entered rows only; purchase bills for the same
    payee sit in a register it does not read. Said out loud rather than left to
    be discovered, because the number is right about what it saw."""
    app, _ = app_db
    d = _post(app, payment_amount_paise=1_00_000_00).json()["data"]
    from domain.tds.manual_register import GAP_REGISTERS_NOT_UNIFIED
    assert GAP_REGISTERS_NOT_UNIFIED in d["explain"]["gaps"]
    assert any("purchase bill" in m.lower() for m in d["explain"]["gap_messages"])


def test_the_request_cannot_carry_a_rate_or_an_amount(app_db):
    """The engine's answers are not the caller's to supply. A request model
    that accepted them would keep the browser's arithmetic alive behind an
    endpoint that looks authoritative."""
    import routers.tds_workspace as mod
    fields = set(mod.CreateDeductionRequest.model_fields)
    assert not fields & {"tds_rate_pct", "tds_paise", "tds_rate_bps",
                         "rate", "rate_pct"}


# ── who may do it ────────────────────────────────────────────────────────────

def test_a_reviewer_cannot_record_a_deduction(app_db):
    """tds:compute is Executive+. This is the app-layer half of migration 345."""
    app, db = app_db
    r = _post(app, user=REVIEWER)
    assert r.status_code == 403
    assert db.rows("tds_deductions") == []


def test_deleting_needs_manager_not_executive(app_db):
    """tds:write, matching the DELETE tier migration 345 gives the table:
    removing a statutory register row is not data entry."""
    app, db = app_db
    made = _post(app).json()["data"]
    assert _client(app, EXEC).delete(
        f"/api/tds-workspace/deductions/{made['id']}").status_code == 403
    assert _client(app, MANAGER).delete(
        f"/api/tds-workspace/deductions/{made['id']}").status_code == 200
    assert db.rows("tds_deductions") == []


def test_a_bill_sourced_row_is_not_editable_here(app_db):
    """sync_for_bill owns it and rebuilds it on every receive, so an edit would
    look like it worked and silently revert."""
    app, db = app_db
    db.seed("tds_deductions", {
        "id": "D9", "firm_id": FIRM, "client_id": CLIENT, "purchase_bill_id": "B1",
        "section": "194J", "deductee_name": "V", "deductee_pan": PAN_COMPANY,
        "payment_amount_paise": 1_00_000_00, "tds_paise": 10_000_00,
        "tds_rate_pct": 10, "transaction_date": "2026-06-15"})

    r = _client(app, EXEC).patch("/api/tds-workspace/deductions/D9",
                                 json={"payment_amount_paise": 1})
    assert r.status_code == 200 and r.json()["success"] is False
    assert "purchase bill" in r.json()["error"]
    assert db.rows("tds_deductions")[0]["payment_amount_paise"] == 1_00_000_00


def test_correcting_a_typed_row_re_runs_the_engine(app_db):
    """And excludes the row itself from its own aggregate."""
    app, db = app_db
    made = _post(app, section="194H", payment_amount_paise=1_00_000_00).json()["data"]
    assert made["tds_paise"] == 2_000_00

    fixed = _client(app, EXEC).patch(
        f"/api/tds-workspace/deductions/{made['id']}",
        json={"payment_amount_paise": 2_00_000_00}).json()["data"]
    assert fixed["tds_paise"] == 4_000_00, "2% of the corrected amount, once"
    assert fixed["explain"]["fy_prior_taxable_paise"] == 0, (
        "a row must not aggregate with itself")


def test_another_firms_row_is_not_found(app_db):
    app, db = app_db
    db.seed("tds_deductions", {"id": "D8", "firm_id": "F2", "client_id": "C9",
                               "section": "194J", "deductee_name": "X",
                               "payment_amount_paise": 1, "tds_paise": 0,
                               "tds_rate_pct": 0, "transaction_date": "2026-06-15"})
    r = _client(app, MANAGER).delete("/api/tds-workspace/deductions/D8")
    assert r.json()["success"] is False
    assert len(db.rows("tds_deductions")) == 1
