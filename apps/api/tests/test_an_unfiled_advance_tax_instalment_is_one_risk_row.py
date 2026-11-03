"""An unfiled advance-tax instalment is ONE row on the risk register, and the capacity forecast settles on the register's pair (POST-A-208).

WHAT WAS WRONG
    The register listed an unfiled advance-tax instalment twice: as an Overdue Filing (its advice reads 'CGST Act §47 for a GST return') and
    as an Advance Tax Default (§208's instalment and §234C, the statute that applies), because the calendar carries the obligation as a
    filing and the register derives the default from the engine's dates. Which stays was an open question on the ledger; the default row is
    the specific one, so it stays and the generic one is held out for the same (client, date), as a TDS statement is held out for the TDS
    default. `capacity_risk_service._COMPLIANCE_SETTLED` was an unpinned second copy of the pair the register calls settled.

WHAT THIS HOLDS
    ONE ROW        an unfiled, overdue instalment on an engine date is one Advance Tax Default and no Overdue Filing;
    NEVER DROPPED  an advance-tax entry on a date the engine does not derive is still listed, as an Overdue Filing, because no default row
                   covers it; a filed or not-applicable one is neither;
    UNCHANGED      an overdue GST return is still an Overdue Filing, an instalment of a client the calendar does not track for advance tax
                   raises nothing, and the default row's content is as it was;
    ONE PAIR       the capacity forecast's settled set IS the register's, and the register service's advance-tax word IS the rule's.
"""
from __future__ import annotations

from datetime import date

from domain.risk import register as rule
from services import capacity_risk_service as capacity
from services import risk_register_service as service

AS_AT = date(2026, 11, 1)
INSTALMENTS = [{"installment": "1st", "due_date": "2026-06-15"}, {"installment": "2nd", "due_date": "2026-09-15"},
               {"installment": "3rd", "due_date": "2026-12-15"}, {"installment": "4th", "due_date": "2027-03-15"}]
CLIENTS = [{"id": "c1", "client_name": "Acme Ltd", "gstin": "", "pan": "AABCU9603R"}]


def _build(calendar, *, tracked=("c1",), filed=()):
    return rule.build(
        calendar=calendar, clients=CLIENTS, client_ids_with_recent_entries={"c1"}, advance_tax_installments=INSTALMENTS,
        advance_tax_tracked_client_ids=set(tracked), advance_tax_filed_keys=set(filed), dsc_rows=[], loans=[], deposits=[], as_at=AS_AT)


def _entry(ctype, due, status="pending"):
    return {"client_id": "c1", "compliance_type": ctype, "due_date": due, "filing_status": status}


def _kinds(register):
    return sorted((r.risk_type, r.on_date) for r in register.rows if r.risk_type in ("Overdue Filing", "Advance Tax Default"))


def test_an_unfiled_instalment_on_an_engine_date_is_one_advance_tax_default_and_no_overdue_filing():
    reg = _build([_entry("ADVANCE_TAX", "2026-09-15")])
    assert _kinds(reg) == [("Advance Tax Default", "2026-06-15"), ("Advance Tax Default", "2026-09-15")], _kinds(reg)


def test_the_row_that_stays_is_the_one_that_names_the_statute_that_applies():
    reg = _build([_entry("ADVANCE_TAX", "2026-09-15")])
    row = next(r for r in reg.rows if r.risk_type == "Advance Tax Default" and r.on_date == "2026-09-15")
    assert "§234C" in row.action and "CGST" not in row.action and row.severity == "high"
    assert not any("CGST Act §47" in r.action and r.on_date == "2026-09-15" for r in reg.rows)


def test_an_advance_tax_entry_on_a_date_the_engine_does_not_derive_is_still_listed():
    reg = _build([_entry("ADVANCE_TAX", "2026-09-30")])
    assert ("Overdue Filing", "2026-09-30") in _kinds(reg), "an instalment must not vanish from the register"


def test_a_filed_or_not_applicable_instalment_is_neither_row():
    for status in ("filed", "na"):
        reg = _build([_entry("ADVANCE_TAX", "2026-09-15", status)], filed={"c1|2026-09-15"})
        assert ("Overdue Filing", "2026-09-15") not in _kinds(reg) and ("Advance Tax Default", "2026-09-15") not in _kinds(reg), status


def test_an_overdue_gst_return_is_still_an_overdue_filing_beside_an_instalment():
    reg = _build([_entry("GSTR3B", "2026-09-20"), _entry("ADVANCE_TAX", "2026-09-15")])
    assert ("Overdue Filing", "2026-09-20") in _kinds(reg) and ("Overdue Filing", "2026-09-15") not in _kinds(reg)


def test_a_client_the_calendar_does_not_track_for_advance_tax_raises_no_instalment():
    reg = _build([_entry("GSTR1", "2026-09-11")], tracked=())
    assert [k for k in _kinds(reg) if k[0] == "Advance Tax Default"] == []


def test_the_hold_out_is_per_client_and_per_date():
    clients = [{"id": "c1", "client_name": "A", "gstin": "", "pan": "AABCU9603R"}, {"id": "c2", "client_name": "B", "gstin": "", "pan": "AABCU9603R"}]
    cal = [_entry("ADVANCE_TAX", "2026-09-15"), {**_entry("ADVANCE_TAX", "2026-09-15"), "client_id": "c2"}]
    reg = rule.build(calendar=cal, clients=clients, client_ids_with_recent_entries={"c1", "c2"}, advance_tax_installments=INSTALMENTS,
                     advance_tax_tracked_client_ids={"c1"}, advance_tax_filed_keys=set(), dsc_rows=[], loans=[], deposits=[], as_at=AS_AT)
    # c1 is tracked: its instalment is a default and not an overdue filing. c2 is NOT tracked (no default row for it), so its entry stays.
    assert sorted((r.client_id, r.risk_type, r.on_date) for r in reg.rows if r.on_date == "2026-09-15") == [
        ("c1", "Advance Tax Default", "2026-09-15"), ("c2", "Overdue Filing", "2026-09-15")]


def test_the_capacity_forecast_settles_on_the_registers_pair_and_the_service_uses_the_rules_word():
    assert capacity._COMPLIANCE_SETTLED is rule.SETTLED_FILING_STATUSES
    assert service._ADVANCE_TAX_TYPE == rule.ADVANCE_TAX_TYPE == "ADVANCE_TAX"
