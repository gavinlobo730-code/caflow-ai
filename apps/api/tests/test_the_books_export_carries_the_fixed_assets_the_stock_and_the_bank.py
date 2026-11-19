"""
POST-A-205, slice 2 — the books export carries the registers beside the ledger: fixed assets, stock and the bank.

WHAT THIS ASSERTS
    * every new file is in the archive and the manifest, with the client's rows only: another client's and another firm's rows, seeded into every new table, are in
      no file;
    * a bank reconciliation match, which has a firm and no client, is read by the ids of the client's own bank lines AND the firm, so another firm's match on the
      same line id is not exported;
    * the stock position is the stock ledger file's own arithmetic per item, quantity exact to three decimals (a string and a number from PostgREST alike) and value
      in paise, and an item moved that is not in the item master is named as a problem;
    * the lists of what is not here no longer say the bank, fixed assets or stock are missing, still say payroll is, and the screen's "Not in it yet" sentence agrees
      with them (read from the Python side, because the service owns what is exported).
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

import services.client_books_export_service as svc
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "firm-1", "firm-2"
CLIENT, OTHER_CLIENT = "client-a", "client-b"

_NEW_FILES = {
    "fixed_assets.csv": "fixed_assets", "fixed_asset_movements.csv": "fixed_asset_movements",
    "fixed_asset_verifications.csv": "fixed_asset_verifications", "fixed_asset_verification_findings.csv": "fixed_asset_verification_findings",
    "capital_work_in_progress.csv": "capital_work_in_progress", "cwip_additions.csv": "cwip_additions",
    "service_catalogue.csv": "service_catalogue", "godowns.csv": "godowns", "inventory_batches.csv": "inventory_batches",
    "inventory_stock_ledger.csv": "inventory_stock_ledger", "stock_count_sessions.csv": "stock_count_sessions", "stock_count_lines.csv": "stock_count_lines",
    "purchase_bill_landed_costs.csv": "purchase_bill_landed_costs", "stock_effect_settlements.csv": "stock_effect_settlements",
    "bank_accounts.csv": "bank_accounts", "bank_statements.csv": "bank_statements", "bank_transactions.csv": "bank_transactions",
    "bank_transaction_splits.csv": "bank_transaction_splits", "bank_reconciliations.csv": "bank_reconciliations", "bank_matching_rules.csv": "bank_matching_rules",
}

_CARD = Path(__file__).resolve().parents[3] / "apps/web/components/reports/BooksExportCard.tsx"


def _books() -> FakeDB:
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Anand Textiles", "legal_name": "Anand Textiles Pvt Ltd"})
    db.seed("clients", {"id": OTHER_CLIENT, "firm_id": FIRM, "client_name": "Other Co"})
    for table in _NEW_FILES.values():
        extra = {"service_catalogue_id": "item-cloth", "quantity_delta": 0, "value_delta_paise": 0} if table == "inventory_stock_ledger" else {}
        db.seed(table, {"id": f"ours-{table}", "firm_id": FIRM, "client_id": CLIENT, "notes": "ours", **extra})
        db.seed(table, {"id": f"otherclient-{table}", "firm_id": FIRM, "client_id": OTHER_CLIENT, "notes": "StrangerClient"})
        db.seed(table, {"id": f"otherfirm-{table}", "firm_id": OTHER_FIRM, "client_id": CLIENT, "notes": "StrangerFirm"})
    # the item master and movements the stock position is made of (quantities as PostgREST sends NUMERIC: numbers or strings)
    db.seed("service_catalogue", {"id": "item-cloth", "firm_id": FIRM, "client_id": CLIENT, "name": "Cloth", "unit": "MTR", "kind": "goods"})
    for sid, item, qty, value in (("m1", "item-cloth", "10.500", 105000), ("m2", "item-cloth", -2.125, -21250), ("m3", "item-cloth", "0.001", 10),
                                  ("m4", "item-gone", 3, 300)):
        db.seed("inventory_stock_ledger", {"id": sid, "firm_id": FIRM, "client_id": CLIENT, "service_catalogue_id": item,
                                           "quantity_delta": qty, "value_delta_paise": value})
    db.seed("inventory_stock_ledger", {"id": "m-other", "firm_id": FIRM, "client_id": OTHER_CLIENT, "service_catalogue_id": "item-cloth",
                                       "quantity_delta": 999, "value_delta_paise": 999})
    # a match on the client's own bank line, another firm's match on the same line id, and a match on another client's line
    db.seed("bank_reconciliation_matches", {"id": "bm1", "firm_id": FIRM, "bank_transaction_id": "ours-bank_transactions", "match_type": "manual"})
    db.seed("bank_reconciliation_matches", {"id": "bm-x", "firm_id": OTHER_FIRM, "bank_transaction_id": "ours-bank_transactions", "match_type": "StrangerFirm"})
    db.seed("bank_reconciliation_matches", {"id": "bm-y", "firm_id": FIRM, "bank_transaction_id": "otherclient-bank_transactions", "match_type": "StrangerClient"})
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


def test_every_new_register_is_a_file_in_the_archive_and_the_manifest(files):
    listed = {f["name"] for f in json.loads(files["manifest.json"])["files"]}
    for name in [*_NEW_FILES, "bank_reconciliation_matches.csv", "stock_position_from_the_stock_ledger_file.csv"]:
        assert name in files and name in listed, name


def test_each_new_file_holds_the_clients_rows_only(files):
    for name, table in _NEW_FILES.items():
        ids = {r["id"] for r in _rows(files, name)}
        assert f"ours-{table}" in ids, name
        assert not any(i.startswith(("otherclient-", "otherfirm-")) for i in ids), name
    everything = b"".join(v for k, v in files.items() if k.endswith(".csv")).decode("utf-8-sig")
    assert "StrangerFirm" not in everything and "StrangerClient" not in everything


def test_a_bank_match_is_read_by_the_clients_own_lines_and_the_firm(files):
    assert [r["id"] for r in _rows(files, "bank_reconciliation_matches.csv")] == ["bm1"]
    child = next(c for s in svc._SECTIONS for c in s.children if c.file == "bank_reconciliation_matches.csv")
    assert child.fk == "bank_transaction_id"


def test_each_new_file_is_counted_by_the_database_and_matches(out):
    for entry in out.manifest["files"]:
        if entry["name"] in _NEW_FILES:
            assert entry["matches_database_count"] is True, entry["name"]


def test_the_stock_position_is_the_stock_ledger_files_own_sum_per_item(files):
    position = {r["service_catalogue_id"]: r for r in _rows(files, "stock_position_from_the_stock_ledger_file.csv")}
    # recomputed by hand from the exported file, not from the seed
    by_hand: dict[str, list] = {}
    for r in _rows(files, "inventory_stock_ledger.csv"):
        acc = by_hand.setdefault(r["service_catalogue_id"], [Decimal(0), 0])
        acc[0] += Decimal(r["quantity_delta"] or "0")
        acc[1] += int(r["value_delta_paise"] or 0)
    assert set(position) == {k for k in by_hand}
    for item, (qty, value) in by_hand.items():
        assert Decimal(position[item]["quantity"]) == qty and int(position[item]["value_paise"]) == value, item
    cloth = position["item-cloth"]
    assert cloth["quantity"] == "8.376" and cloth["value_paise"] == "83760" and cloth["name"] == "Cloth" and cloth["movements"] == "4"


def test_an_item_moved_that_is_not_in_the_item_master_is_named(out):
    assert any("1 items moved in inventory_stock_ledger.csv are not in service_catalogue.csv" in p for p in out.problems)


def test_a_client_with_no_stock_has_an_empty_position_and_no_problem():
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Empty"})
    out = svc.build(db, FIRM, CLIENT)
    files = _unzip(out.content)
    assert _rows(files, "stock_position_from_the_stock_ledger_file.csv") == [] and out.problems == []


def test_a_quantity_is_written_exactly_with_at_most_three_decimals():
    assert svc._quantity_text(Decimal("8.376")) == "8.376"
    assert svc._quantity_text(Decimal("10.500")) == "10.5"
    assert svc._quantity_text(Decimal("-3")) == "-3"
    assert svc._quantity_text(Decimal("0")) == "0"
    assert svc._quantity("") == 0 and svc._quantity(None) == 0 and svc._quantity(1.1) == Decimal("1.1")


def test_what_is_not_here_no_longer_says_the_bank_the_assets_or_the_stock_are_missing(files):
    text = " ".join(json.loads(files["manifest.json"])["not_included"])
    assert "Payroll" in text
    assert "The bank: accounts" not in text and "Fixed assets, stock and stock movements" not in text
    assert "the service catalogue" not in text
    assert not any("service_catalogue_id" in ref for ref in svc.REFERENCES_NOT_EXPORTED)
    assert svc.SCHEMA.startswith("practicesync-books-export/")


def test_the_screen_says_what_the_service_exports_and_what_it_does_not():
    card = _CARD.read_text(encoding="utf-8")
    not_yet = re.search(r"Not in it yet:</span>(.*?)</p>", card, re.S)
    assert not_yet, "the card no longer has its 'Not in it yet' sentence"
    sentence = " ".join(not_yet.group(1).split())
    for still_missing in ("payroll", "uploaded documents", "the audit log", "income tax", "PDFs"):
        assert still_missing in sentence, still_missing
    for now_exported in ("the bank", "fixed assets", "stock", "service catalogue"):
        assert now_exported not in sentence, now_exported
    in_it = re.search(r"In it:</span>(.*?)</p>", card, re.S)
    assert in_it
    for exported in ("fixed assets", "stock ledger", "bank"):
        assert exported in " ".join(in_it.group(1).split()), exported
    # The TDS tier is exported (tds_deductions, tds_challans and tds_returns), so "In it" says so in the service's own tier words, and
    # "Not in it yet" names only the challans that are not files here (delivery and job-work), never challans in general.
    assert svc._TIER_WORDS["tds"] in " ".join(in_it.group(1).split())
    # Since slice 3 every challan the product records is a file (TDS, GST, delivery and job-work), so "Not in it yet" names no challan at all.
    assert "challan" not in sentence, "the card says challans are left out while they are exported"


# ── a Partner blocked from a tier is not handed its files ────────────────────────────────────────────────────

import routers.data_export as route  # noqa: E402
from core.permissions import Role  # noqa: E402
from domain.reporting.export_document import ExportRefused  # noqa: E402

_BANK_FILES = {n for n in _NEW_FILES if n.startswith("bank_")} | {"bank_reconciliation_matches.csv"}
_TDS_FILES = {"tds_deductions.csv", "tds_challans.csv", "tds_returns.csv"}


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


def test_each_section_belongs_to_the_tier_its_screens_ask():
    tiers = {s.file: s.tier for s in svc._SECTIONS}
    assert {f for f, t in tiers.items() if t == "banking"} == _BANK_FILES - {"bank_reconciliation_matches.csv"}
    assert {f for f, t in tiers.items() if t == "tds"} == _TDS_FILES
    assert set(tiers.values()) == set(svc.TIERS)


def test_a_partner_blocked_from_banking_gets_no_bank_file_and_is_told(door):
    response = route.export_client_books(client_id=CLIENT, current_user=_partner(banking=True))
    files = _unzip(response.body)
    assert not (_BANK_FILES & set(files)) and "fixed_assets.csv" in files and "journal_entries.csv" in files
    manifest = json.loads(files["manifest.json"])
    assert len(manifest["left_out_for_the_persons_access"]) == 1 and "the bank" in manifest["left_out_for_the_persons_access"][0]
    assert "blocked from it: the bank" in files["README.txt"].decode("utf-8")
    assert door[-1][0] == "export_completed" and door[-1][1]["new_data"]["left_out_tiers"] == ["banking"]


def test_a_partner_blocked_from_tds_gets_no_tds_file(door):
    files = _unzip(route.export_client_books(client_id=CLIENT, current_user=_partner(tds=True)).body)
    assert not (_TDS_FILES & set(files)) and "bank_transactions.csv" in files


def test_a_partner_blocked_from_the_books_gets_no_ledger_and_no_check_that_reads_as_balanced(door):
    files = _unzip(route.export_client_books(client_id=CLIENT, current_user=_partner(accounting=True)).body)
    for gone in ("journal_entries.csv", "journal_lines.csv", "chart_of_accounts.csv", "fixed_assets.csv", "inventory_stock_ledger.csv",
                 "trial_balance_from_the_ledger_files.csv", "stock_position_from_the_stock_ledger_file.csv"):
        assert gone not in files, gone
    checks = json.loads(files["manifest.json"])["checks"]
    assert checks["posted_lines_balance"] is None and checks["posted_entries_without_a_line"] is None
    assert "bank_transactions.csv" in files and "tds_deductions.csv" in files


def test_a_partner_blocked_from_every_tier_is_refused_in_words():
    with pytest.raises(ExportRefused, match="nothing of this client's"):
        svc.build(_books(), FIRM, CLIENT, readable_tiers=frozenset())


def test_a_partner_with_no_block_gets_every_tier_and_nothing_left_out(door):
    files = _unzip(route.export_client_books(client_id=CLIENT, current_user=_partner()).body)
    assert _BANK_FILES <= set(files) and _TDS_FILES <= set(files)
    assert json.loads(files["manifest.json"])["left_out_for_the_persons_access"] == []
    assert door[-1][1]["new_data"]["left_out_tiers"] == []
