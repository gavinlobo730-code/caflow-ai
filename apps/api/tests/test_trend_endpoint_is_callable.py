"""
The trend endpoint is actually CALLED at least once.

Deliberately shallow, for the reason tests/test_new_payroll_endpoints_are_callable
records: four endpoints once shipped calling a two-argument guard with one
argument, and every one of them would have raised TypeError on its first real
request. Domain tests cannot see a wiring mistake. The arithmetic and the read
shape are tested in tests/test_multi_year_trend.py; this executes the handler.
"""
import pytest
from fastapi import HTTPException

import routers.accounting as ac

CLIENT = "11111111-1111-1111-1111-111111111111"
USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "email": "p@f.in", "role": "Partner"}


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(ac, "_prod_db", lambda: None)
    monkeypatch.setattr(ac, "assert_client_access", lambda *a, **k: None)


def test_the_trend_endpoint_is_callable():
    out = ac.get_schedule_iii_trend(client_id=CLIENT, years=5, to_fy="2026-27",
                                    current_user=USER)
    assert out["success"]
    assert "not a statutory statement" in out["data"]["basis"].lower()


def test_it_asks_for_exactly_the_years_requested_ending_at_to_fy():
    """A window that quietly ran to the current year instead would put a column
    on the page the CA did not ask for, and leave off one they did."""
    out = ac.get_schedule_iii_trend(client_id=CLIENT, years=3, to_fy="2026-27",
                                    current_user=USER)
    assert out["data"]["requested_fys"] == ["2024-25", "2025-26", "2026-27"]


def test_a_malformed_year_is_422_not_a_silently_shifted_window():
    """int("20xx") would raise ValueError and 500; a bad label is the caller's
    mistake and has to say so."""
    with pytest.raises(HTTPException) as e:
        ac.get_schedule_iii_trend(client_id=CLIENT, years=5, to_fy="not-a-year",
                                  current_user=USER)
    assert e.value.status_code == 422


def test_it_defaults_to_the_current_financial_year():
    out = ac.get_schedule_iii_trend(client_id=CLIENT, years=2, to_fy=None,
                                    current_user=USER)
    assert out["data"]["requested_fys"][-1] == ac._current_fy_long()
