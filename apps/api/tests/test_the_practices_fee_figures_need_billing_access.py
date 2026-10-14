"""The practice's fee figures ask `billing:read` at every door, not only at the screens that already did (POST-B-024, stage two).

WHAT WAS WRONG
    `fee_invoices` is the practice's own economics and core/permissions reserves it to `billing` (a Partner's, or a grant
    on the Team screen). Three doors answered the same table to people the permission table keeps from it:

      * `/api/invoices` (list, one, PDF, from-engagement, from-time, run-overdue-check, status, delete) asked
        `invoice:read` / `invoice:write`, which an Executive holds, while `/api/engagements` and `/api/billing` asked
        `billing` and refused an Executive. The same rows were refused at one door and served at the other;
      * the analytics profitability, concentration and revenue-vs-effort endpoints (`analytics:read`, a Manager's) turn
        those invoices into revenue, margin and a share of the book, per client;
      * `/api/analytics/firm` summed revenue and outstanding for the firm and, on any failure, swallowed it into four
        zeros.

    Once the database refuses the fee tables to everyone below `billing:read` (the next migration), each of those would
    have answered an Executive or a Manager with a confident zero. They now refuse at the door, in words, or (the firm
    totals) say that the figures are withheld and give null, never zero.

NEGATIVE CONTROL (each of these fails against the previous code)
    * test_a_manager_is_refused_the_revenue_analytics
    * test_each_revenue_endpoint_asks_both_analytics_and_billing
    * test_the_firm_totals_withhold_the_fee_figures_from_a_manager
    * test_an_unreadable_fee_table_is_not_four_zeros
    * test_an_executive_is_refused_the_practices_fee_invoices
    * test_no_route_in_the_invoices_router_asks_the_invoice_resource
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app

API = Path(__file__).resolve().parents[1]
client = TestClient(app)
FIRM = "firm-001"


def _h(role: str) -> dict:
    return {"X-User-Role": role, "X-Firm-Id": FIRM, "X-User-Id": f"user-{role}"}


REVENUE_ANALYTICS = ["/api/analytics/profitability", "/api/analytics/concentration", "/api/analytics/revenue-vs-effort"]


# ── the revenue analytics ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.usefixtures("dev_header_auth")
@pytest.mark.parametrize("url", REVENUE_ANALYTICS)
def test_a_manager_is_refused_the_revenue_analytics(url):
    res = client.get(url, headers=_h("manager"))
    assert res.status_code == 403, (url, res.status_code, res.text[:200])


def _dependency_names(path: str) -> set[str]:
    route = next(r for r in app.routes if getattr(r, "path", None) == path and "GET" in getattr(r, "methods", ()))
    return {d.call.__name__ for d in route.dependant.dependencies}


@pytest.mark.parametrize("url", REVENUE_ANALYTICS)
def test_each_revenue_endpoint_asks_both_analytics_and_billing(url):
    """Both, not one instead of the other: analytics:read is the work-and-cost view, billing:read is the fees. (The
    routes need a database to answer, so the door is asserted on the route itself; the refusal above is the 403.)"""
    names = _dependency_names(url)
    assert {"rbac_analytics_read", "rbac_billing_read"} <= names, names


def test_a_partner_holds_both_permissions_the_revenue_endpoints_ask():
    from core.permissions import can_user
    for resource in ("analytics", "billing"):
        assert can_user({"role": "Partner"}, resource, "read")
    assert not can_user({"role": "Manager"}, "billing", "read")


# ── the firm totals ────────────────────────────────────────────────────────────────────────────────────────────────

class _Chain:
    """A chainable stand-in for the request client that answers a table with fixed rows, or fails it."""

    def __init__(self, rows, fail=(), name=None):
        self._rows, self._fail, self._name = rows, set(fail), name

    def table(self, name):
        if name in self._fail:
            raise RuntimeError(f"{name} unreadable")
        return _Chain(self._rows, self._fail, name)

    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        class R:
            data: list = []
        R.data = self._rows.get(self._name, [])
        return R()


def _firm(monkeypatch, user, *, fail=()):
    from routers import analytics as routes
    rows = {"fee_invoices": [
        {"total_paise": 100_00, "invoice_date": "2026-10-01", "status": "Paid"},
        {"total_paise": 50_00, "invoice_date": "2026-10-02", "status": "Issued"}]}
    monkeypatch.setattr(routes, "_get_db", lambda: _Chain(rows, fail))
    monkeypatch.setattr(routes.time_tracking_analytics_repo, "get_firm_hours",
                        lambda *a, **k: {"total_minutes": 0, "billable_minutes": 0})
    return routes.firm_analytics(period="month", current_user=user)["data"]


def test_the_firm_totals_withhold_the_fee_figures_from_a_manager(monkeypatch):
    md = _firm(monkeypatch, {"firm_id": FIRM, "role": "Manager"})
    pd = _firm(monkeypatch, {"firm_id": FIRM, "role": "Partner"})
    assert md["fees_withheld"] is True
    for k in ("revenue_paise", "outstanding_paise", "invoices_issued", "invoices_paid"):
        assert md[k] is None, f"{k} must be absent for a role that may not read fees, never 0"
    assert pd["fees_withheld"] is False
    assert pd["revenue_paise"] == 100_00 and pd["outstanding_paise"] == 50_00 and pd["invoices_issued"] == 2
    assert md["tasks_completed"] == pd["tasks_completed"], "the work figures are not fee economics"


def test_an_unreadable_fee_table_is_not_four_zeros(monkeypatch):
    """The read used to sit in `except: pass` over initial zeros, so an outage printed as 'nothing was billed'."""
    data = _firm(monkeypatch, {"firm_id": FIRM, "role": "Partner"}, fail={"fee_invoices"})
    assert data["fees_withheld"] is False
    assert data["revenue_paise"] is None and data["outstanding_paise"] is None, (
        "an outage must read as unknown (null), not as zero billed")


# ── the fee invoices ───────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.usefixtures("dev_header_auth")
def test_an_executive_is_refused_the_practices_fee_invoices():
    assert client.get("/api/invoices", headers=_h("executive")).status_code == 403
    assert client.post("/api/invoices/run-overdue-check", headers=_h("executive")).status_code == 403


def test_no_route_in_the_invoices_router_asks_the_invoice_resource():
    """A rule over the whole module: this router serves `fee_invoices`, the practice's fees, and every route in it
    asks `billing`. A route added next year that asks `invoice` (an Executive's) fails here and names itself."""
    tree = ast.parse((API / "routers" / "invoices.py").read_text())
    asked: list[tuple[str, str]] = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        f = call.func
        if isinstance(f, ast.Name) and f.id == "rbac" and call.args and isinstance(call.args[0], ast.Constant):
            asked.append((call.args[0].value, call.args[1].value if len(call.args) > 1 else ""))
    assert asked, "vacuity: the scan found no rbac() call in the router"
    assert all(resource == "billing" for resource, _ in asked), asked
