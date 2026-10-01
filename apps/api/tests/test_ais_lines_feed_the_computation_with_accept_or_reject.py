"""AIS figures feed the computation, a line at a time, with accept or reject
(TDS-INCOME-TAX-10).

WHAT WAS WRONG
    The AIS import is built and keeps its readings honest — an unreadable amount
    is a problem, never a zero, and it deliberately computes no difference — but
    the computation screen read only the 26AS claim. A CA who had uploaded what
    the department already knows about the client still copied it into the
    computation by hand.

WHAT IS ASSERTED
    * salary, interest and dividend are offered as lines with every payer that
      makes each up, and each feeds ONE named box;
    * an accepted line is APPLIED to an empty box (`accept_paise`), a rejected
      one is not, and a typed figure that differs from the statement is FLAGGED
      with the difference and never replaced;
    * a decision is recorded on the figure it was made on, so a fresh statement
      that changes the figure shows the decision as STALE and does not apply it;
    * a sale of securities, a property sale, rent, a foreign remittance and
      anything unclassified are refused a prefill, each for its own reason;
    * a statement that parsed with problems says its figures may be short, and a
      line added by hand is labelled as such;
    * nothing is applied by the server, no tax is computed, and the writes ask
      for the compute permission while the read asks for read.

NEGATIVE CONTROL
    There was no suggestion before. With the figure dropped from the decision the
    stale test fails; with a rejected line still counted in the statement figure
    the all-rejected test fails; with `typed` replaced by the accepted figure the
    flag-and-keep test fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from core.permissions import PERMISSIONS, can
from routers import ais as ais_router
from services import ais_computation_service as acs
from services import ais_service

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"
FY = "2025-26"          # assessed in AY 2026-27
AY = "2026-27"
CALLER = {"id": USER, "firm_id": FIRM, "role": "Executive"}

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ais_service._reset_mock_state()
    acs._reset_mock_state()
    monkeypatch.setattr(ais_router, "assert_client_access", lambda u, c: None)
    yield
    ais_service._reset_mock_state()
    acs._reset_mock_state()


def statement(*lines) -> str:
    cats = []
    for source, nature, payer, amount, tds in lines:
        cats.append({
            "informationSource": source,
            "informationDescription": [
                {"label": "Nature of transaction", "value": nature},
                {"label": "Deductor", "value": payer},
            ],
            "amount": amount, "tdsAmount": tds,
        })
    return json.dumps({"AnnualInformationStatement": {
        "taxpayerInfo": {"pan": "ABCPK1234F", "name": "Kaveri K"},
        "aisInformation": {"aisSubInformationCategory": cats},
    }})


FULL = statement(
    ("Zenith Systems Pvt Ltd", "TDS on salary", "Zenith Systems Pvt Ltd", "1250000", "125000"),
    ("Orbit Tech", "TDS on salary", "Orbit Tech", "400000", "20000"),
    ("HDFC Bank Ltd", "Interest from savings bank", "HDFC Bank Ltd", "45000", "0"),
    ("SBI", "Interest from deposit", "SBI", "30000", "3000"),
    ("Infosys Ltd", "Dividend income", "Infosys Ltd", "12000", "0"),
    ("NSE Clearing", "Sale of securities", "Kotak Securities", "820000", "0"),
    ("Registrar", "Sale of immovable property", "Sub-Registrar", "5000000", "0"),
    ("Tenant Co", "Rent received", "Tenant Co", "240000", "24000"),
    ("Bank", "Foreign remittance", "Bank", "100000", "0"),
)


def upload(raw=FULL):
    return ais_service.upload_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY, raw=raw,
        file_name="AIS.json", uploaded_by=USER)


def ask(typed=None):
    return acs.suggestions(firm_id=FIRM, client_id=CLIENT, fy=FY, typed=typed or {})


def decide(key, decision):
    return acs.decide(firm_id=FIRM, client_id=CLIENT, fy=FY, line_key=key,
                      decision=decision, user_id=USER)


def line(res, key):
    return next(l for l in res["lines"] if l["line_key"] == key)


def target(res, name):
    return next(t for t in res["targets"] if t["target"] == name)


def rs(r):
    return r * 100


# ══ the lines ════════════════════════════════════════════════════════════════

def test_salary_interest_and_dividend_are_offered_with_every_payer_behind_each():
    upload()
    res = ask()
    assert res["has_statement"] and res["assessment_year"] == AY
    assert {l["line_key"] for l in res["lines"]} == {"salary", "interest", "dividend"}
    salary = line(res, "salary")
    assert salary["amount_paise"] == rs(1_650_000) and salary["tds_paise"] == rs(145_000)
    assert [s["payer"] for s in salary["sources"]] == ["Zenith Systems Pvt Ltd", "Orbit Tech"]
    assert [s["amount_paise"] for s in salary["sources"]] == [rs(1_250_000), rs(400_000)]
    interest = line(res, "interest")
    assert interest["amount_paise"] == rs(75_000)
    assert {s["payer"] for s in interest["sources"]} == {"HDFC Bank Ltd", "SBI"}
    assert line(res, "dividend")["amount_paise"] == rs(12_000)


def test_each_line_names_the_one_box_it_feeds_and_interest_and_dividend_share_one():
    upload()
    res = ask()
    assert line(res, "salary")["target"] == "gross_salary_paise"
    assert line(res, "interest")["target"] == line(res, "dividend")["target"] == "other_income_paise"
    other = target(res, "other_income_paise")
    assert other["ais_paise"] == rs(75_000) + rs(12_000)


def test_the_statement_for_the_assessment_year_of_the_financial_year_is_the_one_read():
    """FY 2025-26 is assessed in AY 2026-27 (§2(9) with §3)."""
    upload()
    assert acs.suggestions(firm_id=FIRM, client_id=CLIENT, fy="2024-25")["has_statement"] is False
    assert ask()["has_statement"] is True


def test_no_statement_says_what_to_do_and_offers_nothing():
    res = ask()
    assert res["has_statement"] is False and res["lines"] == []
    assert any("Upload the AIS" in g for g in res["gaps"])


# ══ the refused lines, each for its own reason ═══════════════════════════════

def test_a_sale_a_rent_and_a_remittance_are_refused_a_prefill_with_different_reasons():
    upload()
    res = ask()
    refused = {r["bucket"]: r for r in res["refused"]}
    assert set(refused) == {"Stock Sale", "Property Sale", "Rent Received", "Foreign Remittance"}
    assert refused["Stock Sale"]["amount_paise"] == rs(820_000)
    assert "consideration, not a gain" in refused["Stock Sale"]["reason"]
    assert "consideration, not a gain" in refused["Property Sale"]["reason"]
    assert "house-property worksheet" in refused["Rent Received"]["reason"]
    assert "not income by itself" in refused["Foreign Remittance"]["reason"]
    assert len({r["reason"] for r in res["refused"]}) == 4, "the reasons are not interchangeable"


def test_a_refused_bucket_is_not_a_line_and_cannot_be_decided():
    upload()
    assert "Stock Sale" not in {l["bucket"] for l in ask()["lines"]}
    for key in ("stock_sale", "rent", "other"):
        with pytest.raises(acs.DecisionRefused):
            decide(key, "accepted")


# ══ accept and reject ════════════════════════════════════════════════════════

def test_a_line_starts_as_suggested_and_nothing_is_applied_until_it_is_accepted():
    upload()
    res = ask()
    assert line(res, "salary")["state"] == "suggested"
    assert target(res, "gross_salary_paise")["accept_paise"] == 0


def test_an_accepted_line_is_what_an_empty_box_may_be_filled_with():
    upload()
    decide("salary", "accepted")
    decide("interest", "accepted")
    res = ask()
    assert line(res, "salary")["state"] == "accepted"
    assert target(res, "gross_salary_paise")["accept_paise"] == rs(1_650_000)
    # Interest accepted, dividend still only suggested: the box gets interest alone.
    assert target(res, "other_income_paise")["accept_paise"] == rs(75_000)
    decide("dividend", "accepted")
    assert target(ask(), "other_income_paise")["accept_paise"] == rs(87_000)


def test_a_rejected_line_is_not_applied_and_is_taken_out_of_the_statement_figure():
    upload()
    decide("dividend", "rejected")
    res = ask()
    assert line(res, "dividend")["state"] == "rejected"
    other = target(res, "other_income_paise")
    assert other["accept_paise"] == 0
    assert other["ais_paise"] == rs(75_000), "the rejected line no longer counts"


def test_where_every_line_for_a_box_is_rejected_a_typed_figure_is_not_flagged_against_nothing():
    upload()
    decide("interest", "rejected")
    decide("dividend", "rejected")
    other = target(ask({"other_income_paise": rs(500_000)}), "other_income_paise")
    assert other["ais_paise"] is None
    assert other["differs"] is False and other["difference_paise"] is None


def test_a_decision_can_be_taken_back():
    upload()
    decide("salary", "accepted")
    assert decide("salary", "undecided")["state"] == "suggested"
    assert line(ask(), "salary")["state"] == "suggested"


def test_a_decision_is_for_a_line_the_statement_carries():
    upload(statement(("HDFC Bank Ltd", "Interest from savings bank", "HDFC Bank Ltd", "45000", "0")))
    with pytest.raises(acs.DecisionRefused) as e:
        decide("salary", "accepted")
    assert "no Salary line" in str(e.value)


def test_a_decision_must_be_one_of_the_three():
    upload()
    with pytest.raises(acs.DecisionRefused):
        decide("salary", "maybe")


# ══ a typed figure is flagged and kept ═══════════════════════════════════════

def test_a_differing_typed_figure_is_flagged_with_the_difference_and_kept():
    """Typed ₹16,00,000 against the statement's ₹16,50,000: flagged, short by
    ₹50,000 — and the server holds no figure to replace it with."""
    upload()
    decide("salary", "accepted")
    t = target(ask({"gross_salary_paise": rs(1_600_000)}), "gross_salary_paise")
    assert t["typed_paise"] == rs(1_600_000)
    assert t["differs"] is True
    assert t["difference_paise"] == -rs(50_000)
    assert t["ais_paise"] == rs(1_650_000)


def test_a_typed_figure_that_agrees_is_not_flagged():
    upload()
    t = target(ask({"gross_salary_paise": rs(1_650_000)}), "gross_salary_paise")
    assert t["differs"] is False and t["difference_paise"] == 0


def test_an_untyped_box_is_not_the_same_as_a_typed_zero():
    upload()
    untyped = target(ask(), "gross_salary_paise")
    assert untyped["typed_paise"] is None and untyped["differs"] is False
    zero = target(ask({"gross_salary_paise": 0}), "gross_salary_paise")
    assert zero["typed_paise"] == 0 and zero["differs"] is True


def test_the_statement_is_compared_even_before_a_line_is_decided():
    """A CA reviewing a suggestion wants to see their own figure beside it
    BEFORE they accept."""
    upload()
    t = target(ask({"gross_salary_paise": rs(1_000_000)}), "gross_salary_paise")
    assert t["differs"] is True and t["accept_paise"] == 0


# ══ a decision is made on a figure ═══════════════════════════════════════════

def test_a_fresh_statement_that_changes_the_figure_shows_the_decision_as_stale_and_does_not_apply_it():
    upload()
    decide("interest", "accepted")
    # A re-downloaded statement: SBI interest is now 40,000 not 30,000.
    upload(statement(
        ("Zenith Systems Pvt Ltd", "TDS on salary", "Zenith Systems Pvt Ltd", "1250000", "125000"),
        ("HDFC Bank Ltd", "Interest from savings bank", "HDFC Bank Ltd", "45000", "0"),
        ("SBI", "Interest from deposit", "SBI", "40000", "4000"),
    ))
    res = ask()
    i = line(res, "interest")
    assert i["amount_paise"] == rs(85_000)
    assert i["state"] == "accepted_stale"
    assert i["decided_amount_paise"] == rs(75_000)
    assert target(res, "other_income_paise")["accept_paise"] == 0, "a stale acceptance is not applied"
    # Deciding again records the figure the CA is now looking at.
    assert decide("interest", "accepted")["state"] == "accepted"
    assert target(ask(), "other_income_paise")["accept_paise"] == rs(85_000)


def test_a_rejection_is_stale_in_the_same_way():
    upload()
    decide("dividend", "rejected")
    upload(statement(("Infosys Ltd", "Dividend income", "Infosys Ltd", "20000", "0")))
    assert line(ask(), "dividend")["state"] == "rejected_stale"


def test_the_figure_the_decision_was_made_on_is_what_is_stored():
    upload()
    decide("salary", "accepted")
    row = acs._decisions_for(FIRM, CLIENT, AY)[0]
    assert row["amount_paise"] == rs(1_650_000) and row["decided_by"] == USER


def test_a_decision_is_one_clients_and_one_years():
    upload()
    decide("salary", "accepted")
    assert acs._decisions_for(FIRM, "another-client", AY) == []
    assert acs._decisions_for("another-firm", CLIENT, AY) == []
    assert acs._decisions_for(FIRM, CLIENT, "2025-26") == []


# ══ what travels with the statement ══════════════════════════════════════════

def test_a_statement_that_parsed_with_problems_says_its_figures_may_be_short():
    upload(statement(
        ("Zenith Systems Pvt Ltd", "TDS on salary", "Zenith Systems Pvt Ltd", "1250000", "125000"),
        ("SBI", "Interest from deposit", "SBI", "not-a-number", "0"),
    ))
    res = ask()
    assert any("SHORT" in g and "problem" in g for g in res["gaps"]), res["gaps"]
    assert line(res, "salary")["amount_paise"] == rs(1_250_000)


def test_a_line_added_by_hand_is_labelled_as_not_the_departments():
    up = upload()
    ais_service.add_manual_record(
        firm_id=FIRM, client_id=CLIENT, upload_id=up["upload"]["id"],
        transaction_type="Interest", payer="Post Office", amount_paise=rs(5_000),
        tds_deducted_paise=0, information_label="Post office savings")
    res = ask()
    sources = line(res, "interest")["sources"]
    assert {s["source"] for s in sources} == {"json", "manual"}
    assert any("added by hand" in g for g in res["gaps"])


def test_no_tax_is_computed_and_nothing_is_applied_by_the_server():
    src = Path(acs.__file__).read_text(encoding="utf-8")
    for needle in ("rates_for", "slab_tax", "itr_engine", "* 30 //", "tax_impact"):
        assert needle not in src
    upload()
    res = ask()
    assert "tax" not in " ".join(res.keys()).replace("targets", "")


# ══ the door ═════════════════════════════════════════════════════════════════

def test_the_read_endpoint_serves_the_lines_and_carries_the_typed_figures():
    upload()
    d = ais_router.computation_lines(
        CLIENT, FY, typed_gross_salary_paise=rs(1_600_000), typed_other_income_paise=None,
        current_user=CALLER)["data"]
    assert target(d, "gross_salary_paise")["differs"] is True
    assert target(d, "other_income_paise")["typed_paise"] is None


def test_the_decision_endpoint_records_and_a_refusal_is_a_400_with_the_sentence():
    upload()
    out = ais_router.decide_computation_line(
        "salary", ais_router.ComputationDecisionRequest(
            client_id=CLIENT, financial_year=FY, decision="accepted"), CALLER)["data"]
    assert out["state"] == "accepted"
    with pytest.raises(HTTPException) as e:
        ais_router.decide_computation_line(
            "stock_sale", ais_router.ComputationDecisionRequest(
                client_id=CLIENT, financial_year=FY, decision="accepted"), CALLER)
    assert e.value.status_code == 400 and "not a line the computation takes" in e.value.detail


def test_reading_asks_for_read_and_deciding_asks_for_compute():
    def action_of(route_name):
        for r in ais_router.router.routes:
            if r.name == route_name:
                names = [getattr(d.call, "__name__", "") for d in r.dependant.dependencies]
                return [n for n in names if n.startswith("rbac_")]
        raise AssertionError(route_name)
    assert action_of("computation_lines") == ["rbac_income_tax_read"]
    assert action_of("decide_computation_line") == ["rbac_income_tax_compute"]
    assert can("Executive", "income_tax", "compute") and not can("Reviewer", "income_tax", "compute")


def test_the_decision_vocabulary_and_the_migrations_check_agree():
    sql = (REPO / "apps" / "api" / "migrations"
           / "455_income_tax_worksheets_and_ais_decisions.sql").read_text(encoding="utf-8")
    import re
    keys = re.search(r"line_key IN \((.*?)\)\)", sql, re.S).group(1)
    assert set(re.findall(r"'([^']+)'", keys)) == set(acs.SUGGESTABLE)
    decisions = re.search(r"decision\s+text NOT NULL CHECK \(decision IN \((.*?)\)\)", sql, re.S).group(1)
    assert set(re.findall(r"'([^']+)'", decisions)) == set(acs.DECISIONS)


def test_the_suggestable_buckets_are_buckets_the_parser_actually_produces():
    from domain.income_tax.ais import TRANSACTION_TYPES
    for bucket, _, _ in acs.SUGGESTABLE.values():
        assert bucket in TRANSACTION_TYPES
    for bucket in acs.SUGGESTIONS_REFUSED:
        assert bucket in TRANSACTION_TYPES
    # Every bucket the parser can produce is either offered or refused with a
    # reason, except the two that are not income lines at all.
    handled = {b for b, _, _ in acs.SUGGESTABLE.values()} | set(acs.SUGGESTIONS_REFUSED)
    assert set(TRANSACTION_TYPES) == handled
