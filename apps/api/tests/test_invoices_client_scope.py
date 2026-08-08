"""
Client-assignment scope on the invoices (Fee Billing) router.

Unlike billing.py, PERMISSIONS["invoice"] (core/permissions.py) is
_AT_LEAST_EXECUTIVE — Manager and Executive both pass rbac() here, and both
are assignment-scoped under M3. This is a live M2 gap, not a firm-boundary
one: every handler checked only `invoice.get("firm_id") != firm_id` (or the
equivalent on the engagement a draft is generated from), with no assignment
check at all, and with 403 rather than the rest of the codebase's 404
convention — itself a disclosure oracle independent of the M2 gap, since a
missing invoice_id already got 404 while a wrong-firm one got 403.

fee_invoices.client_id and fee_engagements.client_id are both NOT NULL
(migration 014) — every row here is traceable to exactly one client, so
nothing in this router is a firm-level resource in disguise.
"""
import pytest
from fastapi import HTTPException

import routers.invoices as iv

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test",
       "role": "Executive"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest. Patches both assert_client_access
    (list_invoices) and can_access_client (the resolve-then-assert helpers)."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(iv, "assert_client_access", _assert)
    monkeypatch.setattr(iv, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_invoices
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_invoices_by_id_is_refused(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_all", lambda **k: [])
    with pytest.raises(HTTPException) as e:
        iv.list_invoices(engagement_id=None, client_id=THEIRS, status=None,
                         date_from=None, date_to=None, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_invoices_still_works(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_all",
                        lambda **k: [{"id": "I1", "client_id": MINE}])
    out = iv.list_invoices(engagement_id=None, client_id=MINE, status=None,
                           date_from=None, date_to=None, current_user=USER)
    assert [i["id"] for i in out["data"]["invoices"]] == ["I1"]
    assert deny == [MINE]


def test_listing_with_no_client_id_narrows_to_assigned_clients(deny, monkeypatch):
    """No client_id means the raw list can span every client in the firm —
    filter_by_client has to actually run, and the response has to reflect
    ITS result (including a corrected 'total'), not the raw one."""
    raw = [{"id": "I1", "client_id": MINE}, {"id": "I2", "client_id": THEIRS}]
    monkeypatch.setattr(iv.invoice_repo, "find_all", lambda **k: raw)
    monkeypatch.setattr(iv, "filter_by_client",
                        lambda user, rows: [r for r in rows if r["client_id"] == MINE])
    out = iv.list_invoices(engagement_id=None, client_id=None, status=None,
                           date_from=None, date_to=None, current_user=USER)
    assert [i["id"] for i in out["data"]["invoices"]] == ["I1"]
    assert out["data"]["total"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# _assert_invoice_scope — the row-addressed helper
# ══════════════════════════════════════════════════════════════════════════════

INVOICES = {
    "INV-MINE": {"id": "INV-MINE", "firm_id": FIRM, "client_id": MINE, "status": "Draft"},
    "INV-THEIRS": {"id": "INV-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "Draft"},
    "INV-ALIEN": {"id": "INV-ALIEN", "firm_id": "firm-2", "client_id": "c-x", "status": "Draft"},
}


def test_invoice_scope_refuses_another_clients_invoice(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    with pytest.raises(HTTPException) as e:
        iv._assert_invoice_scope(USER, "INV-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_invoice_scope_returns_your_own_invoice(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    row = iv._assert_invoice_scope(USER, "INV-MINE")
    assert row["id"] == "INV-MINE"
    assert deny == [MINE]


def test_invoice_scope_refuses_another_firms_invoice_before_the_client_check(deny, monkeypatch):
    """invoice_repo.find_by_id() does not filter by firm at all — this
    router's own firm_id check is the only thing standing between a foreign
    firm's invoice_id and the client-scope check running against the wrong
    client entirely."""
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    with pytest.raises(HTTPException) as e:
        iv._assert_invoice_scope(USER, "INV-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_invoices_use_the_identical_message(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    with pytest.raises(HTTPException) as missing:
        iv._assert_invoice_scope(USER, "INV-NOPE")
    with pytest.raises(HTTPException) as hidden:
        iv._assert_invoice_scope(USER, "INV-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Invoice not found"


# ══════════════════════════════════════════════════════════════════════════════
# get_invoice / download_invoice_pdf — driven through the real endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_reading_another_clients_invoice_is_refused(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    with pytest.raises(HTTPException):
        iv.get_invoice("INV-THEIRS", current_user=USER)


def test_reading_your_own_invoice_still_works(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    out = iv.get_invoice("INV-MINE", current_user=USER)
    assert out["data"]["invoice"]["id"] == "INV-MINE"


def test_downloading_another_clients_invoice_pdf_is_refused(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    reached = []
    monkeypatch.setattr("services.invoice_pdf_service.get_invoice_pdf",
                        lambda *a, **k: reached.append(a) or (b"", "x.pdf"))
    with pytest.raises(HTTPException):
        iv.download_invoice_pdf("INV-THEIRS", current_user=USER)
    assert reached == [], "the PDF was rendered despite the refusal"


def test_downloading_your_own_invoice_pdf_still_works(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    monkeypatch.setattr("services.invoice_pdf_service.get_invoice_pdf",
                        lambda *a, **k: (b"%PDF-1.4", "invoice.pdf"))
    out = iv.download_invoice_pdf("INV-MINE", current_user=USER)
    assert out.media_type == "application/pdf"


# ══════════════════════════════════════════════════════════════════════════════
# _assert_engagement_scope + generate_from_engagement / generate_from_time_entries
# ══════════════════════════════════════════════════════════════════════════════

ENGAGEMENTS = {
    "ENG-MINE": {"id": "ENG-MINE", "firm_id": FIRM, "client_id": MINE},
    "ENG-THEIRS": {"id": "ENG-THEIRS", "firm_id": FIRM, "client_id": THEIRS},
    "ENG-ALIEN": {"id": "ENG-ALIEN", "firm_id": "firm-2", "client_id": "c-x"},
}


def _fake_engagement_repo(monkeypatch):
    import repositories.engagement_repository as er
    monkeypatch.setattr(er.engagement_repo, "find_by_id", lambda eid: ENGAGEMENTS.get(eid))


def test_engagement_scope_refuses_another_clients_engagement(deny, monkeypatch):
    _fake_engagement_repo(monkeypatch)
    with pytest.raises(HTTPException) as e:
        iv._assert_engagement_scope(USER, "ENG-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_engagement_scope_returns_your_own_engagement(deny, monkeypatch):
    _fake_engagement_repo(monkeypatch)
    row = iv._assert_engagement_scope(USER, "ENG-MINE")
    assert row["id"] == "ENG-MINE"
    assert deny == [MINE]


def test_engagement_scope_refuses_another_firms_engagement_before_the_client_check(deny, monkeypatch):
    _fake_engagement_repo(monkeypatch)
    with pytest.raises(HTTPException) as e:
        iv._assert_engagement_scope(USER, "ENG-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_engagements_use_the_identical_message(deny, monkeypatch):
    _fake_engagement_repo(monkeypatch)
    with pytest.raises(HTTPException) as missing:
        iv._assert_engagement_scope(USER, "ENG-NOPE")
    with pytest.raises(HTTPException) as hidden:
        iv._assert_engagement_scope(USER, "ENG-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Engagement not found"


def test_generating_from_another_clients_engagement_is_refused(deny, monkeypatch):
    _fake_engagement_repo(monkeypatch)
    reached = []
    monkeypatch.setattr("services.invoice_generation_service.generate_invoice_from_engagement",
                        lambda *a, **k: reached.append(a) or "INV-NEW")
    with pytest.raises(HTTPException):
        iv.generate_from_engagement("ENG-THEIRS", invoice_month=None, current_user=USER)
    assert reached == [], "an invoice was generated despite the refusal"


def test_generating_from_your_own_engagement_still_works(deny, monkeypatch):
    _fake_engagement_repo(monkeypatch)
    monkeypatch.setattr("services.invoice_generation_service.generate_invoice_from_engagement",
                        lambda *a, **k: "INV-NEW")
    monkeypatch.setattr(iv.invoice_repo, "find_by_id",
                        lambda iid: {"id": iid, "client_id": MINE})
    out = iv.generate_from_engagement("ENG-MINE", invoice_month=None, current_user=USER)
    assert out["data"]["invoice"]["id"] == "INV-NEW"


def test_generating_from_time_entries_on_another_clients_engagement_is_refused(deny, monkeypatch):
    _fake_engagement_repo(monkeypatch)
    reached = []
    monkeypatch.setattr("services.invoice_generation_service.generate_invoice_from_time_entries",
                        lambda *a, **k: reached.append(a) or "INV-NEW")
    with pytest.raises(HTTPException):
        iv.generate_from_time_entries("ENG-THEIRS", invoice_month=None,
                                      billable_only=True, current_user=USER)
    assert reached == [], "an invoice was generated despite the refusal"


# ══════════════════════════════════════════════════════════════════════════════
# change_invoice_status / delete_invoice
# ══════════════════════════════════════════════════════════════════════════════

def test_changing_status_on_another_clients_invoice_is_refused(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    reached = []
    monkeypatch.setattr(iv.invoice_repo, "change_status",
                        lambda *a, **k: reached.append(a) or {})
    with pytest.raises(HTTPException):
        iv.change_invoice_status("INV-THEIRS", iv.StatusChangeRequest(new_status="Issued"),
                                 current_user=USER)
    assert reached == [], "the status was changed despite the refusal"


def test_changing_status_on_your_own_invoice_still_works(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    monkeypatch.setattr(iv.invoice_repo, "change_status",
                        lambda iid, status: {"id": iid, "status": status})
    monkeypatch.setattr(iv, "log_event", lambda *a, **k: None)
    out = iv.change_invoice_status("INV-MINE", iv.StatusChangeRequest(new_status="Issued"),
                                   current_user=USER)
    assert out["data"]["invoice"]["status"] == "Issued"


def test_deleting_another_clients_invoice_is_refused(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    reached = []
    monkeypatch.setattr(iv.invoice_repo, "delete", lambda *a, **k: reached.append(a) or True)
    with pytest.raises(HTTPException):
        iv.delete_invoice("INV-THEIRS", current_user=USER)
    assert reached == [], "the invoice was deleted despite the refusal"


def test_deleting_your_own_draft_invoice_still_works(deny, monkeypatch):
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    monkeypatch.setattr(iv.invoice_repo, "delete", lambda *a, **k: True)
    out = iv.delete_invoice("INV-MINE", current_user=USER)
    assert out["data"]["deleted"] is True


def test_deleting_your_own_non_draft_invoice_hits_the_business_rule_not_the_guard(deny, monkeypatch):
    """The M2 guard has to step aside for a legitimate call and let the
    router's own status check run — not swallow it into another refusal."""
    issued = dict(INVOICES["INV-MINE"], status="Issued")
    monkeypatch.setattr(iv.invoice_repo, "find_by_id", lambda iid: issued)
    with pytest.raises(HTTPException) as e:
        iv.delete_invoice("INV-MINE", current_user=USER)
    assert e.value.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# run_overdue_check_endpoint — confine-the-run, not a list to narrow
# ══════════════════════════════════════════════════════════════════════════════

def test_overdue_check_runs_once_firm_wide_for_a_firmwide_caller(monkeypatch):
    calls = []
    monkeypatch.setattr(iv, "effective_client_ids", lambda user: None)
    monkeypatch.setattr("services.invoice_lifecycle_service.run_overdue_check",
                        lambda **k: calls.append(k) or {"transitioned": 3, "invoice_ids": ["A", "B", "C"]})
    partner = {**USER, "role": "Partner"}
    out = iv.run_overdue_check_endpoint(current_user=partner)
    assert calls == [{"firm_id": FIRM, "client_id": None}]
    assert out["data"]["transitioned"] == 3


def test_overdue_check_runs_once_per_assigned_client_for_a_scoped_caller(monkeypatch):
    """The write itself must be confined — the caller is assigned to exactly
    two clients, and the batch must not touch a third, unassigned one."""
    calls = []
    monkeypatch.setattr(iv, "effective_client_ids", lambda user: {"c-a", "c-b"})

    def _fake_run(firm_id, client_id):
        calls.append(client_id)
        return {"transitioned": 1, "invoice_ids": [f"INV-{client_id}"]}

    monkeypatch.setattr("services.invoice_lifecycle_service.run_overdue_check", _fake_run)
    out = iv.run_overdue_check_endpoint(current_user=USER)
    assert sorted(calls) == ["c-a", "c-b"]
    assert out["data"]["transitioned"] == 2
    assert sorted(out["data"]["invoice_ids"]) == ["INV-c-a", "INV-c-b"]
