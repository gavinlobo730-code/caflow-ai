"""The ledger an asset's accumulated depreciation is credited to, and its disposal debits, is chosen by ONE function (POST-A-345, stage 1 of 3).

WHY
    An intangible asset's amortisation is credited to the one shared Accumulated Depreciation ledger, which Schedule III places on the
    tangible line (see migration 553). The fix lets an asset NAME its ledger (`fixed_assets.accumulated_account_id`) and moves what is
    already in the shared ledger by a Partner's posting. It is safe only if an asset's two journals can never disagree about the ledger:
    a disposal that debits the shared ledger for an asset whose history is in the new one clears the wrong ledger, and the totals
    still agree while each ledger is wrong by the asset's whole accumulated figure. So both journals ask one function, and neither
    names a ledger pattern.

    THIS STAGE CHANGES NO POSTING: nothing writes the pointer yet, so every asset is NULL and goes where it always went. What is held
    here is the shape the writers are built on.

WHAT IS HELD
    * (the function) NULL, an absent key and an empty string all mean the shared ledger; a pointer means that ledger and no other;
    * (the rule) both journals call `_accumulated_account_id` and name no ledger pattern of their own, and no production module outside
      `domain/fixed_assets/asset_ledger.py` writes either accumulated-ledger pattern as a literal;
    * (the behaviour) through the real journals on a fake database holding the standard chart: depreciation credits, and a disposal
      debits, the pointed ledger when there is one and the shared ledger when there is not;
    * (the refusal) a pointed ledger that is missing, inactive, another practice's or not an asset ledger is refused in a sentence by
      both routes, nothing is posted, the disposal's claim is undone, and the shared ledger is NEVER the fallback.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import HTTPException

import routers.fixed_assets as fa
from domain.fixed_assets.asset_ledger import (
    SHARED_ACCUMULATED_PATTERN, AccumulatedLedgerUnavailable, accumulated_account_pointer)
from models.accounting import DepreciationIn, FixedAssetIn
from services.coa_seed_service import STANDARD_COA
from services.phase2_journal_service import Phase2JournalService, phase2_journal_service as svc
from tests.e2e_harness import FakeDB, wire_e2e

API = pathlib.Path(__file__).resolve().parent.parent
FIRM, CLIENT, OTHER_FIRM = "FIRM-ACC", "CLI-ACC", "FIRM-OTHER"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}

SHARED = "acct-1590"        # Accumulated Depreciation on the standard chart
OWN = "acct-1591"           # Accumulated Amortisation on the standard chart (migration 553)


# ── the function ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("asset,expected", [
    ({}, None), ({"accumulated_account_id": None}, None), ({"accumulated_account_id": ""}, None),
    ({"accumulated_account_id": "acct-1591"}, "acct-1591"), ({"accumulated_account_id": 7}, "7"),
    (None, None),
])
def test_null_absent_and_empty_all_mean_the_shared_ledger_and_a_pointer_means_that_ledger(asset, expected):
    assert accumulated_account_pointer(asset) == expected


# ── the rule ────────────────────────────────────────────────────────────────

def _calls(fn: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            names.add(n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
    return names


def _string_constants(fn: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_both_journals_ask_the_one_function_and_name_no_accumulated_ledger_pattern():
    import inspect
    import textwrap
    for fn in (Phase2JournalService.journal_for_depreciation, Phase2JournalService.journal_for_asset_disposal):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        assert "_accumulated_account_id" in _calls(tree), fn.__name__
        named = [c for c in _string_constants(tree) if "accumulated" in c.lower() and c.startswith("%")]
        assert not named, (fn.__name__, named)


def test_no_production_module_but_the_ledger_table_writes_an_accumulated_ledger_pattern():
    offenders, seen = [], 0
    for sub in ("services", "routers", "domain", "models", "repositories", "jobs", "core"):
        for path in sorted((API / sub).rglob("*.py")):
            rel = path.relative_to(API).as_posix()
            seen += 1
            if rel == "domain/fixed_assets/asset_ledger.py":
                continue
            for c in _string_constants(ast.parse(path.read_text())):
                if c.startswith("%") and c.endswith("%") and "accumulated" in c.lower():
                    offenders.append(f"{rel}: {c}")
    assert seen > 300, "the scan is not reading the tree"
    assert not offenders, f"an accumulated-ledger pattern is written outside the one module that owns it: {offenders}"


def test_the_shared_pattern_is_the_one_every_asset_has_always_used():
    assert SHARED_ACCUMULATED_PATTERN == "%Accumulated Depreciation%"


def test_the_detector_sees_a_journal_that_names_the_pattern_itself():
    old = ast.parse('def f(self, db):\n    return self._find_account(db, 1, 2, "%Accumulated Depreciation%")\n')
    assert [c for c in _string_constants(old) if "accumulated" in c.lower() and c.startswith("%")]
    new = ast.parse("def f(self, db, a):\n    return self._accumulated_account_id(db, a, 1, 2)\n")
    assert "_accumulated_account_id" in _calls(new) and not _string_constants(new)


# ── the behaviour ───────────────────────────────────────────────────────────

def _firm(monkeypatch) -> FakeDB:
    db = FakeDB()
    wire_e2e(monkeypatch, db, [fa])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("firms", {"id": FIRM, "name": "Acc & Co", "locked_financial_years": []})
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    for code, name, account_type, subtype in STANDARD_COA:
        db.seed("chart_of_accounts", {
            "id": f"acct-{code}", "firm_id": FIRM, "client_id": None,
            "account_code": code, "account_name": name, "account_type": account_type,
            "account_subtype": subtype, "is_active": True, "system_account_key": None})
    return db


def _credit_accounts(db: FakeDB, journal_id: str) -> list[str]:
    return [l["account_id"] for l in db.rows("journal_lines") if l["journal_entry_id"] == journal_id and l.get("credit_paise", 0) > 0]


def _debit_accounts(db: FakeDB, journal_id: str) -> list[str]:
    return [l["account_id"] for l in db.rows("journal_lines") if l["journal_entry_id"] == journal_id and l.get("debit_paise", 0) > 0]


def _asset(**extra) -> dict:
    base = {"id": "asset-0001-xxxxxxxx", "asset_name": "Licence", "asset_code": "FA-0001", "asset_category": "Intangibles",
            "depreciation_method": "SL", "purchase_cost_paise": 1_00_000_00, "purchase_date": "2025-04-05",
            "accumulated_depreciation_paise": 20_000_00, "disposal_date": "2025-09-30"}
    base.update(extra)
    return base


@pytest.mark.parametrize("extra,ledger", [({}, SHARED), ({"accumulated_account_id": None}, SHARED), ({"accumulated_account_id": OWN}, OWN)])
def test_depreciation_credits_and_a_disposal_debits_the_ledger_the_asset_names(monkeypatch, extra, ledger):
    db = _firm(monkeypatch)
    asset = _asset(**extra)
    dep = svc.journal_for_depreciation(asset, 1_66_66, "2025-06", FIRM, CLIENT)
    assert dep and _credit_accounts(db, dep) == [ledger]
    disp = svc.journal_for_asset_disposal(asset, 80_000_00, FIRM, CLIENT)
    assert disp and ledger in _debit_accounts(db, disp)
    other = OWN if ledger == SHARED else SHARED
    assert other not in _debit_accounts(db, disp) and other not in _credit_accounts(db, dep)


def _break_the_pointed_ledger(db: FakeDB, how: str) -> str:
    row = next(r for r in db.rows("chart_of_accounts") if r["id"] == OWN)
    if how == "inactive":
        row["is_active"] = False
    elif how == "another practice's":
        row["firm_id"] = OTHER_FIRM
    elif how == "not an asset ledger":
        row["account_type"] = "Expense"
    elif how == "another client's":
        row["client_id"] = "CLI-SOMEONE-ELSE"
    elif how == "missing":
        return "acct-gone"
    return OWN


@pytest.mark.parametrize("how", ["inactive", "another practice's", "not an asset ledger", "another client's", "missing"])
def test_a_pointed_ledger_that_cannot_be_used_is_refused_in_words_and_never_replaced_by_the_shared_one(monkeypatch, how):
    db = _firm(monkeypatch)
    pointer = _break_the_pointed_ledger(db, how)
    asset = _asset(accumulated_account_id=pointer)
    before = len(db.rows("journal_entries"))
    with pytest.raises(AccumulatedLedgerUnavailable) as dep:
        svc.journal_for_depreciation(asset, 1_66_66, "2025-06", FIRM, CLIENT)
    assert "is NOT moved to the shared Accumulated Depreciation ledger" in str(dep.value) and "Licence" in str(dep.value)
    with pytest.raises(AccumulatedLedgerUnavailable):
        svc.journal_for_asset_disposal(asset, 80_000_00, FIRM, CLIENT)
    assert len(db.rows("journal_entries")) == before, "nothing may be posted to either ledger"
    assert isinstance(dep.value, ValueError), "the journals' own 're-raise account problems' branch must let it through"


def _created_asset(db: FakeDB) -> dict:
    res = fa.create_asset(FixedAssetIn(
        client_id=CLIENT, asset_name="Licence", asset_category="Intangibles", purchase_date="2025-04-05",
        purchase_cost_paise=1_20_000_00, depreciation_method="SL", useful_life_years=5, acquisition_mode="paid"), CALLER)
    assert res["success"] is True, res
    return db.rows("fixed_assets")[0]


def test_the_depreciation_route_answers_422_with_the_sentence_when_the_pointed_ledger_cannot_be_used(monkeypatch):
    db = _firm(monkeypatch)
    row = _created_asset(db)
    row["accumulated_account_id"] = OWN
    next(r for r in db.rows("chart_of_accounts") if r["id"] == OWN)["is_active"] = False
    entries_before = len(db.rows("journal_entries"))
    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation(row["id"], DepreciationIn(period="2025-04"), CALLER)
    assert exc.value.status_code == 422 and "cannot be used" in exc.value.detail
    assert len(db.rows("journal_entries")) == entries_before
    assert row["accumulated_depreciation_paise"] == 0, "the register must not move without a journal"


def test_the_disposal_route_answers_422_undoes_its_claim_and_leaves_the_asset_live(monkeypatch):
    db = _firm(monkeypatch)
    row = _created_asset(db)
    row["accumulated_account_id"] = OWN
    # A disposal needs every month before it posted (the route refuses otherwise); say they are, so the ledger is what is tested.
    row["depreciation_posted_through"] = "2025-09-30"
    next(r for r in db.rows("chart_of_accounts") if r["id"] == OWN)["is_active"] = False
    from models.accounting import DisposalIn
    entries_before = len(db.rows("journal_entries"))
    with pytest.raises(HTTPException) as exc:
        fa.dispose_asset(row["id"], DisposalIn(disposal_date="2025-09-30", sale_proceeds_paise=50_000_00, disposal_type="Sale"), CALLER)
    assert exc.value.status_code == 422 and "cannot be used" in exc.value.detail
    assert len(db.rows("journal_entries")) == entries_before
    assert row["is_disposed"] is False, "the claim must be undone so a retry can start over"
