"""
Client-assignment scope on the billing (Revenue Operations) router.

Every endpoint here requires rbac("billing", "read"/"write"), and
PERMISSIONS["billing"] (core/permissions.py) admits ONLY Partner — the sole
firm-wide role (core/authz.py _FIRMWIDE_ROLES). A Manager, Executive or
Reviewer 403s before any handler body runs, so the M2 assignment-scope bug
this sweep targets cannot occur on this router by construction.

What WAS real: assert_client_access's other half — the firm-boundary check
(does client_id actually belong to the caller's firm?) — which every
endpoint but create_schedule (a prior fix) left unchecked. A Partner
supplying a schedule_id/client_id/invoice_id from another firm previously
fell through to either a raw firm_id-scoped WHERE clause (safe by
construction, confirmed by reading services/billing_service.py and
services/collections_service.py) or, for record_fee_receipt, a bare
firm_id-only check with no client check at all despite fee_invoices.client_id
being NOT NULL (migration 014). This makes every one of those checks
explicit at the router — the same "guards the body, not the record" fix as
every prior router in this sweep, and real defense-in-depth: if any of those
service queries is ever refactored to drop its firm_id filter, the router
check below still catches it.
"""
import pytest
from fastapi import HTTPException

import routers.billing as bl

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real boundary, not a stub that
    always agrees. Catches a guard that resolves the wrong row's client.
    Patches both assert_client_access (raising helpers) and can_access_client
    (the boolean form _assert_invoice_scope uses for its message-oracle fix)."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(bl, "assert_client_access", _assert)
    monkeypatch.setattr(bl, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_schedules — filter_by_client (aggregate list, not a bare assert)
# ══════════════════════════════════════════════════════════════════════════════

def test_list_schedules_returns_the_filtered_result_not_the_raw_one(monkeypatch):
    """A filter that's computed but discarded is the same bug as no filter —
    this drives the actual return value through filter_by_client."""
    raw = [{"id": "S1", "client_id": MINE}, {"id": "S2", "client_id": THEIRS}]
    monkeypatch.setattr(bl.billing_service, "list_schedules", lambda *a, **k: raw)
    monkeypatch.setattr(bl, "filter_by_client",
                        lambda user, rows: [r for r in rows if r["client_id"] == MINE])
    out = bl.list_schedules(active_only=False, current_user=USER)
    assert [s["id"] for s in out["data"]] == ["S1"]


def test_list_schedules_passes_the_caller_to_filter_by_client(monkeypatch):
    seen = {}
    monkeypatch.setattr(bl.billing_service, "list_schedules", lambda *a, **k: [])

    def _filter(user, rows):
        seen["user"] = user
        return rows

    monkeypatch.setattr(bl, "filter_by_client", _filter)
    bl.list_schedules(active_only=False, current_user=USER)
    assert seen["user"] == USER


# ══════════════════════════════════════════════════════════════════════════════
# create_schedule — pre-existing guard, still driven for real
# ══════════════════════════════════════════════════════════════════════════════

def _schedule_body(client_id):
    return bl.BillingScheduleIn(client_id=client_id, arrangement="retainer",
                                cadence="monthly", amount_paise=10000,
                                service_id="svc-1")


def test_creating_a_schedule_for_another_clients_id_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        bl.create_schedule(_schedule_body(THEIRS), current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_creating_a_schedule_for_your_own_client_still_works(deny, monkeypatch):
    monkeypatch.setattr(bl.billing_service, "create_schedule",
                        lambda *a, **k: {"id": "S1", "client_id": MINE})
    out = bl.create_schedule(_schedule_body(MINE), current_user=USER)
    assert out["data"]["id"] == "S1"
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# generate — row-addressed by schedule_id
# ══════════════════════════════════════════════════════════════════════════════

def test_generate_refuses_another_clients_schedule(deny, monkeypatch):
    monkeypatch.setattr(bl.billing_service, "get_schedule",
                        lambda *a, **k: {"id": "S1", "client_id": THEIRS})
    reached = []
    monkeypatch.setattr(bl.billing_service, "generate_for_schedule",
                        lambda *a, **k: reached.append(a) or {})
    with pytest.raises(HTTPException) as e:
        bl.generate(schedule_id="S1", period=None, current_user=USER)
    assert e.value.status_code == 404
    assert reached == [], "generate_for_schedule ran despite the refusal"


def test_generate_still_works_for_your_own_schedule(deny, monkeypatch):
    monkeypatch.setattr(bl.billing_service, "get_schedule",
                        lambda *a, **k: {"id": "S1", "client_id": MINE})
    monkeypatch.setattr(bl.billing_service, "generate_for_schedule",
                        lambda *a, **k: {"created": True, "period": "2026-08",
                                         "invoice": {"id": "INV1"}})
    out = bl.generate(schedule_id="S1", period=None, current_user=USER)
    assert out["data"]["created"] is True
    assert deny == [MINE]


def test_generate_404s_before_the_client_check_when_the_schedule_is_missing(deny, monkeypatch):
    monkeypatch.setattr(bl.billing_service, "get_schedule", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        bl.generate(schedule_id="NOPE", period=None, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [], "the client guard ran on a schedule that does not exist"



# ══════════════════════════════════════════════════════════════════════════════
# unbilled_work — optional client_id query param
# ══════════════════════════════════════════════════════════════════════════════

def test_unbilled_work_refuses_another_client(deny, monkeypatch):
    reached = []
    monkeypatch.setattr(bl.billing_service, "unbilled_work",
                        lambda *a, **k: reached.append(a) or {})
    with pytest.raises(HTTPException) as e:
        bl.unbilled_work(client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert reached == [], "unbilled_work ran despite the refusal"


def test_unbilled_work_still_works_for_your_own_client(deny, monkeypatch):
    monkeypatch.setattr(bl.billing_service, "unbilled_work",
                        lambda *a, **k: {"total_value_paise": 50000})
    out = bl.unbilled_work(client_id=MINE, current_user=USER)
    assert out["data"]["total_value_paise"] == 50000
    assert deny == [MINE]


def test_unbilled_work_with_no_client_id_lists_firm_wide(deny, monkeypatch):
    monkeypatch.setattr(bl.billing_service, "unbilled_work",
                        lambda *a, **k: {"total_value_paise": 90000})
    out = bl.unbilled_work(client_id=None, current_user=USER)
    assert out["data"]["total_value_paise"] == 90000
    assert deny == [None]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_invoice_scope — the row-addressed helper itself
# ══════════════════════════════════════════════════════════════════════════════

INVOICES = {
    "INV-MINE": {"id": "INV-MINE", "firm_id": FIRM, "client_id": MINE, "total_paise": 100000},
    "INV-THEIRS": {"id": "INV-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "total_paise": 200000},
    "INV-ALIEN": {"id": "INV-ALIEN", "firm_id": "firm-2", "client_id": "c-x", "total_paise": 300000},
}


def test_invoice_scope_refuses_another_clients_invoice(deny, monkeypatch):
    monkeypatch.setattr(bl.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    with pytest.raises(HTTPException) as e:
        bl._assert_invoice_scope(USER, "INV-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_invoice_scope_returns_your_own_invoice(deny, monkeypatch):
    monkeypatch.setattr(bl.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    row = bl._assert_invoice_scope(USER, "INV-MINE")
    assert row["total_paise"] == 100000
    assert deny == [MINE]


def test_invoice_scope_refuses_another_firms_invoice_before_the_client_check(deny, monkeypatch):
    """Tenancy first: invoice_repo.find_by_id() does not filter by firm at
    all (repositories/invoice_repository.py), so this router's own firm_id
    check is the only thing standing between a foreign firm's invoice_id and
    the client-scope check being reached with an unrelated client."""
    monkeypatch.setattr(bl.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    with pytest.raises(HTTPException) as e:
        bl._assert_invoice_scope(USER, "INV-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_invoices_use_the_identical_message_template(deny, monkeypatch):
    """Checked against each id's own expected template rather than against
    each other, since two different ids always differ in the echoed id."""
    monkeypatch.setattr(bl.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    with pytest.raises(HTTPException) as missing:
        bl._assert_invoice_scope(USER, "INV-NOPE")
    with pytest.raises(HTTPException) as hidden:
        bl._assert_invoice_scope(USER, "INV-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == "Invoice INV-NOPE not found."
    assert hidden.value.detail == "Invoice INV-THEIRS not found."


# ══════════════════════════════════════════════════════════════════════════════
# record_fee_receipt — driven through the real endpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_recording_a_receipt_on_another_clients_invoice_is_refused(deny, monkeypatch):
    monkeypatch.setattr(bl.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    reached = []
    monkeypatch.setattr(bl.fee_billing_service, "record_receipt",
                        lambda *a, **k: reached.append(a) or {})
    with pytest.raises(HTTPException) as e:
        bl.record_fee_receipt("INV-THEIRS", bl.FeeReceiptIn(amount_paise=1000),
                              current_user=USER)
    assert e.value.status_code == 404
    assert reached == [], "record_receipt ran despite the refusal"


def test_recording_a_receipt_on_your_own_invoice_still_works(deny, monkeypatch):
    monkeypatch.setattr(bl.invoice_repo, "find_by_id", lambda iid: INVOICES.get(iid))
    monkeypatch.setattr(bl.fee_billing_service, "record_receipt",
                        lambda *a, **k: {"status": "Paid", "paid_paise": 100000})
    out = bl.record_fee_receipt("INV-MINE", bl.FeeReceiptIn(amount_paise=100000),
                                current_user=USER)
    assert out["data"]["status"] == "Paid"
    assert deny == [MINE]


def test_recording_a_receipt_on_a_missing_invoice_404s_before_the_client_check(deny, monkeypatch):
    monkeypatch.setattr(bl.invoice_repo, "find_by_id", lambda iid: None)
    with pytest.raises(HTTPException) as e:
        bl.record_fee_receipt("INV-NOPE", bl.FeeReceiptIn(amount_paise=1000),
                              current_user=USER)
    assert e.value.status_code == 404
    assert deny == []
