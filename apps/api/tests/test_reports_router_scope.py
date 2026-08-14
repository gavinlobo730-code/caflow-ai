"""
/api/reports — the guard and the client scoping, not the arithmetic.

The arithmetic is covered in test_report_transactions_service.py. What matters
here is that a new endpoint over EXISTING data did not become the loosest way to
reach it. Both source lists — sales_invoices.list_invoices and
purchase_bills.list_purchase_bills — are rbac("accounting", "read"), which
excludes Reviewer. A reporting router is exactly where someone reaches for
report:read (_ALL_STAFF) because the name fits, and hands a Reviewer the invoice
and bill data the other two endpoints refuse them.
"""
import inspect

import pytest

from core.permissions import can
from routers import reports


def _guard_name(fn) -> str:
    dep = inspect.signature(fn).parameters["current_user"].default
    return getattr(dep.dependency, "__name__", "")


@pytest.mark.parametrize("fn", [reports.list_report_transactions, reports.gst_summary])
def test_both_endpoints_require_accounting_read(fn):
    """Not report:read. The rows are invoices and bills, so the permission has
    to be the one that already governs invoices and bills."""
    assert _guard_name(fn) == "rbac_accounting_read"


def test_the_guard_actually_excludes_someone():
    """A guard nobody fails is not a guard. accounting:read stops at Executive,
    so Reviewer is the role this endpoint is protected from — and report:read,
    the tempting alternative, would have admitted them."""
    assert can("Reviewer", "accounting", "read") is False
    assert can("Executive", "accounting", "read") is True
    assert can("Reviewer", "report", "read") is True    # why the name is a trap


def test_a_named_client_is_checked_before_any_query(monkeypatch):
    """assert_client_access raises 404 — not 403 — so a client outside the
    caller's assignments is not disclosed to exist. It must run BEFORE the
    service, or the check happens after the data has already been read."""
    order = []
    monkeypatch.setattr(reports, "assert_client_access",
                        lambda u, c: order.append(("check", c)))
    monkeypatch.setattr(reports, "get_supabase", lambda: object())
    monkeypatch.setattr(reports.svc, "list_transactions",
                        lambda *a, **k: order.append(("query", k.get("client_ids"))) or [])

    reports.list_report_transactions(
        client_id="c1", date_from=None, date_to=None,
        current_user={"id": "u1", "firm_id": "f1", "role": "Manager"})

    assert order == [("check", "c1"), ("query", ["c1"])]


def test_omitting_the_client_narrows_to_the_callers_assignments(monkeypatch):
    """No client_id must not mean "every client in the firm" for a role that is
    not firm-wide — it means every client they are assigned to."""
    seen = {}
    monkeypatch.setattr(reports, "effective_client_ids", lambda u: {"c2", "c1"})
    monkeypatch.setattr(reports, "get_supabase", lambda: object())
    monkeypatch.setattr(reports.svc, "list_transactions",
                        lambda *a, **k: seen.update(k) or [])

    reports.list_report_transactions(
        client_id=None, date_from=None, date_to=None,
        current_user={"id": "u1", "firm_id": "f1", "role": "Executive"})

    # Sorted so the query is deterministic; a set's iteration order is not.
    assert seen["client_ids"] == ["c1", "c2"]


def test_a_firmwide_role_passes_no_client_filter(monkeypatch):
    """effective_client_ids returns None for Partner. That must reach the
    service as None ("no filter"), NOT as an empty list, which the service
    correctly reads as "scoped to nothing" and would blank a Partner's report."""
    seen = {}
    monkeypatch.setattr(reports, "effective_client_ids", lambda u: None)
    monkeypatch.setattr(reports, "get_supabase", lambda: object())
    monkeypatch.setattr(reports.svc, "list_transactions",
                        lambda *a, **k: seen.update(k) or [])

    reports.list_report_transactions(
        client_id=None, date_from=None, date_to=None,
        current_user={"id": "u1", "firm_id": "f1", "role": "Partner"})

    assert seen["client_ids"] is None


@pytest.mark.parametrize("bad", ["2026", "2026-1", "26-01", "2026-13", "2026-00", "abc-de"])
def test_a_malformed_month_is_refused(bad, monkeypatch):
    """Rejected before the client check and the query. '2026-13' is the one that
    matters: it parses as an integer pair and would build a nonsense window
    rather than fail, quietly returning an empty GST summary."""
    from fastapi import HTTPException
    monkeypatch.setattr(reports, "assert_client_access", lambda u, c: None)

    with pytest.raises(HTTPException) as exc:
        reports.gst_summary(client_id="c1", month=bad,
                            current_user={"id": "u1", "firm_id": "f1", "role": "Manager"})

    assert exc.value.status_code == 422


def test_a_wellformed_month_is_accepted(monkeypatch):
    """The control: the validation above must not reject a legitimate month."""
    monkeypatch.setattr(reports, "assert_client_access", lambda u, c: None)
    monkeypatch.setattr(reports, "get_supabase", lambda: object())
    monkeypatch.setattr(reports.svc, "gst_summary", lambda *a, **k: {"period": "2026-04"})

    body = reports.gst_summary(client_id="c1", month="2026-04",
                               current_user={"id": "u1", "firm_id": "f1", "role": "Manager"})

    assert body["success"] is True
