"""
Client-assignment scope (M2) on the four GST note-type routers:
credit_notes.py, debit_notes.py, purchase_credit_notes.py, sales_debit_notes.py.

None of the four imported core.authz at all before this fix — the exact same
shape as sales_invoices.py/purchase_bills.py before their own fix earlier in
this sweep. list_*/create_* took client_id from the query/body and never
checked it; get_*/update_*/issue_*/delete_* (and debit_notes.py's/
purchase_credit_notes.py's upload/document-url pair) are row-addressed and
checked only firm_id — so any Executive/Reviewer/Manager in the firm could
read, edit, issue or delete another staff member's assigned client's notes,
and (document-url) mint a live signed Storage URL to another client's
attachment.

Each router gets its own `_assert_*_scope(current_user, id) -> client_id`
resolver: `(row_exists, client_id)` lookup, then can_access_client (not
assert_client_access) with ONE fixed message for every failure branch —
missing, wrong firm, and right firm but unassigned all read identically, in
both mock and live mode — mirroring year_end.py's `_assert_engagement_scope`,
the most rigorous shape established in this sweep, rather than the older
permissive-in-mock-mode/id-embedded-message shape sales_invoices.py used
before it.
"""
import asyncio
import pytest
from fastapi import HTTPException

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "e@f.test", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "email": "m@f.test", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest, on all four note routers at once."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    for mod in (cn, dn, pcn, sdn):
        monkeypatch.setattr(mod, "assert_client_access", _assert)
        monkeypatch.setattr(mod, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    cn.MOCK_CREDIT_NOTES.clear(); cn.MOCK_CREDIT_NOTE_LINES.clear()
    dn.MOCK_DEBIT_NOTES.clear(); dn.MOCK_DEBIT_NOTE_LINES.clear()
    pcn.MOCK_PURCHASE_CREDIT_NOTES.clear(); pcn.MOCK_PURCHASE_CREDIT_NOTE_LINES.clear()
    sdn.MOCK_SALES_DEBIT_NOTES.clear(); sdn.MOCK_SALES_DEBIT_NOTE_LINES.clear()


def _row(client_id, note_id, **extra):
    return {"id": note_id, "firm_id": FIRM, "client_id": client_id, "status": "draft", **extra}


# ══════════════════════════════════════════════════════════════════════════
# credit_notes.py
# ══════════════════════════════════════════════════════════════════════════

def test_listing_credit_notes_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        cn.list_credit_notes(client_id=THEIRS, customer_id=None, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_credit_notes_for_an_own_client_is_allowed(deny):
    resp = cn.list_credit_notes(client_id=MINE, customer_id=None, current_user=EXEC_USER)
    assert resp["success"] is True


def test_creating_a_credit_note_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        cn.create_credit_note(
            cn.CreditNoteIn(client_id=THEIRS, customer_id="CUST1", credit_note_date="2025-06-01",
                             lines=[{"description": "x", "rate_paise": 100, "quantity": 1,
                                     "gst_rate_percent": 18.0, "service_catalogue_id": "SVC-1"}]),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert cn.MOCK_CREDIT_NOTES == []


def test_getting_a_hidden_clients_credit_note_is_refused(deny):
    cn.MOCK_CREDIT_NOTES.append(_row(THEIRS, "CN1"))
    with pytest.raises(HTTPException) as exc:
        cn.get_credit_note("CN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_an_own_clients_credit_note_is_allowed(deny):
    cn.MOCK_CREDIT_NOTES.append(_row(MINE, "CN1"))
    resp = cn.get_credit_note("CN1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_updating_a_hidden_clients_credit_note_is_refused(deny):
    cn.MOCK_CREDIT_NOTES.append(_row(THEIRS, "CN1"))
    with pytest.raises(HTTPException) as exc:
        cn.update_credit_note("CN1", cn.CreditNoteUpdateIn(reason="oops"), current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert cn.MOCK_CREDIT_NOTES[0].get("reason") is None


def test_updating_an_own_clients_credit_note_is_allowed(deny):
    cn.MOCK_CREDIT_NOTES.append(_row(MINE, "CN1"))
    resp = cn.update_credit_note("CN1", cn.CreditNoteUpdateIn(reason="oops"), current_user=MANAGER_USER)
    assert resp["success"] is True


def test_issuing_a_hidden_clients_credit_note_is_refused(deny):
    cn.MOCK_CREDIT_NOTES.append(_row(THEIRS, "CN1"))
    with pytest.raises(HTTPException) as exc:
        cn.issue_credit_note("CN1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert cn.MOCK_CREDIT_NOTES[0]["status"] == "draft"


def test_deleting_a_hidden_clients_credit_note_is_refused(deny):
    cn.MOCK_CREDIT_NOTES.append(_row(THEIRS, "CN1"))
    with pytest.raises(HTTPException) as exc:
        cn.delete_credit_note("CN1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert len(cn.MOCK_CREDIT_NOTES) == 1


def test_deleting_an_own_clients_credit_note_is_allowed(deny):
    cn.MOCK_CREDIT_NOTES.append(_row(MINE, "CN1"))
    resp = cn.delete_credit_note("CN1", current_user=MANAGER_USER)
    assert resp["success"] is True


def test_hidden_and_missing_credit_note_errors_match(deny):
    # Same id in both scenarios — absent from the store, then present but
    # belonging to another client — so the message can only differ if the
    # wording itself differs between the two branches.
    with pytest.raises(HTTPException) as exc_missing:
        cn.get_credit_note("CN1", current_user=EXEC_USER)
    cn.MOCK_CREDIT_NOTES.append(_row(THEIRS, "CN1"))
    with pytest.raises(HTTPException) as exc_hidden:
        cn.get_credit_note("CN1", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# debit_notes.py
# ══════════════════════════════════════════════════════════════════════════

def test_listing_debit_notes_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        dn.list_debit_notes(client_id=THEIRS, vendor_id=None, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_debit_notes_for_an_own_client_is_allowed(deny):
    resp = dn.list_debit_notes(client_id=MINE, vendor_id=None, current_user=EXEC_USER)
    assert resp["success"] is True


def test_creating_a_debit_note_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        dn.create_debit_note(
            dn.DebitNoteIn(client_id=THEIRS, vendor_id="VEND1", debit_note_date="2025-06-01",
                           lines=[{"description": "x", "rate_paise": 100, "quantity": 1,
                                   "gst_rate_percent": 18.0, "service_catalogue_id": "SVC-1"}]),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert dn.MOCK_DEBIT_NOTES == []


def test_getting_a_hidden_clients_debit_note_is_refused(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(THEIRS, "DN1"))
    with pytest.raises(HTTPException) as exc:
        dn.get_debit_note("DN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_an_own_clients_debit_note_is_allowed(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(MINE, "DN1"))
    resp = dn.get_debit_note("DN1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_updating_a_hidden_clients_debit_note_is_refused(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(THEIRS, "DN1"))
    with pytest.raises(HTTPException) as exc:
        dn.update_debit_note("DN1", dn.DebitNoteUpdateIn(reason="oops"), current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_updating_an_own_clients_debit_note_is_allowed(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(MINE, "DN1"))
    resp = dn.update_debit_note("DN1", dn.DebitNoteUpdateIn(reason="oops"), current_user=MANAGER_USER)
    assert resp["success"] is True


def test_uploading_a_debit_note_document_for_a_hidden_client_is_refused(deny):
    from fastapi import UploadFile
    import io
    upload = UploadFile(filename="scan.pdf", file=io.BytesIO(b"pdf-bytes"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dn.upload_debit_note_document(file=upload, client_id=THEIRS, current_user=MANAGER_USER))
    assert exc.value.status_code == 404


def test_getting_a_hidden_clients_debit_note_document_url_is_refused(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(THEIRS, "DN1", document_url="mock/some/path"))
    with pytest.raises(HTTPException) as exc:
        dn.get_debit_note_document_url("DN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_an_own_clients_debit_note_document_url_is_allowed(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(MINE, "DN1", document_url="mock/some/path"))
    resp = dn.get_debit_note_document_url("DN1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_issuing_a_hidden_clients_debit_note_is_refused(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(THEIRS, "DN1"))
    with pytest.raises(HTTPException) as exc:
        dn.issue_debit_note("DN1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert dn.MOCK_DEBIT_NOTES[0]["status"] == "draft"


def test_deleting_a_hidden_clients_debit_note_is_refused(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(THEIRS, "DN1"))
    with pytest.raises(HTTPException) as exc:
        dn.delete_debit_note("DN1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert len(dn.MOCK_DEBIT_NOTES) == 1


def test_deleting_an_own_clients_debit_note_is_allowed(deny):
    dn.MOCK_DEBIT_NOTES.append(_row(MINE, "DN1"))
    resp = dn.delete_debit_note("DN1", current_user=MANAGER_USER)
    assert resp["success"] is True


def test_hidden_and_missing_debit_note_errors_match(deny):
    with pytest.raises(HTTPException) as exc_missing:
        dn.get_debit_note("DN1", current_user=EXEC_USER)
    dn.MOCK_DEBIT_NOTES.append(_row(THEIRS, "DN1"))
    with pytest.raises(HTTPException) as exc_hidden:
        dn.get_debit_note("DN1", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# purchase_credit_notes.py
# ══════════════════════════════════════════════════════════════════════════

def test_listing_purchase_credit_notes_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        pcn.list_purchase_credit_notes(client_id=THEIRS, vendor_id=None, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_purchase_credit_notes_for_an_own_client_is_allowed(deny):
    resp = pcn.list_purchase_credit_notes(client_id=MINE, vendor_id=None, current_user=EXEC_USER)
    assert resp["success"] is True


def test_creating_a_purchase_credit_note_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        pcn.create_purchase_credit_note(
            pcn.PurchaseCreditNoteIn(client_id=THEIRS, vendor_id="VEND1", credit_note_date="2025-06-01",
                                     lines=[{"description": "x", "rate_paise": 100, "quantity": 1,
                                             "gst_rate_percent": 18.0, "service_catalogue_id": "SVC-1"}]),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert pcn.MOCK_PURCHASE_CREDIT_NOTES == []


def test_getting_a_hidden_clients_purchase_credit_note_is_refused(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(THEIRS, "PCN1"))
    with pytest.raises(HTTPException) as exc:
        pcn.get_purchase_credit_note("PCN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_an_own_clients_purchase_credit_note_is_allowed(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(MINE, "PCN1"))
    resp = pcn.get_purchase_credit_note("PCN1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_updating_a_hidden_clients_purchase_credit_note_is_refused(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(THEIRS, "PCN1"))
    with pytest.raises(HTTPException) as exc:
        pcn.update_purchase_credit_note("PCN1", pcn.PurchaseCreditNoteUpdateIn(reason="oops"), current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_updating_an_own_clients_purchase_credit_note_is_allowed(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(MINE, "PCN1"))
    resp = pcn.update_purchase_credit_note("PCN1", pcn.PurchaseCreditNoteUpdateIn(reason="oops"), current_user=MANAGER_USER)
    assert resp["success"] is True


def test_uploading_a_purchase_credit_note_document_for_a_hidden_client_is_refused(deny):
    from fastapi import UploadFile
    import io
    upload = UploadFile(filename="scan.pdf", file=io.BytesIO(b"pdf-bytes"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(pcn.upload_purchase_credit_note_document(file=upload, client_id=THEIRS, current_user=MANAGER_USER))
    assert exc.value.status_code == 404


def test_getting_a_hidden_clients_purchase_credit_note_document_url_is_refused(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(THEIRS, "PCN1", document_url="mock/some/path"))
    with pytest.raises(HTTPException) as exc:
        pcn.get_purchase_credit_note_document_url("PCN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_an_own_clients_purchase_credit_note_document_url_is_allowed(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(MINE, "PCN1", document_url="mock/some/path"))
    resp = pcn.get_purchase_credit_note_document_url("PCN1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_issuing_a_hidden_clients_purchase_credit_note_is_refused(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(THEIRS, "PCN1"))
    with pytest.raises(HTTPException) as exc:
        pcn.issue_purchase_credit_note("PCN1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert pcn.MOCK_PURCHASE_CREDIT_NOTES[0]["status"] == "draft"


def test_deleting_a_hidden_clients_purchase_credit_note_is_refused(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(THEIRS, "PCN1"))
    with pytest.raises(HTTPException) as exc:
        pcn.delete_purchase_credit_note("PCN1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert len(pcn.MOCK_PURCHASE_CREDIT_NOTES) == 1


def test_deleting_an_own_clients_purchase_credit_note_is_allowed(deny):
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(MINE, "PCN1"))
    resp = pcn.delete_purchase_credit_note("PCN1", current_user=MANAGER_USER)
    assert resp["success"] is True


def test_hidden_and_missing_purchase_credit_note_errors_match(deny):
    with pytest.raises(HTTPException) as exc_missing:
        pcn.get_purchase_credit_note("PCN1", current_user=EXEC_USER)
    pcn.MOCK_PURCHASE_CREDIT_NOTES.append(_row(THEIRS, "PCN1"))
    with pytest.raises(HTTPException) as exc_hidden:
        pcn.get_purchase_credit_note("PCN1", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# sales_debit_notes.py
# ══════════════════════════════════════════════════════════════════════════

def test_listing_sales_debit_notes_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        sdn.list_sales_debit_notes(client_id=THEIRS, customer_id=None, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_sales_debit_notes_for_an_own_client_is_allowed(deny):
    resp = sdn.list_sales_debit_notes(client_id=MINE, customer_id=None, current_user=EXEC_USER)
    assert resp["success"] is True


def test_creating_a_sales_debit_note_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        sdn.create_sales_debit_note(
            sdn.SalesDebitNoteIn(client_id=THEIRS, customer_id="CUST1", debit_note_date="2025-06-01",
                                 lines=[{"description": "x", "rate_paise": 100, "quantity": 1,
                                         "gst_rate_percent": 18.0, "service_catalogue_id": "SVC-1"}]),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert sdn.MOCK_SALES_DEBIT_NOTES == []


def test_getting_a_hidden_clients_sales_debit_note_is_refused(deny):
    sdn.MOCK_SALES_DEBIT_NOTES.append(_row(THEIRS, "SDN1"))
    with pytest.raises(HTTPException) as exc:
        sdn.get_sales_debit_note("SDN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_an_own_clients_sales_debit_note_is_allowed(deny):
    sdn.MOCK_SALES_DEBIT_NOTES.append(_row(MINE, "SDN1"))
    resp = sdn.get_sales_debit_note("SDN1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_updating_a_hidden_clients_sales_debit_note_is_refused(deny):
    sdn.MOCK_SALES_DEBIT_NOTES.append(_row(THEIRS, "SDN1"))
    with pytest.raises(HTTPException) as exc:
        sdn.update_sales_debit_note("SDN1", sdn.SalesDebitNoteUpdateIn(reason="oops"), current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_updating_an_own_clients_sales_debit_note_is_allowed(deny):
    sdn.MOCK_SALES_DEBIT_NOTES.append(_row(MINE, "SDN1"))
    resp = sdn.update_sales_debit_note("SDN1", sdn.SalesDebitNoteUpdateIn(reason="oops"), current_user=MANAGER_USER)
    assert resp["success"] is True


def test_issuing_a_hidden_clients_sales_debit_note_is_refused(deny):
    sdn.MOCK_SALES_DEBIT_NOTES.append(_row(THEIRS, "SDN1"))
    with pytest.raises(HTTPException) as exc:
        sdn.issue_sales_debit_note("SDN1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert sdn.MOCK_SALES_DEBIT_NOTES[0]["status"] == "draft"


def test_deleting_a_hidden_clients_sales_debit_note_is_refused(deny):
    sdn.MOCK_SALES_DEBIT_NOTES.append(_row(THEIRS, "SDN1"))
    with pytest.raises(HTTPException) as exc:
        sdn.delete_sales_debit_note("SDN1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert len(sdn.MOCK_SALES_DEBIT_NOTES) == 1


def test_deleting_an_own_clients_sales_debit_note_is_allowed(deny):
    sdn.MOCK_SALES_DEBIT_NOTES.append(_row(MINE, "SDN1"))
    resp = sdn.delete_sales_debit_note("SDN1", current_user=MANAGER_USER)
    assert resp["success"] is True


def test_hidden_and_missing_sales_debit_note_errors_match(deny):
    with pytest.raises(HTTPException) as exc_missing:
        sdn.get_sales_debit_note("SDN1", current_user=EXEC_USER)
    sdn.MOCK_SALES_DEBIT_NOTES.append(_row(THEIRS, "SDN1"))
    with pytest.raises(HTTPException) as exc_hidden:
        sdn.get_sales_debit_note("SDN1", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# Live-mode (FakeDB) — exercises each router's _owner resolver's own SQL
# lookup branch, not just the mock-store branch above. can_access_client
# stays patched by `deny`; FakeDB only backs the resolver's own row fetch —
# same split as test_year_end_engagements_client_scope.py's e2e tests.
# ══════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch, modules):
    db = FakeDB()
    wire_e2e(monkeypatch, db, modules)
    return db


def test_e2e_getting_a_hidden_clients_credit_note_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [cn])
    db.seed("credit_notes", {"id": "CN1", "firm_id": FIRM, "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        cn.get_credit_note("CN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert deny == [THEIRS]


def test_e2e_getting_an_own_clients_credit_note_is_allowed(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [cn])
    db.seed("credit_notes", {"id": "CN1", "firm_id": FIRM, "client_id": MINE, "status": "draft"})
    resp = cn.get_credit_note("CN1", current_user=EXEC_USER)
    assert resp["success"] is True
    assert deny == [MINE]


def test_e2e_getting_a_hidden_clients_debit_note_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [dn])
    db.seed("debit_notes", {"id": "DN1", "firm_id": FIRM, "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        dn.get_debit_note("DN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert deny == [THEIRS]


def test_e2e_getting_an_own_clients_debit_note_is_allowed(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [dn])
    db.seed("debit_notes", {"id": "DN1", "firm_id": FIRM, "client_id": MINE, "status": "draft"})
    resp = dn.get_debit_note("DN1", current_user=EXEC_USER)
    assert resp["success"] is True
    assert deny == [MINE]


def test_e2e_getting_a_hidden_clients_purchase_credit_note_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [pcn])
    db.seed("purchase_credit_notes", {"id": "PCN1", "firm_id": FIRM, "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        pcn.get_purchase_credit_note("PCN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert deny == [THEIRS]


def test_e2e_getting_an_own_clients_purchase_credit_note_is_allowed(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [pcn])
    db.seed("purchase_credit_notes", {"id": "PCN1", "firm_id": FIRM, "client_id": MINE, "status": "draft"})
    resp = pcn.get_purchase_credit_note("PCN1", current_user=EXEC_USER)
    assert resp["success"] is True
    assert deny == [MINE]


def test_e2e_getting_a_hidden_clients_sales_debit_note_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [sdn])
    db.seed("sales_debit_notes", {"id": "SDN1", "firm_id": FIRM, "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        sdn.get_sales_debit_note("SDN1", current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert deny == [THEIRS]


def test_e2e_getting_an_own_clients_sales_debit_note_is_allowed(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [sdn])
    db.seed("sales_debit_notes", {"id": "SDN1", "firm_id": FIRM, "client_id": MINE, "status": "draft"})
    resp = sdn.get_sales_debit_note("SDN1", current_user=EXEC_USER)
    assert resp["success"] is True
    assert deny == [MINE]


def test_e2e_missing_and_hidden_credit_notes_use_the_identical_message(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [cn])
    db.seed("credit_notes", {"id": "CN-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as missing:
        cn._assert_cn_scope(EXEC_USER, "CN-NOPE")
    with pytest.raises(HTTPException) as hidden:
        cn._assert_cn_scope(EXEC_USER, "CN-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail
