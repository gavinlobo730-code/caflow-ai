"""A fee engagement is billed once per billing period (misc-tools-06).

'Raise Invoice' minted a new invoice per click, so a Monthly retainer clicked
twice was billed twice and a Quarterly or Annual one on every click.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.billing.period import CYCLES, billing_period


@pytest.mark.parametrize("cycle,on,start,end", [
    ("Monthly",     date(2026, 9, 15), date(2026, 9, 1),  date(2026, 9, 30)),
    ("Monthly",     date(2027, 2, 28), date(2027, 2, 1),  date(2027, 2, 28)),
    ("Quarterly",   date(2026, 4, 1),  date(2026, 4, 1),  date(2026, 6, 30)),
    ("Quarterly",   date(2026, 12, 31), date(2026, 10, 1), date(2026, 12, 31)),
    ("Quarterly",   date(2027, 2, 10), date(2027, 1, 1),  date(2027, 3, 31)),
    ("Half-Yearly", date(2026, 9, 30), date(2026, 4, 1),  date(2026, 9, 30)),
    ("Half-Yearly", date(2027, 3, 31), date(2026, 10, 1), date(2027, 3, 31)),
    ("Annually",    date(2027, 1, 5),  date(2026, 4, 1),  date(2027, 3, 31)),
    ("Annually",    date(2026, 4, 1),  date(2026, 4, 1),  date(2027, 3, 31)),
])
def test_periods_follow_the_indian_financial_year(cycle, on, start, end):
    assert billing_period(cycle, on) == (start, end)


def test_a_one_time_engagement_is_one_unbounded_period():
    assert billing_period("One-time", date(2026, 9, 1)) == (None, None)


def test_an_unknown_cycle_is_refused_not_guessed():
    with pytest.raises(ValueError):
        billing_period("Weekly", date(2026, 9, 1))


def test_the_vocabulary_is_migration_123s_check():
    import pathlib, re
    migrations = pathlib.Path(__file__).resolve().parents[1] / "migrations"
    text = "\n".join(p.read_text() for p in sorted(migrations.glob("*.sql"))
                     if "billing_cycle" in p.read_text())
    found = re.findall(r"billing_cycle\s+IN\s*\(([^)]*)\)", text, re.I)
    assert found, "no billing_cycle CHECK found in the migrations"
    values = {v.strip().strip("'") for v in found[-1].split(",")}
    assert values == set(CYCLES)


# ── the service refuses a second invoice for the same period ────────────────

import uuid as _uuid

import services.invoice_generation_service as invoice_gen
from repositories.engagement_repository import engagement_repo
from repositories.invoice_repository import invoice_repo


def _engagement(cycle, **over):
    eid = f"ENG-{_uuid.uuid4().hex[:8]}"
    row = {"id": eid, "firm_id": "FIRM-BILL", "client_id": "CLI-BILL",
           "fee_paise": 1_000_000, "billing_cycle": cycle, **over}
    return row


def _raise(monkeypatch, eng, when):
    monkeypatch.setattr(engagement_repo, "get_or_raise", lambda _id: eng)
    return invoice_gen.generate_invoice_from_engagement(eng["id"], invoice_month=when)


def test_a_second_monthly_invoice_in_the_same_month_is_refused(monkeypatch):
    eng = _engagement("Monthly")
    _raise(monkeypatch, eng, "2026-09-03")
    with pytest.raises(invoice_gen.PeriodAlreadyBilled) as exc:
        _raise(monkeypatch, eng, "2026-09-28")
    assert "September 2026" in str(exc.value)


def test_the_next_month_is_a_new_period(monkeypatch):
    eng = _engagement("Monthly")
    _raise(monkeypatch, eng, "2026-09-03")
    assert _raise(monkeypatch, eng, "2026-10-01")


def test_a_quarterly_engagement_is_billed_once_a_quarter(monkeypatch):
    eng = _engagement("Quarterly")
    _raise(monkeypatch, eng, "2026-07-02")
    with pytest.raises(invoice_gen.PeriodAlreadyBilled):
        _raise(monkeypatch, eng, "2026-09-30")
    assert _raise(monkeypatch, eng, "2026-10-01")


def test_a_one_time_engagement_is_billed_once_ever(monkeypatch):
    eng = _engagement("One-time")
    _raise(monkeypatch, eng, "2026-04-10")
    with pytest.raises(invoice_gen.PeriodAlreadyBilled):
        _raise(monkeypatch, eng, "2027-06-01")


def test_a_cancelled_invoice_does_not_block_raising_it_again(monkeypatch):
    eng = _engagement("Monthly")
    first = _raise(monkeypatch, eng, "2026-09-03")
    invoice_repo.find_by_id(first)["status"] = "Cancelled"
    assert _raise(monkeypatch, eng, "2026-09-20")


def test_the_router_answers_a_second_click_with_a_409():
    import inspect
    from routers import invoices
    src = inspect.getsource(invoices.generate_from_engagement)
    assert "except PeriodAlreadyBilled" in src and "status_code=409" in src
    # HTTPException must pass through before the generic 400 handler.
    assert src.index("except HTTPException") < src.index("except Exception")
