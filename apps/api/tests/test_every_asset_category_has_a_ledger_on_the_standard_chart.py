"""An asset of any category can be booked on the chart a firm is onboarded with.

THE DEFECT (PRE-A-004, found by driving the demo seeder over a real database)

    `POST /api/fixed-assets` with category "Office Equipment" answered 500 for
    every firm onboarded through the product. The posting engine's category map
    asked for a ledger matching `%Office Equipment%`; `STANDARD_COA` - the chart
    `seed_firm_coa` gives a new firm - had no such ledger; `_find_account` raised
    "Required account not found"; and the router does not convert that, so the
    asset row was written and the request failed. The map existed three times in
    `phase2_journal_service` (acquisition, CWIP capitalisation, disposal) and the
    chart existed once, and nothing compared the two.

THE RULE

    Every asset category Schedule II knows (`schedule_ii.PART_C`) is an explicit
    key of `domain/fixed_assets/asset_ledger`, the pattern it names matches
    EXACTLY ONE ledger on `STANDARD_COA`, that ledger is an asset ledger, and a
    firm holding nothing but the standard chart can post an acquisition, a
    capitalisation and a disposal in every one of the categories. Written over
    the two tables, not over today's nine names: a tenth category added to
    `PART_C` fails here until the table and the chart both have it.

    The test that was already here for this (`test_fixed_asset_gl_mapping`) seeds
    its OWN chart containing an Office Equipment account, which is why it passed
    while the chart a firm actually gets did not have one.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

import routers.fixed_assets as fa
from domain.fixed_assets import asset_ledger, schedule_ii
from domain.reporting import schedule_iii
from models.accounting import FixedAssetIn
from services.coa_seed_service import STANDARD_COA
from tests.e2e_harness import FakeDB, wire_e2e

API = pathlib.Path(__file__).resolve().parent.parent

FIRM, CLIENT = "FIRM-OE", "CLI-OE"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth", "email": "ca@f.test",
          "role": "Partner"}

CATEGORIES = sorted(schedule_ii.PART_C)

#: Asset ledgers an asset's COST is debited to. Not the contra account, not CWIP.
ASSET_SUBTYPES = {"Fixed Asset", "Intangible Asset"}


def _ilike(pattern: str, value: str) -> bool:
    """`ILIKE` as `_find_account` asks it: '%' is the only wildcard."""
    rx = ".*".join(re.escape(part) for part in pattern.split("%"))
    return re.fullmatch(rx, value, re.IGNORECASE) is not None


def _ledgers_for(category: str) -> list[tuple[str, str, str, str]]:
    return [row for row in STANDARD_COA
            if _ilike(asset_ledger.ledger_pattern(category), row[1])]


# ── the table and the taxonomy agree ────────────────────────────────────────

def test_every_category_schedule_ii_knows_is_named_in_the_ledger_table():
    missing = sorted(set(schedule_ii.PART_C) - set(asset_ledger.LEDGER_PATTERN_BY_CATEGORY))
    stale = sorted(set(asset_ledger.LEDGER_PATTERN_BY_CATEGORY) - set(schedule_ii.PART_C))
    assert not missing, (
        f"{missing} are asset categories with no entry in domain/fixed_assets/"
        "asset_ledger.py: they would fall through to the Plant & Machinery default "
        "and the CA would never be told")
    assert not stale, f"{stale} are in the ledger table but are not asset categories"


def test_an_unknown_category_is_booked_to_the_default_ledger_and_says_so_in_one_place():
    for odd in (None, "", "Aircraft", 7):
        assert asset_ledger.ledger_pattern(odd) == asset_ledger.DEFAULT_LEDGER_PATTERN
    assert asset_ledger.DEFAULT_LEDGER_PATTERN == "%Plant & Machinery%"


@pytest.mark.parametrize("category", CATEGORIES)
def test_each_categorys_pattern_finds_exactly_one_asset_ledger_on_the_standard_chart(category):
    """Zero is the 500. Two is worse: `_find_account` takes `limit(1)` with no
    ORDER BY, so a pattern matching two ledgers books to whichever came first."""
    hits = _ledgers_for(category)
    assert len(hits) == 1, (
        f"{category!r} asks for {asset_ledger.ledger_pattern(category)!r}, which "
        f"matches {[h[1] for h in hits]} on STANDARD_COA")
    _code, name, account_type, subtype = hits[0]
    assert account_type == "Asset", name
    assert subtype in ASSET_SUBTYPES, f"{name!r} is subtype {subtype!r}, not an asset ledger"


def test_office_equipment_is_a_tangible_fixed_asset_ledger_like_its_neighbours():
    rows = {name: (code, atype, subtype) for code, name, atype, subtype in STANDARD_COA}
    assert rows["Office Equipment"] == ("1508", "Asset", "Fixed Asset")
    # Presented where Plant & Machinery is: the subtype is what Schedule III reads.
    assert (schedule_iii.classify("Asset", rows["Office Equipment"][2])
            == schedule_iii.classify("Asset", rows["Plant & Machinery"][2])
            == ("Tangible Fixed Assets", "subtype"))


def test_no_other_pattern_the_posting_engine_asks_for_finds_the_new_ledger():
    """The cess ledgers' names avoid "GST Input" for the same reason: every
    lookup is an unordered `limit(1)` ILIKE, so a name another pattern also
    matches is a ledger some other posting can be sent to."""
    src = (API / "services" / "phase2_journal_service.py").read_text()
    patterns = {n.value for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value.startswith("%") and n.value.endswith("%") and len(n.value) > 2}
    own = {asset_ledger.ledger_pattern(c) for c in CATEGORIES}   # the table owns these
    offenders = sorted(p for p in patterns - own if _ilike(p, "Office Equipment"))
    assert not offenders, (
        f"{offenders} also match the Office Equipment ledger: an asset or the "
        "other posting could land on the wrong account")
    assert len(patterns) > 20, "the scan found almost no patterns: it is not reading the module"


# ── nothing but the table decides ───────────────────────────────────────────

def _is_category_to_ledger_dict(node: ast.AST) -> bool:
    if not isinstance(node, ast.Dict) or len(node.keys) < 3:
        return False
    keys = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    vals = [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return (len(keys) == len(node.keys) and len(vals) == len(node.values)
            and sum(k in schedule_ii.PART_C for k in keys) >= 3
            and all(v.startswith("%") and v.endswith("%") for v in vals))


def test_only_the_ledger_table_maps_a_category_to_a_ledger():
    """The map was written three times in one service. A dict from asset
    categories to ILIKE patterns is a decision about which account a cost is
    debited to, and a second one is a place a category gets added and forgotten."""
    offenders = []
    for sub in ("services", "routers", "domain", "models", "repositories", "jobs"):
        for path in sorted((API / sub).rglob("*.py")):
            rel = path.relative_to(API).as_posix()
            if rel == "domain/fixed_assets/asset_ledger.py" or "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text())
            offenders += [f"{rel}:{n.lineno}" for n in ast.walk(tree) if _is_category_to_ledger_dict(n)]
    assert not offenders, (
        "a category-to-ledger map outside domain/fixed_assets/asset_ledger.py: "
        f"{offenders}")


def test_the_scan_recognises_the_dict_it_forbids():
    """Negative control for the guard above: it must see the old copy."""
    old = ast.parse('''
cat_map = {
    "Plant & Machinery":        "%Plant & Machinery%",
    "Office Equipment":         "%Office Equipment%",
    "Vehicles":                 "%Vehicles%",
}
''')
    assert any(_is_category_to_ledger_dict(n) for n in ast.walk(old))
    unrelated = ast.parse('names = {"a": "%x%", "b": "%y%", "c": "%z%"}')
    assert not any(_is_category_to_ledger_dict(n) for n in ast.walk(unrelated))


def test_the_posting_engine_asks_the_table_in_all_three_places():
    """Each journal that books an asset to its category's ledger asks the one
    table. Judged per function, by AST, so renaming the local variable or adding
    a fourth journal that also asks cannot fail it; a journal that stops asking
    (and would then carry a map of its own) does."""
    tree = ast.parse((API / "services" / "phase2_journal_service.py").read_text())
    asking = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        and any(
            isinstance(c, ast.Call)
            and getattr(c.func, "id", getattr(c.func, "attr", "")) == "ledger_pattern"
            for c in ast.walk(fn)
        )
    }
    assert {
        "journal_for_asset_acquisition",
        "journal_for_cwip_capitalisation",
        "journal_for_asset_disposal",
    } <= asking


# ── the behaviour: a firm holding only the standard chart can post ──────────

def _firm_with_only_the_standard_chart(monkeypatch) -> FakeDB:
    db = FakeDB()
    wire_e2e(monkeypatch, db, [fa])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("firms", {"id": FIRM, "name": "Onboarded & Co", "locked_financial_years": []})
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    for code, name, account_type, subtype in STANDARD_COA:
        db.seed("chart_of_accounts", {
            "id": f"acct-{code}", "firm_id": FIRM, "client_id": None,
            "account_code": code, "account_name": name, "account_type": account_type,
            "account_subtype": subtype, "is_active": True, "system_account_key": None})
    return db


def _debit_account_ids(db: FakeDB, journal_id: str) -> list[str]:
    return [l["account_id"] for l in db.rows("journal_lines")
            if l["journal_entry_id"] == journal_id and l.get("debit_paise", 0) > 0]


def _credit_account_ids(db: FakeDB, journal_id: str) -> list[str]:
    return [l["account_id"] for l in db.rows("journal_lines")
            if l["journal_entry_id"] == journal_id and l.get("credit_paise", 0) > 0]


@pytest.mark.parametrize("category", CATEGORIES)
def test_creating_an_asset_of_any_category_posts_to_its_own_ledger(monkeypatch, category):
    """THE REGRESSION. The route, not just the journal function: before the
    chart had the ledger this raised `ValueError: Required account not found:
    %Office Equipment%` out of `create_asset`, which is a 500."""
    db = _firm_with_only_the_standard_chart(monkeypatch)
    expected = f"acct-{_ledgers_for(category)[0][0]}"

    res = fa.create_asset(FixedAssetIn(
        client_id=CLIENT, asset_name=f"Test {category}", asset_category=category,
        purchase_date="2025-04-05", purchase_cost_paise=1_00_000_00,
        depreciation_method="SL", useful_life_years=10, acquisition_mode="paid"), CALLER)

    assert res["success"] is True, res
    journal_id = res["data"]["journal_entry_id"]
    assert journal_id, "the acquisition posted no journal"
    assert _debit_account_ids(db, journal_id) == [expected]
    # …and the asset row and its journal agree: nothing is left half done.
    assert [r["journal_entry_id"] for r in db.rows("fixed_assets")] == [journal_id]


@pytest.mark.parametrize("category", CATEGORIES)
def test_a_capitalised_project_and_a_disposal_use_the_same_ledger(monkeypatch, category):
    """The other two copies of the map. The cost leaves the ledger it entered."""
    from services.phase2_journal_service import phase2_journal_service as svc

    db = _firm_with_only_the_standard_chart(monkeypatch)
    expected = f"acct-{_ledgers_for(category)[0][0]}"
    asset = {"id": "asset-0001-xxxxxxxx", "asset_name": "Item", "asset_code": "FA-0001",
             "asset_category": category, "purchase_cost_paise": 1_00_000_00,
             "purchase_date": "2025-04-05", "accumulated_depreciation_paise": 0,
             "disposal_date": "2025-09-30"}

    cap = svc.journal_for_cwip_capitalisation(
        {"id": "proj-0001-xxxxxxxx", "project_name": "Build"}, asset, 1_00_000_00,
        "2025-04-05", FIRM, CLIENT)
    assert cap and _debit_account_ids(db, cap) == [expected]

    disp = svc.journal_for_asset_disposal(asset, 80_000_00, FIRM, CLIENT)
    assert disp and expected in _credit_account_ids(db, disp)
