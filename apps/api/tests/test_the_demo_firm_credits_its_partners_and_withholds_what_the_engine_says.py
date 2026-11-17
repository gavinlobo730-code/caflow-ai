"""The demo partnership credits its partners' remuneration, and the tax it withholds under section 194T is the engine's (PRE-A-004).

What was wrong: the fixture's partnership said it demonstrated "section 184 partner remuneration, section 194T on a partner
payment", and the seeder wrote neither: no partner, no remuneration, no deduction, so the TDS register, the deposit worksheet
and the 26Q carried no section 194T row and the firm's profit and loss showed no remuneration at all.

What the seeder does now (`seed_demo_firm._partner_remuneration`): for each quarter whose months are posted, it records each
partner's remuneration on the TDS screen's own door (which asks the engine for the tax and takes no rate), and posts a journal,
Dr Remuneration to Partners for the whole, Cr the partner's current account with the remuneration less the tax, Cr TDS Payable
with the tax the door answered. The payroll and TDS stages cannot run in mock mode, so the bodies are read off the recorder the
body-shape test uses; the tax the TDS door answers in mock mode is asked of the real door below.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from domain.demo import fixture, year_estimate

FY = "2025-26"
FIRM = fixture.build(FY)
FIRMS_WITH_PARTNERS = [c for c in FIRM.clients if c.partners]


def test_the_partnership_and_only_the_partnership_has_partners():
    assert [c.entity_type for c in FIRMS_WITH_PARTNERS] == ["Partnership"]
    assert all(not c.partners for c in FIRM.clients if c.entity_type != "Partnership")


def test_a_partner_is_a_person_with_a_pan_of_their_own():
    import re
    for c in FIRMS_WITH_PARTNERS:
        pans = [p.pan for p in c.partners]
        assert len(set(pans)) == len(pans) >= 2
        for pan in pans:
            assert re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan) and pan[3] == "P", pan


def test_three_quarters_are_credited_and_none_in_the_month_still_in_draft():
    draft = fixture.draft_month(FY)
    for c in FIRMS_WITH_PARTNERS:
        credits = fixture.partner_remuneration_credits(c, FY)
        days = sorted({cr.on for cr in credits})
        assert days == ["2025-06-30", "2025-09-30", "2025-12-31"]
        assert all(cr.on[:7] != draft for cr in credits)
        assert len(credits) == 3 * len(c.partners)
        assert {cr.amount_paise for cr in credits} == {p.remuneration_per_quarter_paise for p in c.partners}


def test_a_client_with_no_partners_credits_nothing():
    assert all(fixture.partner_remuneration_credits(c, FY) == () for c in FIRM.clients if not c.partners)


def test_the_year_estimate_charges_the_remuneration_and_the_firm_is_still_in_profit():
    for c in FIRMS_WITH_PARTNERS:
        y = year_estimate.estimate(c, FY)
        assert y.partner_remuneration_paise == sum(cr.amount_paise for cr in fixture.partner_remuneration_credits(c, FY))
        assert y.partner_remuneration_paise > 0
        assert y.profit_after_the_queue_paise > 0


# ── The seeder's bodies ─────────────────────────────────────────────────────────

def _recorded_run():
    spec = importlib.util.spec_from_file_location(
        "body_test", Path(__file__).resolve().parent / "test_every_body_the_seeder_sends_is_one_its_door_accepts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from main import app
    seeder = mod._seeder()
    rec = mod._Recorder(mod._doors(app))
    seeder.seed(rec, fixture.build(), add_to_existing=False)
    assert not rec.invalid, rec.invalid
    assert not rec.unmatched, rec.unmatched
    return rec


@pytest.fixture(scope="module")
def run():
    return _recorded_run()


def _deductions(run):
    return [(i, b) for i, (m, p, b) in enumerate(run.requests) if (m, p) == ("POST", "/api/tds-workspace/deductions")]


def _remuneration_journals(run):
    return [(i, b) for i, (m, p, b) in enumerate(run.requests)
            if (m, p) == ("POST", "/api/accounting/journal") and b["reference_no"].startswith("SEED-PARTNER-REM-")]


def test_every_credit_is_recorded_as_a_194t_deduction_with_no_rate_or_tax_of_the_seeders_own(run):
    credits = [cr for c in FIRMS_WITH_PARTNERS for cr in fixture.partner_remuneration_credits(c, FY)]
    deductions = _deductions(run)
    assert len(deductions) == len(credits)
    for (_, b), cr in zip(deductions, credits, strict=True):
        assert b["section"] == "194T"
        assert (b["deductee_name"], b["deductee_pan"]) == (cr.partner.name, cr.partner.pan)
        assert (b["payment_amount_paise"], b["transaction_date"]) == (cr.amount_paise, cr.on)
        assert not {"tds_paise", "tds_rate_pct", "rate_bps", "vendor_id"} & set(b), b


def test_each_journal_follows_its_deduction_balances_and_withholds_exactly_what_the_door_answered(run):
    deductions, journals = _deductions(run), _remuneration_journals(run)
    assert len(journals) == len(deductions)
    for (i, d), (j, jb) in zip(deductions, journals, strict=True):
        assert i < j, "a journal was posted before the deduction whose tax it carries"
        debits = sum(ln["debit_paise"] for ln in jb["lines"])
        credits = sum(ln["credit_paise"] for ln in jb["lines"])
        assert debits == credits == d["payment_amount_paise"]
        tax_lines = [ln for ln in jb["lines"] if "194T" in ln["narration"]]
        assert [ln["credit_paise"] for ln in tax_lines] == [3_000_00], "the TDS credit is not the door's answer"
        assert jb["entry_date"] == d["transaction_date"] and jb["status"] == "posted"


def test_the_ledgers_are_created_on_the_clients_own_chart_with_codes_the_standard_chart_does_not_use(run):
    from services.coa_seed_service import STANDARD_COA
    standard = {code for code, *_ in STANDARD_COA}
    made = [(p, b) for m, p, b in run.requests if m == "POST" and p.startswith("/api/accounting/accounts?client_id=")]
    assert len(made) == sum(1 + len(c.partners) for c in FIRMS_WITH_PARTNERS)
    assert not {b["code"] for _, b in made} & standard
    assert {b["account_type"] for _, b in made} == {"Expense", "Equity"}


def test_the_remuneration_is_posted_before_the_returns_that_would_lock_its_months_and_before_the_tds_stage(run):
    journals = [j for j, _ in _remuneration_journals(run)]
    assert journals
    gst = [i for i, (m, p, _) in enumerate(run.requests) if p in ("/api/gst/gstr1/from-books", "/api/gst/gstr3b/from-books")]
    challans = [i for i, (m, p, _) in enumerate(run.requests) if (m, p) == ("POST", "/api/tds-workspace/challans")]
    # The client's own GST returns and challans come after; the partnership is one client, so compare inside its stretch.
    clients = [i for i, (m, p, _) in enumerate(run.requests) if (m, p) == ("POST", "/api/clients")]
    start = max(c for c in clients if c < journals[0])
    end = min([c for c in clients if c > journals[-1]] or [len(run.requests)])
    assert all(j < g for j in journals for g in gst if start < g < end)
    assert any(start < g < end for g in gst), "the partnership files no GST return in the seed"
    assert all(j < ch for j in journals for ch in challans if start < ch < end)


def test_the_tds_door_answers_a_partners_remuneration_with_the_engines_tax_in_mock_mode(dev_header_auth):
    """The recorder answers a fixed figure; here the real door is asked, with the body the seeder sends, and it must answer an
    integer tax no larger than the remuneration, which is all the seeder relies on."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    c = FIRMS_WITH_PARTNERS[0]
    made = client.post("/api/clients", json={"client_name": c.name, "entity_type": c.entity_type,
                                             "pan": c.pan, "gstin": c.gstin, "state_code": c.state_code})
    assert made.status_code < 300, made.text
    # The id where the seeder reads it, by the seeder's own reader.
    spec = importlib.util.spec_from_file_location("seed_demo_firm", Path(__file__).resolve().parents[1] / "scripts" / "seed_demo_firm.py")
    seeder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seeder)
    client_id = seeder._id(made.json())
    cr = fixture.partner_remuneration_credits(c, FY)[0]
    got = client.post("/api/tds-workspace/deductions", json={
        "client_id": client_id, "deductee_name": cr.partner.name, "deductee_pan": cr.partner.pan, "section": "194T",
        "payment_amount_paise": cr.amount_paise, "transaction_date": cr.on,
        "nature_of_payment": "Remuneration to a partner of the firm"})
    assert got.status_code == 200, got.text
    data = got.json()["data"]
    assert isinstance(data["tds_paise"], int) and 0 < data["tds_paise"] < cr.amount_paise, data


def test_the_mock_chart_door_creates_an_account(dev_header_auth):
    """The mock branch of `POST /api/accounting/accounts` handed the store the model's own keys and answered a 500."""
    from fastapi.testclient import TestClient
    from main import app
    got = TestClient(app).post("/api/accounting/accounts", json={"name": "Remuneration to Partners", "code": "5801",
                                                                 "account_type": "Expense"})
    assert got.status_code == 200, got.text
    assert got.json()["data"]["account_name"] == "Remuneration to Partners"
    assert got.json()["data"]["account_code"] == "5801"
