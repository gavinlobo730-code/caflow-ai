"""The loans screen's EMI calculator is a server answer in exact decimal arithmetic (POST-A-266, part 2)."""
from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from domain.loans.emi import emi_paise

pytestmark = pytest.mark.usefixtures("dev_header_auth")

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _exact(p: int, bps: int, n: int) -> Decimal:
    r = Decimal(bps) / Decimal(120_000)
    g = (1 + r) ** n
    return Decimal(p) * r * g / (g - 1)


@pytest.mark.parametrize("p,bps,n,expected", [
    # Rs 10,00,000 at 10.5% over 60 months: Rs 21,493.90 (a binary floating-point evaluation gives 2,149,390.04 paise).
    (100_000_000, 1050, 60, 2_149_390),
    # Rs 1,00,000 at 12% over 12 months: Rs 8,884.88.
    (10_000_000, 1200, 12, 888_488),
    # One month: principal plus one month's interest.
    (10_000_000, 1200, 1, 10_100_000),
])
def test_known_instalments(p, bps, n, expected):
    assert emi_paise(p, bps, n) == expected


def test_rounding_is_half_up_once_at_the_end():
    for p, bps, n in [(123_457, 937, 37), (99_999_999, 1, 1199), (5_000_000, 2499, 240)]:
        exact = _exact(p, bps, n)
        assert emi_paise(p, bps, n) == int(exact.quantize(Decimal(1), rounding="ROUND_HALF_UP"))


def test_a_zero_rate_spreads_the_principal():
    assert emi_paise(1_200_000, 0, 12) == 100_000
    assert emi_paise(1_000, 0, 3) == 333


@pytest.mark.parametrize("p,bps,n", [(0, 1000, 12), (-5, 1000, 12), (100, -1, 12), (100, 1000, 0), (True, 1000, 12)])
def test_refuses_what_is_not_a_loan(p, bps, n):
    with pytest.raises(ValueError):
        emi_paise(p, bps, n)


def test_the_route_answers_and_refuses():
    from main import app
    c = TestClient(app)
    h = {"X-User-Email": "exec@test.com", "X-User-Role": "executive", "X-Firm-ID": "firm-1"}
    r = c.get("/api/accounting/emi", params={"principal_paise": 100_000_000, "annual_rate_bps": 1050, "months": 60}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["data"]["emi_paise"] == 2_149_390
    assert c.get("/api/accounting/emi", params={"principal_paise": 0, "annual_rate_bps": 1050, "months": 60}, headers=h).status_code == 422
    assert c.get("/api/accounting/emi", params={"principal_paise": 100, "annual_rate_bps": 1050}, headers=h).status_code == 422
    client_role = {"X-User-Email": "c@test.com", "X-User-Role": "client", "X-Firm-ID": "firm-1"}
    assert c.get("/api/accounting/emi", params={"principal_paise": 100, "annual_rate_bps": 1050, "months": 6}, headers=client_role).status_code == 403


def test_the_browser_no_longer_works_out_an_emi():
    page = (WEB / "app/accounting/loans/page.tsx").read_text(encoding="utf-8")
    assert "calculateEMIPaise" not in page
    assert "Math.pow" not in page
    assert "/api/accounting/emi" in (WEB / "lib/api/index.ts").read_text(encoding="utf-8")
