"""
Four more call sites naming columns that do not exist.

Same class as the health-engine fixes, found by sweeping all 1,477 backend
`.table()` call sites and checking each against production's
information_schema. Each is a whole feature that has never worked:

    billing_service.py            client_sales_invoice_lines.invoice_id
                                  (real: sales_invoice_id)
    portal.py  GET /document-requests   document_requests.due_date
                                  (no such column; is_urgent is the signal)
    portal.py  GET+POST /messages  portal_messages.text / .from_ca
                                  (real: body / sender_type)
    document_intelligence_v2.py   team_members.user_id, plus `message`,
                                  `entity_type`, `entity_id` on notifications,
                                  a lowercase role literal, and a `type` value
                                  outside the CHECK

WHY IT MATTERS THAT THESE ARE DIFFERENT SHAPES OF FAILURE
    The two portal ones have NO try/except around them, so those endpoints
    returned a 500 on every call — visibly broken, if anyone had looked.
    The other two are inside fail-soft blocks, so they failed silently: the
    billing recovery path left orphan rows behind, and no partner has ever
    been notified of a government notice.

The double refuses any column outside the real schema, exactly as PostgREST's
42703 does, and refuses values outside a CHECK. There is no `except` between
it and the assertions, so a phantom column cannot pass quietly here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _schema_checked_db import (  # noqa: E402
    CheckViolation, PhantomColumn, SchemaCheckedDB,
)

import routers.portal as portal  # noqa: E402
import services.billing_service as billing  # noqa: E402
from core.auth import get_current_user  # noqa: E402

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "auth_user_id": "auth-u1", "firm_id": FIRM,
        "role": "Partner", "email": "p@f.in"}


@pytest.fixture()
def portal_client(monkeypatch):
    """Build a TestClient whose portal router talks to a SchemaCheckedDB.

    monkeypatch, NOT a bare `portal._db = ...`: an unscoped assignment survives
    the test and leaks into every module that imports routers.portal afterwards.
    The first draft of this file did exactly that and broke two unrelated tests
    in test_portal_client_scope.py, which run later in the same session.
    """
    def _build(db: SchemaCheckedDB) -> TestClient:
        monkeypatch.setattr(portal, "_db", lambda: db)
        app = FastAPI()
        app.include_router(portal.router)
        app.dependency_overrides[get_current_user] = lambda: USER
        return TestClient(app, raise_server_exceptions=False)
    return _build


# ── portal: document requests ────────────────────────────────────────────────

def test_document_requests_endpoint_does_not_ask_for_due_date(portal_client):
    """`due_date` is not a column on document_requests. PostgREST rejects the
    whole select at parse time, and nothing catches it here — this endpoint
    returned 500 on every call."""
    db = SchemaCheckedDB({"document_requests": [{
        "id": "r1", "firm_id": FIRM, "client_id": CLIENT, "title": "Bank statement",
        "description": None, "is_urgent": True, "status": "pending",
        "fulfilled_at": None, "created_at": "2026-08-01",
    }]})
    res = portal_client(db).get(f"/api/portal/document-requests?client_id={CLIENT}")

    assert res.status_code == 200, "the select named a column that does not exist"
    rows = res.json()["data"]
    assert len(rows) == 1
    assert rows[0]["title"] == "Bank statement"
    assert rows[0]["is_urgent"] is True


# ── portal: messages, read and write ─────────────────────────────────────────

def test_messages_endpoint_reads_body_and_sender_type(portal_client):
    db = SchemaCheckedDB({"portal_messages": [{
        "id": "m1", "firm_id": FIRM, "client_id": CLIENT,
        "body": "Please send the April statement", "sender_type": "ca",
        "created_at": "2026-08-01",
    }]})
    res = portal_client(db).get(f"/api/portal/messages?client_id={CLIENT}")

    assert res.status_code == 200, "the select named `text` and `from_ca`, neither of which exists"
    msg = res.json()["data"][0]
    # The API shape is unchanged — the fix belongs at the database boundary.
    assert msg["text"] == "Please send the April statement"
    assert msg["from_ca"] is True


def test_a_client_message_maps_back_to_from_ca_false(portal_client):
    db = SchemaCheckedDB({"portal_messages": [{
        "id": "m2", "firm_id": FIRM, "client_id": CLIENT,
        "body": "Attached", "sender_type": "client", "created_at": "2026-08-02",
    }]})
    msg = portal_client(db).get(f"/api/portal/messages?client_id={CLIENT}").json()["data"][0]
    assert msg["from_ca"] is False


def test_sending_a_message_writes_real_columns(portal_client):
    """The INSERT named `text` and `from_ca` too, so no portal message has ever
    been written through this endpoint."""
    db = SchemaCheckedDB({"portal_messages": []})
    res = portal_client(db).post(
        "/api/portal/messages",
        json={"client_id": CLIENT, "text": "Received, thank you", "from_ca": True},
    )

    assert res.status_code == 200, "the insert named columns that do not exist"
    stored = db.rows["portal_messages"][0]
    assert stored["body"] == "Received, thank you"
    assert stored["sender_type"] == "ca", "sender_type is CHECKed to ('ca','client')"
    assert "text" not in stored and "from_ca" not in stored
    # ...and the caller still gets the shape it was written against.
    assert res.json()["data"]["text"] == "Received, thank you"
    assert res.json()["data"]["from_ca"] is True


def test_a_message_from_the_client_stores_sender_type_client(portal_client):
    db = SchemaCheckedDB({"portal_messages": []})
    portal_client(db).post(
        "/api/portal/messages",
        json={"client_id": CLIENT, "text": "Uploaded", "from_ca": False},
    )
    assert db.rows["portal_messages"][0]["sender_type"] == "client"


# ── billing: the duplicate-run recovery path ─────────────────────────────────

def test_orphan_invoice_lines_are_deleted_by_their_real_fk():
    """The FK is sales_invoice_id. As `invoice_id` this raised 42703, so the
    recovery never reached the statements after it: the orphan draft invoice
    survived AND the caller got an unknown-column error instead of the winner."""
    db = SchemaCheckedDB({"client_sales_invoice_lines": [
        {"id": "l1", "sales_invoice_id": "inv-1", "description": "A"},
        {"id": "l2", "sales_invoice_id": "inv-1", "description": "B"},
        {"id": "l3", "sales_invoice_id": "inv-2", "description": "other invoice"},
    ]})

    db.table("client_sales_invoice_lines").delete().eq("sales_invoice_id", "inv-1").execute()

    remaining = db.rows["client_sales_invoice_lines"]
    assert [r["id"] for r in remaining] == ["l3"], "only inv-1's lines should go"


def test_the_old_fk_name_would_still_be_rejected():
    """Pins the actual defect: had the column name been left alone, the double
    would refuse it — which is what production did, with an exception nobody
    was catching in that path."""
    db = SchemaCheckedDB({"client_sales_invoice_lines": []})
    with pytest.raises(PhantomColumn):
        db.table("client_sales_invoice_lines").delete().eq("invoice_id", "inv-1").execute()


def test_billing_service_no_longer_references_the_phantom_fk():
    src = Path(billing.__file__).read_text(encoding="utf-8")
    assert 'eq("invoice_id"' not in src, (
        "client_sales_invoice_lines has no invoice_id column — the FK is sales_invoice_id"
    )


# ── notices: the partner notification ────────────────────────────────────────

def test_partner_lookup_uses_users_not_team_members():
    """team_members has no user_id column, and notifications.user_id FKs to
    users(id). The role literal was lowercase too, while users.role is CHECKed
    to capitalised values — so it matched nothing even against the right table."""
    db = SchemaCheckedDB({"users": [
        {"id": "u-partner", "firm_id": FIRM, "email": "p@f.in", "role": "Partner"},
        {"id": "u-exec", "firm_id": FIRM, "email": "e@f.in", "role": "Executive"},
    ]})
    found = db.table("users").select("id,email").eq("firm_id", FIRM).eq("role", "Partner").execute().data
    assert [r["id"] for r in found] == ["u-partner"]


def test_lowercase_partner_matches_nothing():
    """Why the case mattered: this is a silent empty result, not an error."""
    db = SchemaCheckedDB({"users": [
        {"id": "u-partner", "firm_id": FIRM, "email": "p@f.in", "role": "Partner"}]})
    assert db.table("users").select("id").eq("role", "partner").execute().data == []


def test_the_notification_row_uses_real_columns_and_a_permitted_type():
    """`message`, `entity_type` and `entity_id` are not columns; the body column
    is `body`, and entity information belongs in `metadata`. `compliance_alert`
    is not in the type CHECK."""
    db = SchemaCheckedDB({"notifications": []})
    db.table("notifications").insert({
        "firm_id": FIRM, "user_id": "u-partner",
        "title": "New Government Notice: CPC",
        "body": "Reference: ABC123. Response due: 2026-09-30",
        "type": "compliance_due", "severity": "high",
        "action_url": "/income-tax/notices",
        "metadata": {"entity_type": "government_notice", "entity_id": "n1"},
        "is_read": False, "created_at": "2026-08-20T00:00:00Z",
    }).execute()
    assert db.rows["notifications"][0]["body"].startswith("Reference:")


def test_the_old_notification_shape_is_rejected():
    db = SchemaCheckedDB({"notifications": []})
    with pytest.raises(PhantomColumn):
        db.table("notifications").insert({
            "firm_id": FIRM, "user_id": "u1", "title": "t",
            "message": "not a column", "type": "compliance_due", "severity": "high",
        }).execute()


def test_compliance_alert_is_not_a_permitted_notification_type():
    db = SchemaCheckedDB({"notifications": []})
    with pytest.raises(CheckViolation):
        db.table("notifications").insert({
            "firm_id": FIRM, "user_id": "u1", "title": "t", "body": "b",
            "type": "compliance_alert", "severity": "high",
        }).execute()


# ── Vacuity guard ────────────────────────────────────────────────────────────

def test_the_double_still_rejects_a_phantom_column():
    """If the double stopped checking, every assertion above would pass while
    proving nothing about column names."""
    db = SchemaCheckedDB({"portal_messages": []})
    with pytest.raises(PhantomColumn):
        db.table("portal_messages").select("id, text").execute()
