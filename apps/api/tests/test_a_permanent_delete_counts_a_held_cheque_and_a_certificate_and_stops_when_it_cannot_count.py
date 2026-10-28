"""A customer's or vendor's permanent delete counts the cheque it would lose and the certificate it would lose, and stops when it cannot count (POST-A-334; 28-10-2026).

THE TWO DEFECTS
    1. Every foreign key that references `customers` or `vendors` is ON DELETE CASCADE and the application's list of what blocks a
       permanent delete was written by hand. Six tables that cascade were not on it. The decision (the three tests: lawful, safe for the
       data of a CA's clients, best for the product): `post_dated_cheques` (both sides: a memorandum of a cheque held or issued) and
       `tds_lower_deduction_certificates` (a section 197 certificate the withholding reads) now block, UNDATED, so the refusal claims no
       statutory clock for them; the link, the statement mail log and the draft interest figure go with the party as they always did, for
       the reasons recorded in `test_the_party_delete_guard_names_every_table_that_cascades_from_a_party_pg.py`.
    2. The count itself answered ZERO for a table it could not read, under a comment saying a missing or locked table "must never mask a
       dependency": it masked it, and the records were cascaded away with the party. An unreadable table now stops the delete, in words,
       and the dependency read the screen opens the dialog with says the same instead of a list with nothing in it.
"""
from __future__ import annotations

import pathlib

import pytest
from fastapi import HTTPException

import routers.customers as cu
import routers.vendors as vn
from services import party_erasure
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}
WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


class _Unreadable:
    """A database that raises for one table, as a locked or missing one does."""

    def __init__(self, inner, table):
        self.inner, self.table_name = inner, table

    def table(self, name):
        if name == self.table_name:
            raise RuntimeError(f"permission denied for table {name}")
        return self.inner.table(name)

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


def _world(monkeypatch, *, unreadable=None):
    db = FakeDB()
    db.seed("customers", {"id": "cust-1", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme", "opening_balance_paise": 0, "is_active": True})
    db.seed("vendors", {"id": "vend-1", "firm_id": FIRM, "client_id": CLIENT, "name": "Zed", "opening_balance_paise": 0, "is_active": True})
    seen = _Unreadable(db, unreadable) if unreadable else db
    wire_e2e(monkeypatch, db, [cu, vn])
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: seen)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: seen)
    monkeypatch.setattr(cu, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(vn, "log_event", lambda *a, **k: None)
    return db


# ── the two tables that were not counted ───────────────────────────────────────────────────────────────────────────────
def test_a_held_cheque_blocks_a_customers_permanent_delete_without_a_statutory_clock(monkeypatch):
    db = _world(monkeypatch)
    db.seed("post_dated_cheques", {"id": "chq-1", "firm_id": FIRM, "client_id": CLIENT, "customer_id": "cust-1", "cheque_date": "2019-04-01"})
    deps = cu._customer_dependencies(db, "cust-1", 0)
    assert deps["counts"]["cheques"] == 1 and deps["has_any"] is True
    assert deps["latest_record_date"] is None, "undated on purpose: the refusal must not claim a retention date for a memorandum"
    with pytest.raises(HTTPException) as e:
        cu.delete_customer("cust-1", PARTNER, permanent=True)
    assert e.value.status_code == 409 and "retention date cannot be computed" in e.value.detail and "post-dated cheque" in e.value.detail
    assert [r["id"] for r in db.rows("customers")] == ["cust-1"]


def test_a_cheque_and_a_certificate_block_a_vendors_permanent_delete(monkeypatch):
    db = _world(monkeypatch)
    db.seed("post_dated_cheques", {"id": "chq-1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "vend-1"})
    deps = vn._vendor_dependencies(db, "vend-1", 0)
    assert deps["counts"]["cheques"] == 1 and deps["counts"]["certificates"] == 0 and deps["has_any"] is True
    db.rows("post_dated_cheques").clear()
    db.seed("tds_lower_deduction_certificates", {"id": "cert-1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "vend-1",
                                                 "valid_from": "2025-04-01", "valid_to": "2026-03-31"})
    deps = vn._vendor_dependencies(db, "vend-1", 0)
    assert deps["counts"]["certificates"] == 1 and deps["latest_record_date"] is None
    with pytest.raises(HTTPException) as e:
        vn.delete_vendor("vend-1", PARTNER, permanent=True)
    assert e.value.status_code == 409 and [r["id"] for r in db.rows("vendors")] == ["vend-1"]


def test_a_party_with_nothing_on_record_is_still_deleted(monkeypatch):
    db = _world(monkeypatch)
    assert cu.delete_customer("cust-1", PARTNER, permanent=True)["data"]["deleted"] is True
    assert vn.delete_vendor("vend-1", PARTNER, permanent=True)["data"]["deleted"] is True
    assert db.rows("customers") == [] and db.rows("vendors") == []


# ── a table that cannot be read ────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("table", ["client_sales_invoices", "post_dated_cheques"])
def test_an_unreadable_table_stops_a_customers_permanent_delete_in_words(monkeypatch, table):
    db = _world(monkeypatch, unreadable=table)
    with pytest.raises(HTTPException) as e:
        cu.delete_customer("cust-1", PARTNER, permanent=True)
    assert e.value.status_code == 503 and "nothing was deleted" in e.value.detail and "deactivate the customer" in e.value.detail
    assert [r["id"] for r in db.rows("customers")] == ["cust-1"], "the customer must still be there"


@pytest.mark.parametrize("table", ["purchase_bills", "tds_lower_deduction_certificates"])
def test_an_unreadable_table_stops_a_vendors_permanent_delete_in_words(monkeypatch, table):
    db = _world(monkeypatch, unreadable=table)
    with pytest.raises(HTTPException) as e:
        vn.delete_vendor("vend-1", PARTNER, permanent=True)
    assert e.value.status_code == 503 and "nothing was deleted" in e.value.detail
    assert [r["id"] for r in db.rows("vendors")] == ["vend-1"]


def test_the_dependency_read_the_dialog_opens_with_says_it_could_not_check_and_not_that_there_is_nothing(monkeypatch):
    _world(monkeypatch, unreadable="receipts")
    out = cu.get_customer_dependencies("cust-1", PARTNER)
    assert out["success"] is False and "Could not check" in out["error"] and "receipts" in out["error"]
    _world(monkeypatch, unreadable="debit_notes")
    out = vn.get_vendor_dependencies("vend-1", PARTNER)
    assert out["success"] is False and "Could not check" in out["error"] and "debit notes" in out["error"]


def test_a_readable_world_still_answers_the_dependency_read_as_before(monkeypatch):
    _world(monkeypatch)
    out = cu.get_customer_dependencies("cust-1", PARTNER)
    assert out["success"] is True and out["data"]["can_delete"] is True and out["data"]["dependencies"]["cheques"] == 0
    out = vn.get_vendor_dependencies("vend-1", PARTNER)
    assert out["success"] is True and out["data"]["dependencies"]["certificates"] == 0


def test_the_unreadable_sentence_names_each_table_in_words_a_ca_reads():
    sentence = party_erasure.unreadable_refusal("customer", ["cheques", "credit_notes"])
    assert "post-dated cheques, credit notes" in sentence and "_" not in sentence


# ── the screen names what the server counts ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("page,tables", [
    ("sales", cu._DEPENDENCY_TABLES),
    ("purchases", vn._VENDOR_DEPENDENCY_TABLES),
])
def test_the_delete_dialog_has_a_line_for_every_kind_of_record_the_server_counts(page, tables):
    """A kind of record the server counts and the dialog does not name is a refusal with nothing listed under it."""
    source = (WEB / "app" / "clients" / "[id]" / page / "page.tsx").read_text(encoding="utf-8")
    for label, _table, _date in tables:
        assert f'["{label}", "' in source, f"apps/web/app/clients/[id]/{page}/page.tsx names no line for {label!r}"
    assert '["opening_balance", "Opening balance"]' in source
