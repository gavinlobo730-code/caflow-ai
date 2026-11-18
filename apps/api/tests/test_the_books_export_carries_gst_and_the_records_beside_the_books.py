"""
POST-A-205, slice 3 — the books export carries the records beside the books and, under the GST permission, the client's GST records.

WHAT THIS ASSERTS
    * every new file is in the archive and the manifest, with the client's rows only: another client's and another firm's rows, seeded into every new table, are
      in no file, and each file is counted by the database and matches;
    * the GST files belong to the `gst` tier, so a Partner blocked from GST on the Team screen is not handed them and is told so, while the books still come;
    * a return's JSON is exported as the return (it is the GST return JSON the item asked for), and nothing that names a payroll record is added;
    * the lists of what is not here no longer say the records beside the books, the challans or the GST returns are missing, and the screen's sentences agree
      (read from the Python side, because the service owns what is exported).
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

import routers.data_export as route
import services.client_books_export_service as svc
from core.permissions import Role
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "firm-1", "firm-2"
CLIENT, OTHER_CLIENT = "client-a", "client-b"

_BESIDE = ("cost_centres", "party_credit_balances", "party_credit_ledger", "loans", "fixed_deposits", "related_party_loans", "fx_revaluations",
           "fx_adjustments", "price_lists", "price_list_items", "recurring_journal_templates", "recurring_invoice_templates",
           "recurring_purchase_bill_templates", "sales_quotations", "sales_quotation_lines", "sales_orders", "sales_order_lines", "purchase_orders",
           "purchase_order_lines", "delivery_challans", "delivery_challan_lines", "delivery_challan_returns", "goods_receipt_notes", "goods_receipt_lines",
           "bills_of_entry", "post_dated_cheques")
_GST = ("client_gst_registrations", "gstr1_returns", "gstr3b_returns", "gst_challans", "gstr2a_records", "gstr2b_reconciliations", "itc_reversal_register",
        "rcm_documents", "einvoice_records", "eway_bill_records")
_GST_FILES = {f"{t}.csv" for t in _GST}

_CARD = Path(__file__).resolve().parents[3] / "apps/web/components/reports/BooksExportCard.tsx"


def _books() -> FakeDB:
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Anand Textiles", "legal_name": "Anand Textiles Pvt Ltd"})
    for table in (*_BESIDE, *_GST):
        db.seed(table, {"id": f"ours-{table}", "firm_id": FIRM, "client_id": CLIENT, "notes": "ours"})
        db.seed(table, {"id": f"otherclient-{table}", "firm_id": FIRM, "client_id": OTHER_CLIENT, "notes": "StrangerClient"})
        db.seed(table, {"id": f"otherfirm-{table}", "firm_id": OTHER_FIRM, "client_id": CLIENT, "notes": "StrangerFirm"})
    db.seed("gstr1_returns", {"id": "g1-june", "firm_id": FIRM, "client_id": CLIENT, "period": "2026-06",
                              "payload_json": {"gstin": "27AAAPL1234C1ZV", "fp": "062026", "b2b": []}})
    return db


def _unzip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def _rows(files: dict[str, bytes], name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8-sig"))))


@pytest.fixture
def out():
    return svc.build(_books(), FIRM, CLIENT)


@pytest.fixture
def files(out):
    return _unzip(out.content)


def test_every_new_file_is_in_the_archive_and_the_manifest_with_the_clients_rows_only(out, files):
    listed = {f["name"]: f for f in out.manifest["files"]}
    for table in (*_BESIDE, *_GST):
        name = f"{table}.csv"
        assert name in files and name in listed, name
        ids = {r["id"] for r in _rows(files, name)}
        assert f"ours-{table}" in ids, name
        assert not any(i.startswith(("otherclient-", "otherfirm-")) for i in ids), name
        assert listed[name]["matches_database_count"] is True, name
    everything = b"".join(v for k, v in files.items() if k.endswith(".csv")).decode("utf-8-sig")
    assert "StrangerFirm" not in everything and "StrangerClient" not in everything
    assert out.manifest["schema"] == "practicesync-books-export/3"


def test_a_returns_json_is_exported_as_the_return(files):
    june = next(r for r in _rows(files, "gstr1_returns.csv") if r["id"] == "g1-june")
    assert json.loads(june["payload_json"]) == {"b2b": [], "fp": "062026", "gstin": "27AAAPL1234C1ZV"}


def test_the_gst_files_are_the_gst_tier_and_the_rest_the_books():
    tiers = {s.file: s.tier for s in svc._SECTIONS}
    assert {f for f, t in tiers.items() if t == "gst"} == _GST_FILES
    for table in _BESIDE:
        assert tiers[f"{table}.csv"] == "accounting", table
    assert "gst" in svc.TIERS


def _partner(**blocked) -> dict:
    return {"id": "u1", "auth_user_id": "auth-1", "email": "p@firm.test", "firm_id": FIRM, "role": Role.PARTNER.value,
            "permission_overrides": {f"{tier}:read": False for tier in blocked}}


@pytest.fixture
def door(monkeypatch):
    audit = FakeDB()
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: audit)
    monkeypatch.setattr(route, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(route, "_prod_db", lambda: _books())
    logged: list[tuple] = []
    monkeypatch.setattr(route.audit_service, "log_event", lambda firm, kind, entity, action, **kw: logged.append((action, kw)))
    return logged


def test_a_partner_blocked_from_gst_gets_no_gst_file_and_is_told(door):
    files = _unzip(route.export_client_books(client_id=CLIENT, current_user=_partner(gst=True)).body)
    assert not (_GST_FILES & set(files)) and "delivery_challans.csv" in files and "journal_entries.csv" in files
    manifest = json.loads(files["manifest.json"])
    assert len(manifest["left_out_for_the_persons_access"]) == 1 and "GST" in manifest["left_out_for_the_persons_access"][0]
    assert door[-1][0] == "export_completed" and door[-1][1]["new_data"]["left_out_tiers"] == ["gst"]


def test_a_partner_with_no_block_gets_the_gst_files(door):
    files = _unzip(route.export_client_books(client_id=CLIENT, current_user=_partner()).body)
    assert _GST_FILES <= set(files)


def test_what_is_not_here_no_longer_names_what_is_and_the_screen_agrees(files):
    manifest = json.loads(files["manifest.json"])
    text = " ".join(manifest["not_included"])
    for now_exported in ("customer and vendor advances", "cost centres", "customer rate cards", "orders and quotations", "Delivery challans",
                         "GST returns and their JSON", "e-invoice and e-way bill records"):
        assert now_exported not in text, now_exported
    refs = " ".join(manifest["ids_that_lead_to_tables_not_in_the_export"])
    assert "cost_centre_id" not in refs and "bill_of_entry_id" not in refs and "purchase_order_line_id" not in refs
    card = _CARD.read_text(encoding="utf-8")
    not_yet = " ".join(re.search(r"Not in it yet:</span>(.*?)</p>", card, re.S).group(1).split())
    for now_exported in ("GST returns", "advances", "loans", "orders", "challans", "rate cards"):
        assert now_exported not in not_yet, now_exported
    in_it = " ".join(re.search(r"In it:</span>(.*?)</p>", card, re.S).group(1).split())
    for exported in ("GST", "e-way bill", "delivery and job-work challans", "price lists", "the bank or GST"):
        assert exported in in_it, exported
