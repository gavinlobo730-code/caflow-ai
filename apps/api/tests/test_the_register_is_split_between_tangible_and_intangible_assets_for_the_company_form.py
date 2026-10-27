"""POST-A-344 — ITR-6 takes the gross block and the depreciation of tangible assets and of intangible assets apart, and the fixed-asset register
is split between them only where it ties to the ledger.

WHAT WAS LEFT OPEN

    POST-A-070 filled the net block of each kind from the ledger's two Schedule III lines and left the gross block and the depreciation to date
    to the CA, because the register's movement is by asset CATEGORY and nothing said which categories are intangible. ITR-3 and ITR-5 take the
    two kinds together and were filled from the register's totals.

WHAT THIS FILE HOLDS

    * THE SPLIT IS BY THE LEDGER LINE, not by a list of category names: each category is booked to one ledger (`asset_ledger`) and the line that
      ledger is on is the line the year-end statements already use (`year_end_lines.schedule_line_for_account`, the CA's own mapping included).
    * IT IS USED ONLY WHERE THE REGISTER'S NET BLOCK OF EACH LINE EQUALS THE LEDGER'S LINE TO THE PAISA. The standard chart books the depreciation
      of every category in ONE Accumulated Depreciation account, so the ledger's tangible line carries the amortisation of intangible assets and
      the two lines cannot match the register's category by category once any intangible asset has been amortised. That is the common case with
      intangibles, and it is withheld with the difference in words and the figures left to the CA, never absorbed into either line.
    * A CATEGORY WITH A FIGURE AND NO READABLE LINE WITHHOLDS THE SPLIT and is named; a category held at nil asks nothing.
    * ITR-3 AND ITR-5 ARE UNCHANGED, and read no chart account (the service reads one only for the form that needs it).
    * EVERY BOX NAMED IS IN THE DEPARTMENT'S SCHEMA (the books-schedules file holds that for every slot and part; the new ones are in it).
"""
from __future__ import annotations

import re
from typing import Optional

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from domain.income_tax import books_schedules as B
from domain.reporting import year_end_lines as lines
from services import itr_books_schedules_service as svc
from tests._books_statements import L, balanced_statements

FIRM, CLIENT = "firm-1", "client-1"
TANGIBLE, INTANGIBLE = "tangible_assets", "intangible_assets"


def _cls(name: str, gross: int, accum: int) -> dict:
    return {"asset_class": name, "closing_gross_paise": gross, "closing_accum_paise": accum, "closing_net_paise": gross - accum}


def _register(classes: list[dict], ledger_lines: dict, **kw) -> dict:
    gross = sum(c["closing_gross_paise"] for c in classes)
    accum = sum(c["closing_accum_paise"] for c in classes)
    base = {"gross": gross, "accumulated": accum, "net": gross - accum, "split_known": True,
            "classes": classes, "ledger_lines": ledger_lines}
    base.update(kw)
    return base


def _assemble(register, statements=None, form: str = "ITR-6") -> dict:
    return B.assemble(form=form, assessment_year="2026-27", financial_year="2025-26",
                      statements=statements or balanced_statements(), register=register)


def _slot(out: dict, key: str) -> dict:
    return next(s for s in out["balance_sheet"]["asset_slots"] if s["key"] == key)


def _parts(out: dict, key: str) -> dict:
    return {p["label"]: p for p in _slot(out, key)["parts"]}


def _check(out: dict, name: str) -> Optional[dict]:
    return next((c for c in out["tie_out"]["checks"] if c["name"] == name), None)


# Hand-computed books, for a chart that carries the amortisation of intangible assets on the intangible line (a chart a firm built for
# itself; the shipped one keeps all depreciation in one account, which is the next block's case). Tangible: plant 10 lakh gross with 2.5 lakh depreciation, computers 2 lakh with 0.5 lakh, so 12 lakh gross, 3 lakh
# depreciation, 9 lakh net, which is the ledger's tangible line. Intangible: 80,000 gross with 30,000 amortised, 50,000 net, which is the
# ledger's intangible line (a chart that carries the amortisation of intangible assets on the intangible line).
PLANT = _cls("Plant & Machinery", 10 * L, 2_50_000_00)
COMPUTERS = _cls("Computer & IT Equipment", 2 * L, 50_000_00)
SOFTWARE = _cls("Intangibles", 80_000_00, 30_000_00)
BOOKED = {"Plant & Machinery": TANGIBLE, "Computer & IT Equipment": TANGIBLE, "Intangibles": INTANGIBLE}


# ── the split, when each line ties ───────────────────────────────────────────────────────────────────────────────────────────────
def test_the_register_fills_the_gross_block_and_the_depreciation_of_each_kind_when_each_line_ties():
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], BOOKED))
    t, i = _parts(out, "tangible_assets"), _parts(out, "intangible_assets")
    assert t["Gross block"]["amount_paise"] == 12 * L and t["Gross block"]["state"] == "placed"
    assert t["Depreciation"]["amount_paise"] == 3 * L and t["Depreciation"]["state"] == "placed"
    assert i["Gross block"]["amount_paise"] == 80_000_00 and i["Gross block"]["state"] == "placed"
    assert i["Amortisation"]["amount_paise"] == 30_000_00 and i["Amortisation"]["state"] == "placed"
    # The net block of each is still the ledger's and is not recomputed from the register.
    assert _slot(out, "tangible_assets")["amount_paise"] == 9 * L
    assert _slot(out, "intangible_assets")["amount_paise"] == 50_000_00
    # Gross less depreciation is the net block, to the paisa, on each kind.
    assert t["Gross block"]["amount_paise"] - t["Depreciation"]["amount_paise"] == _slot(out, "tangible_assets")["amount_paise"]
    assert i["Gross block"]["amount_paise"] - i["Amortisation"]["amount_paise"] == _slot(out, "intangible_assets")["amount_paise"]


def test_each_part_is_keyed_in_the_departments_own_box():
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], BOOKED))
    paths = {p["label"]: p["json_path"] for key in ("tangible_assets", "intangible_assets") for p in _slot(out, key)["parts"]}
    tangible = {p["json_path"] for p in _slot(out, "tangible_assets")["parts"]}
    intangible = {p["json_path"] for p in _slot(out, "intangible_assets")["parts"]}
    assert any(p.endswith("FixedAsset.Tangible.GrossBlock") for p in tangible)
    assert any(p.endswith("FixedAsset.Tangible.Depreciation") for p in tangible)
    assert any(p.endswith("FixedAsset.InTangible.GrossBlock") for p in intangible)
    assert any(p.endswith("FixedAsset.InTangible.Amortization") for p in intangible)
    assert paths  # both kinds served parts


def test_the_per_line_tie_is_reported_in_the_tie_out_without_ever_failing_it():
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], BOOKED))
    for name, expected in (("register_tangible_net_block_vs_ledger", 9 * L), ("register_intangible_net_block_vs_ledger", 50_000_00)):
        row = _check(out, name)
        assert row["informational"] is True and row["expected_paise"] == expected and row["difference_paise"] == 0, row
    assert out["tie_out"]["ok"] is True and out["tie_out"]["difference_paise"] == 0


def test_a_company_with_no_intangible_asset_gets_its_whole_register_on_the_tangible_boxes():
    statements = balanced_statements(assets={"tangible_assets": 9 * L + 50_000_00, "intangible_assets": 0})
    register = _register([PLANT, COMPUTERS, _cls("Land", 50_000_00, 0)], {**BOOKED, "Land": TANGIBLE})
    out = _assemble(register, statements)
    t, i = _parts(out, "tangible_assets"), _parts(out, "intangible_assets")
    assert t["Gross block"]["amount_paise"] == 12 * L + 50_000_00 and t["Depreciation"]["amount_paise"] == 3 * L
    assert i["Gross block"]["amount_paise"] == 0 and i["Amortisation"]["amount_paise"] == 0
    assert i["Gross block"]["state"] == "placed", "a nil that the books settle is a figure, not an unknown"


def test_unamortised_intangibles_tie_and_are_filled():
    out = _assemble(_register([PLANT, COMPUTERS, _cls("Intangibles", 50_000_00, 0)], BOOKED))
    i = _parts(out, "intangible_assets")
    assert i["Gross block"]["amount_paise"] == 50_000_00 and i["Amortisation"]["amount_paise"] == 0
    assert not any("could not be split" in g or "was not split" in g for g in out["gaps"])


# ── the split, withheld ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_opposite_difference_is_not_called_an_amortised_intangible():
    """The sentence naming an amortised intangible asset is true only of its own shape: the ledger's tangible line LOWER than the
    register's by exactly what its intangible line is higher. (When the totals tie the two differences are always equal and opposite, so
    the sign is what tells the shapes apart.) The other way round, an intangible line below the register's, is something else."""
    statements = balanced_statements(assets={"tangible_assets": 9 * L + 30_000_00, "intangible_assets": 20_000_00})
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], BOOKED), statements)
    sentence = next(g for g in out["gaps"] if "differs from the ledger's" in g)
    assert "the register's tangible assets are ₹30,000.00 lower and its intangible assets ₹30,000.00 higher" in sentence, sentence
    assert "paise" not in sentence, "a figure written for a CA is rupees in the Indian grouping, never a count of paise"
    assert "amortised intangible" not in sentence and "need reconciling" in sentence and "left for the CA to key" in sentence
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] is None


def test_an_amortised_intangible_on_the_standard_chart_withholds_the_split_and_says_why():
    """The standard chart books every category's depreciation in one account, so the ledger's tangible line is lower by what the
    intangible assets were amortised and its intangible line is the cost: 8.7 lakh and 80,000 against the register's 9 lakh and 50,000."""
    statements = balanced_statements(assets={"tangible_assets": 9 * L - 30_000_00, "intangible_assets": 80_000_00})
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], BOOKED), statements)
    for key, label in (("tangible_assets", "Gross block"), ("tangible_assets", "Depreciation"),
                       ("intangible_assets", "Gross block"), ("intangible_assets", "Amortisation")):
        part = _parts(out, key)[label]
        assert part["amount_paise"] is None and part["state"] == "not_recorded", (key, label)
    sentence = next(g for g in out["gaps"] if "differs from the ledger's" in g)
    assert "the register's tangible assets are ₹30,000.00 higher and its intangible assets ₹30,000.00 lower" in sentence, sentence
    assert "paise" not in sentence
    assert "Accumulated Depreciation account" in sentence and "left for the CA to key" in sentence
    # The ledger's net block of each is still given, and the books still tie: the difference is reported, never absorbed.
    assert _slot(out, "tangible_assets")["amount_paise"] == 9 * L - 30_000_00
    assert _slot(out, "intangible_assets")["amount_paise"] == 80_000_00
    assert out["tie_out"]["ok"] is True and out["tie_out"]["difference_paise"] == 0
    assert _check(out, "register_tangible_net_block_vs_ledger")["difference_paise"] == 30_000_00
    assert _check(out, "register_intangible_net_block_vs_ledger")["difference_paise"] == -30_000_00


def test_a_category_with_a_figure_and_no_ledger_account_withholds_the_split_and_is_named():
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], {**BOOKED, "Intangibles": None}))
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] is None
    sentence = next(g for g in out["gaps"] if "could not be split" in g)
    assert "no ledger account could be found for the category 'Intangibles'" in sentence and "left for the CA to key" in sentence
    assert _check(out, "register_tangible_net_block_vs_ledger") is None


def test_a_category_booked_to_a_line_that_is_neither_kind_withholds_the_split_and_names_the_line():
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], {**BOOKED, "Intangibles": "inventories"}))
    assert _parts(out, "intangible_assets")["Gross block"]["amount_paise"] is None
    sentence = next(g for g in out["gaps"] if "could not be split" in g)
    assert "the category 'Intangibles' is booked to a ledger that Schedule III places under Inventories" in sentence, sentence


def test_a_category_held_at_nil_asks_no_line_and_withholds_nothing():
    sold = _cls("Vehicles", 0, 0)
    assert B.register_categories_to_place([PLANT, sold, SOFTWARE]) == ["Plant & Machinery", "Intangibles"]
    out = _assemble(_register([PLANT, COMPUTERS, sold, SOFTWARE], BOOKED))      # no line given for Vehicles at all
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] == 12 * L


def test_a_category_nil_on_cost_but_with_depreciation_is_not_nil():
    odd = _cls("Vehicles", 0, 1_000_00)
    assert B.register_categories_to_place([odd]) == ["Vehicles"]
    # A register whose net block is 1,000 lower, against a ledger that agrees (so it is the category and not the total that withholds).
    statements = balanced_statements(assets={"tangible_assets": 9 * L - 1_000_00}, liabilities={"share_capital": 10 * L - 1_000_00})
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE, odd], BOOKED), statements)
    assert any("no ledger account could be found for the category 'Vehicles'" in g for g in out["gaps"]), out["gaps"]


@pytest.mark.parametrize("field", ["gross", "accumulated"])
def test_categories_that_do_not_add_to_the_registers_totals_are_not_placed(field):
    """A split handed categories that leave something out of the total is not the register's figure, whichever total it misses."""
    reg = _register([PLANT, COMPUTERS, SOFTWARE], BOOKED)
    reg[field] += 1_00                      # the total says one rupee more than its categories hold (net is left to tie)
    reg["net"] = 9 * L + 50_000_00
    out = _assemble(reg)
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] is None
    assert any("categories do not add to its totals" in g and "left for the CA to key" in g for g in out["gaps"]), out["gaps"]


def test_a_register_that_was_not_handed_its_categories_says_it_was_not_split():
    legacy = {"gross": 12_80_000_00, "accumulated": 3_30_000_00, "net": 9_50_000_00, "split_known": True}
    out = _assemble(legacy)
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] is None
    sentence = next(g for g in out["gaps"] if "was not split between tangible and intangible" in g)
    assert "tangible and intangible" in sentence and "left for the CA to key" in sentence


def test_a_register_that_does_not_tie_in_total_gives_one_reason_and_not_two():
    reg = _register([PLANT, COMPUTERS, SOFTWARE], BOOKED, net=9 * L)             # the register's total net differs from the ledger's
    out = _assemble(reg)
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] is None
    reasons = [g for g in out["gaps"] if "the gross block and the depreciation" in g]
    assert len(reasons) == 1 and "differs from the ledger's tangible and intangible assets" in reasons[0], reasons
    assert "paise" not in reasons[0] and ("higher" in reasons[0] or "lower" in reasons[0]) and "₹" in reasons[0], reasons[0]
    assert _check(out, "register_tangible_net_block_vs_ledger") is None


def test_no_register_read_is_said_once_for_the_company_form_too():
    out = _assemble(None)
    reasons = [g for g in out["gaps"] if "the gross block and the depreciation" in g]
    assert len(reasons) == 1 and "register was not read" in reasons[0], reasons
    assert _parts(out, "intangible_assets")["Amortisation"]["state"] == "not_recorded"


@pytest.mark.parametrize("form", ["ITR-3", "ITR-5", "ITR-6"])
def test_a_placed_gross_block_says_the_ledger_ties_only_its_net_block(form):
    """A register that agrees with the ledger on the net block can disagree on the cost and the depreciation (an asset entered at its
    written-down value), and nothing the module holds can tell: it says so beside the figures it placed, and only then."""
    placed = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], BOOKED), form=form)
    said = [g for g in placed["gaps"] if "What ties them to the ledger is the net block only" in g]
    assert len(said) == 1 and "check them against the fixed assets note" in said[0], said
    for withheld in (None, _register([PLANT, COMPUTERS, SOFTWARE], BOOKED, net=9 * L)):
        assert not any("What ties them to the ledger" in g for g in _assemble(withheld, form=form)["gaps"])


def test_a_split_that_is_withheld_does_not_say_the_figures_were_placed():
    statements = balanced_statements(assets={"tangible_assets": 9 * L - 30_000_00, "intangible_assets": 80_000_00})
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], BOOKED), statements)
    assert not any("What ties them to the ledger" in g for g in out["gaps"])


def test_the_company_form_always_says_impairment_is_left_for_the_ca():
    for reg in (None, _register([PLANT, COMPUTERS, SOFTWARE], BOOKED)):
        gaps = [g for g in _assemble(reg)["gaps"] if "impairment losses" in g]
        assert len(gaps) == 1 and "does not record them" in gaps[0] and "left for the CA to key" in gaps[0], gaps


# ── the firm forms are untouched ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("form", ["ITR-3", "ITR-5"])
def test_the_firm_forms_keep_the_registers_totals_and_ask_nothing_per_line(form):
    out = _assemble(_register([PLANT, COMPUTERS, SOFTWARE], BOOKED), form=form)
    parts = {p["label"]: p for p in _slot(out, "fixed_assets")["parts"]}
    assert parts["Gross block"]["amount_paise"] == 12_80_000_00 and parts["Depreciation"]["amount_paise"] == 3_30_000_00
    assert _check(out, "register_tangible_net_block_vs_ledger") is None
    assert not any("impairment" in g for g in out["gaps"])


@pytest.mark.parametrize("form,expected", [("ITR-3", False), ("ITR-5", False), ("ITR-6", True)])
def test_only_the_company_form_splits_the_register(form, expected):
    assert B.splits_fixed_assets(form) is expected


# ── nothing is dropped or counted twice, on any set of categories that ties ────────────────────────────────────────────────────────
_category = st.tuples(st.sampled_from(["Plant & Machinery", "Furniture & Fixtures", "Computer & IT Equipment", "Vehicles", "Building",
                                       "Intangibles", "Other", "Land"]),
                      st.integers(0, 50 * L), st.integers(0, 50 * L), st.sampled_from([TANGIBLE, INTANGIBLE]))


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(rows=st.lists(_category, min_size=1, max_size=8, unique_by=lambda r: r[0]))
def test_the_per_line_figures_add_to_the_registers_totals_whatever_the_categories(rows):
    classes = [_cls(name, gross, min(accum, gross)) for name, gross, accum, _ in rows]
    line_of = {name: line for name, _, _, line in rows}
    net = {TANGIBLE: 0, INTANGIBLE: 0}
    for c in classes:
        net[line_of[c["asset_class"]]] += c["closing_net_paise"]
    statements = balanced_statements(assets={TANGIBLE: net[TANGIBLE], INTANGIBLE: net[INTANGIBLE], "capital_wip": 0,
                                             "long_term_investments": 0, "long_term_loans_and_advances": 0,
                                             "inventories": 0, "trade_receivables": 0, "cash_and_bank": 0,
                                             "short_term_loans_and_advances": 0, "other_current_assets": 0},
                                   liabilities={k: 0 for k in B.BS_LIABILITY_LINES} | {"share_capital": net[TANGIBLE] + net[INTANGIBLE]},
                                   income={"revenue_from_operations": 0, "other_income": 0},
                                   expenses={k: 0 for k in B.PL_EXPENSE_LINES}, current_tax=0, deferred_tax=0)
    flat, why, rows_out = B.register_by_line(_register(classes, line_of), statements)
    assert why is None and all(r["difference_paise"] == 0 for r in rows_out), (why, rows_out)
    assert flat["gross_tangible_assets"] + flat["gross_intangible_assets"] == sum(c["closing_gross_paise"] for c in classes)
    assert flat["accumulated_tangible_assets"] + flat["accumulated_intangible_assets"] == sum(c["closing_accum_paise"] for c in classes)
    for line in (TANGIBLE, INTANGIBLE):
        assert flat[f"gross_{line}"] - flat[f"accumulated_{line}"] == net[line]


# ── the service: the line is read from the account the journals debit ──────────────────────────────────────────────────────────
class _Result:
    def __init__(self, data):
        self.data = data


class _ChartQuery:
    """The two reads the split makes of the chart, evaluated: a lookup that forgets the firm finds another firm's account."""
    COLUMNS = {"id", "firm_id", "client_id", "account_name", "account_type", "account_subtype", "schedule_iii_mapping", "is_active"}

    def __init__(self, db, table):
        self.db, self.table, self.filters, self.cols, self.n = db, table, [], None, None
        self.conds: list = []

    def select(self, cols="*", **_k):
        if self.table == "chart_of_accounts":
            self.cols = [c.strip() for c in cols.split(",")]
            assert set(self.cols) <= self.COLUMNS, f"a column the chart does not have: {set(self.cols) - self.COLUMNS}"
        return self

    def eq(self, col, val):
        self.db.log.append((self.table, "eq", col, val))
        self.conds.append(("eq", col, val))
        self.filters.append(lambda r, c=col, v=val: r.get(c) == v)
        return self

    def is_(self, col, val):
        self.db.log.append((self.table, "is", col, val))
        return self

    def or_(self, expr):
        self.db.log.append((self.table, "or", expr))
        allowed = {part.split(".eq.")[1] if ".eq." in part else None for part in expr.split(",")}
        self.filters.append(lambda r: r.get("client_id") in allowed or r.get("client_id") is None)
        return self

    def ilike(self, col, pattern):
        self.db.log.append((self.table, "ilike", col, pattern))
        rx = re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("%")) + "$", re.I)
        self.filters.append(lambda r, c=col: bool(rx.match(str(r.get(c) or ""))))
        return self

    def limit(self, n):
        self.n = n
        return self

    def execute(self):
        self.db.queries.append((self.table, tuple(self.conds)))
        if self.db.hide_by_id and any(c[:2] == ("eq", "id") for c in self.conds):
            return _Result([])
        rows = [r for r in self.db.chart if all(f(r) for f in self.filters)]
        rows = rows[: self.n] if self.n is not None else rows
        return _Result([{c: r.get(c) for c in self.cols} for r in rows] if self.cols else rows)


class _ChartDb:
    def __init__(self, chart):
        self.chart, self.log, self.queries = chart, [], []
        self.hide_by_id = False            # the account the lookup found is gone when it is read (deleted between the two requests)

    def table(self, name):
        self.log.append(("table", name))
        return _ChartQuery(self, name)


def _account(account_id, name, subtype, mapping=None, firm=FIRM, client=None, active=True):
    return {"id": account_id, "firm_id": firm, "client_id": client, "account_name": name, "account_type": "Asset",
            "account_subtype": subtype, "schedule_iii_mapping": mapping, "is_active": active}


STANDARD_CHART = [
    _account("a-pm", "Plant & Machinery", "Fixed Asset"),
    _account("a-comp", "Computers & Software", "Fixed Asset"),
    _account("a-int", "Intangible Assets", "Intangible Asset"),
]


def _asset(category: str, cost: int, accumulated: int) -> dict:
    return {"asset_category": category, "purchase_cost_paise": cost, "accumulated_depreciation_paise": accumulated,
            "purchase_date": "2024-06-01", "is_disposed": False, "depreciation_fy": "2025-26",
            "depreciation_fy_start_accum_paise": 0, "firm_id": FIRM, "client_id": CLIENT}


def _filing(form: str = "ITR-6") -> dict:
    return {"id": "f-1", "firm_id": FIRM, "client_id": CLIENT, "itr_form": form, "financial_year": "2025-26",
            "assessment_year": "2026-27", "status": "draft", "return_type": "original"}


@pytest.fixture
def books(monkeypatch):
    holder = {"assets": [], "statements": balanced_statements()}
    monkeypatch.setattr(svc, "fetch_all", lambda make_query, **kw: (make_query(), list(holder["assets"]))[1])
    monkeypatch.setattr("services.year_end_financial_service.generate_financial_statements",
                        lambda *a, **k: holder["statements"])
    monkeypatch.setattr(svc.section_32_service, "assemble",
                        lambda *a, **k: {"blocks": [], "allowance_paise": 0, "short_term_capital_gain_paise": 0, "statutory_gaps": [],
                                         "unclassified_assets": [], "blocks_without_opening_wdv": []})
    return holder


def test_the_service_splits_the_register_by_the_line_of_the_account_each_category_is_booked_to(books):
    # Plant and computers on the tangible line (9 lakh net: 12 lakh gross less 3 lakh), an unamortised intangible of 50,000 on the other.
    books["assets"] = [_asset("Plant & Machinery", 10 * L, 2_50_000_00), _asset("Computer & IT Equipment", 2 * L, 50_000_00),
                       _asset("Intangibles", 50_000_00, 0)]
    db = _ChartDb(STANDARD_CHART)
    out = svc.for_filing(db, firm_id=FIRM, filing=_filing())
    t, i = _parts(out, "tangible_assets"), _parts(out, "intangible_assets")
    assert t["Gross block"]["amount_paise"] == 12 * L and t["Depreciation"]["amount_paise"] == 3 * L
    assert i["Gross block"]["amount_paise"] == 50_000_00 and i["Amortisation"]["amount_paise"] == 0
    assert out["tie_out"]["ok"] is True


def test_the_service_withholds_an_amortised_intangible_on_the_standard_chart(books):
    books["assets"] = [_asset("Plant & Machinery", 12 * L, 3 * L), _asset("Intangibles", 80_000_00, 30_000_00)]
    # What the standard chart's ledger holds: all the depreciation (3.3 lakh) in one account on the tangible line, the intangible at cost.
    books["statements"] = balanced_statements(assets={"tangible_assets": 12 * L - 3_30_000_00, "intangible_assets": 80_000_00})
    out = svc.for_filing(_ChartDb(STANDARD_CHART), firm_id=FIRM, filing=_filing())
    assert _parts(out, "tangible_assets")["Gross block"]["state"] == "not_recorded"
    assert any("differs from the ledger's" in g and "Accumulated Depreciation account" in g for g in out["gaps"]), out["gaps"]


def test_a_chart_the_ca_mapped_decides_the_line_and_not_the_accounts_name(books):
    # The CA mapped the Intangible Assets account to Tangible Fixed Assets, so the category is on the tangible line and there is no
    # intangible figure to place: the whole register is the tangible kind.
    books["assets"] = [_asset("Plant & Machinery", 12 * L, 3 * L), _asset("Intangibles", 50_000_00, 0)]
    books["statements"] = balanced_statements(assets={"tangible_assets": 9 * L + 50_000_00, "intangible_assets": 0})
    chart = [STANDARD_CHART[0], STANDARD_CHART[1], _account("a-int", "Intangible Assets", "Intangible Asset", "Tangible Fixed Assets")]
    out = svc.for_filing(_ChartDb(chart), firm_id=FIRM, filing=_filing())
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] == 12 * L + 50_000_00
    assert _parts(out, "intangible_assets")["Gross block"]["amount_paise"] == 0


def test_a_category_whose_ledger_is_not_on_the_chart_withholds_the_split(books):
    books["assets"] = [_asset("Plant & Machinery", 12 * L, 3 * L), _asset("Intangibles", 50_000_00, 0)]
    chart = [STANDARD_CHART[0], STANDARD_CHART[1]]                                       # no Intangible Assets account at all
    out = svc.for_filing(_ChartDb(chart), firm_id=FIRM, filing=_filing())
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] is None
    assert any("no ledger account could be found for the category 'Intangibles'" in g for g in out["gaps"]), out["gaps"]


def test_an_account_that_is_gone_when_it_is_read_is_not_given_a_line(books):
    books["assets"] = [_asset("Plant & Machinery", 12 * L, 3 * L), _asset("Intangibles", 50_000_00, 0)]
    db = _ChartDb(STANDARD_CHART)
    db.hide_by_id = True
    out = svc.for_filing(db, firm_id=FIRM, filing=_filing())
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] is None
    assert any("no ledger account could be found for the category" in g for g in out["gaps"]), out["gaps"]


@pytest.mark.parametrize("category", [None, "", "Zebra"])
def test_a_category_the_taxonomy_does_not_know_is_read_from_the_account_the_posting_would_use(books, category):
    """An asset row with no category, or one outside the taxonomy, is booked by the journals to the Plant & Machinery ledger
    (`ledger_pattern`), and the movement names a missing category 'Other', which that table maps to the same ledger."""
    books["assets"] = [_asset(category, 12 * L, 3 * L), _asset("Intangibles", 50_000_00, 0)]
    out = svc.for_filing(_ChartDb(STANDARD_CHART), firm_id=FIRM, filing=_filing())
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] == 12 * L
    assert _parts(out, "intangible_assets")["Gross block"]["amount_paise"] == 50_000_00


def test_another_clients_account_of_the_same_name_is_never_this_clients_ledger(books):
    books["assets"] = [_asset("Plant & Machinery", 12 * L, 3 * L), _asset("Intangibles", 50_000_00, 0)]
    chart = [STANDARD_CHART[0], STANDARD_CHART[1], _account("a-int-other", "Intangible Assets", "Intangible Asset", client="client-2")]
    out = svc.for_filing(_ChartDb(chart), firm_id=FIRM, filing=_filing())
    assert any("no ledger account could be found for the category 'Intangibles'" in g for g in out["gaps"]), out["gaps"]
    # while this client's own account of that name is found
    chart = [STANDARD_CHART[0], STANDARD_CHART[1], _account("a-int-own", "Intangible Assets", "Intangible Asset", client=CLIENT)]
    assert _parts(svc.for_filing(_ChartDb(chart), firm_id=FIRM, filing=_filing()), "intangible_assets")["Gross block"]["amount_paise"] == 50_000_00


def test_another_firms_account_is_never_the_ledger_of_this_one(books):
    books["assets"] = [_asset("Plant & Machinery", 12 * L, 3 * L), _asset("Intangibles", 50_000_00, 0)]
    chart = [STANDARD_CHART[0], STANDARD_CHART[1], _account("a-int", "Intangible Assets", "Intangible Asset", firm="firm-2")]
    out = svc.for_filing(_ChartDb(chart), firm_id=FIRM, filing=_filing())
    assert any("no ledger account could be found for the category 'Intangibles'" in g for g in out["gaps"]), out["gaps"]


def test_the_account_is_found_by_the_pattern_the_journals_use_and_read_under_the_firm(books):
    from domain.fixed_assets.asset_ledger import ledger_pattern
    books["assets"] = [_asset("Intangibles", 50_000_00, 0), _asset("Plant & Machinery", 12 * L, 3 * L)]
    db = _ChartDb(STANDARD_CHART)
    svc.for_filing(db, firm_id=FIRM, filing=_filing())
    assert ("chart_of_accounts", "ilike", "account_name", ledger_pattern("Intangibles")) in db.log
    assert ("chart_of_accounts", "ilike", "account_name", ledger_pattern("Plant & Machinery")) in db.log
    assert ("chart_of_accounts", "eq", "id", "a-int") in db.log
    # EVERY read of the chart, the lookup by pattern and the read of the account found, names the firm.
    reads = [conds for table, conds in db.queries if table == "chart_of_accounts"]
    assert len(reads) == 4 and all(("eq", "firm_id", FIRM) in conds for conds in reads), reads


def test_a_category_is_looked_up_once_and_only_when_it_holds_a_figure(books):
    # A vehicle bought in 2024-25 and sold in September 2025 leaves the register at nil: the category is in the movement and holds no
    # figure, and the standard chart used here has no Vehicles account at all, so a lookup made for it would withhold the split.
    sold = {**_asset("Vehicles", 1 * L, 20_000_00), "is_disposed": True, "disposal_date": "2025-09-01"}
    books["assets"] = [_asset("Plant & Machinery", 12 * L, 3 * L), _asset("Intangibles", 50_000_00, 0), sold]
    db = _ChartDb(STANDARD_CHART)
    out = svc.for_filing(db, firm_id=FIRM, filing=_filing())
    lookups = [e for e in db.log if e[:3] == ("chart_of_accounts", "ilike", "account_name")]
    assert len(lookups) == 2, lookups
    assert _parts(out, "tangible_assets")["Gross block"]["amount_paise"] == 12 * L


@pytest.mark.parametrize("form", ["ITR-3", "ITR-5"])
def test_the_firm_forms_read_no_chart_account(books, form):
    books["assets"] = [_asset("Plant & Machinery", 12 * L, 3 * L), _asset("Intangibles", 50_000_00, 0)]
    db = _ChartDb(STANDARD_CHART)
    out = svc.for_filing(db, firm_id=FIRM, filing=_filing(form))
    assert ("table", "chart_of_accounts") not in db.log
    assert {p["label"]: p for p in _slot_fixed(out)}["Gross block"]["amount_paise"] == 12 * L + 50_000_00


def _slot_fixed(out: dict) -> list[dict]:
    return next(s for s in out["balance_sheet"]["asset_slots"] if s["key"] == "fixed_assets")["parts"]


def test_the_standard_chart_books_every_categorys_depreciation_in_one_account():
    """The sentence the split gives when an amortised intangible breaks the tie is true of the standard chart, and this is what keeps it
    true: exactly one account is the Accumulated Depreciation account, and it is on the tangible line."""
    from services.coa_seed_service import STANDARD_COA
    named = [row for row in STANDARD_COA if "accumulated depreciation" in row[1].lower()]
    assert len(named) == 1, named
    _code, _name, account_type, subtype = named[0]
    assert lines.schedule_line_for_account(account_type, subtype, None) == TANGIBLE
    assert lines.schedule_line_for_account("Asset", "Intangible Asset", None) == INTANGIBLE


def test_the_depreciation_and_the_disposal_journals_use_the_one_accumulated_depreciation_account_whatever_the_category():
    """The other half of the sentence the split gives: the account the depreciation is credited to, and the disposal debits, is found by
    one fixed pattern and never by the asset's category, so an intangible asset's amortisation lands in the same account as a
    machine's depreciation. If that changes (POST-A-345 is the change) this test and the sentence change with it."""
    import ast
    import inspect
    import textwrap
    from services.phase2_journal_service import Phase2JournalService as P

    for fn in (P.journal_for_depreciation, P.journal_for_asset_disposal):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "_find_account"]
        accum = [c for c in calls if any(isinstance(a, ast.Constant) and a.value == "%Accumulated Depreciation%" for a in c.args)]
        assert len(accum) == 1, (fn.__name__, [ast.unparse(c) for c in calls])


def test_every_category_the_register_can_hold_is_booked_to_a_ledger_that_is_on_the_standard_chart_with_a_readable_line():
    """The split reads each category's line off the account the journals debit. On the standard chart every category has one, on one of the
    two lines, so a firm onboarded through the product never has a category withhold its own split."""
    from domain.fixed_assets.asset_ledger import LEDGER_PATTERN_BY_CATEGORY
    from services.coa_seed_service import STANDARD_COA
    for category, pattern in LEDGER_PATTERN_BY_CATEGORY.items():
        rx = re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("%")) + "$", re.I)
        found = [row for row in STANDARD_COA if rx.match(row[1])]
        assert len(found) == 1, (category, found)
        assert lines.schedule_line_for_account(found[0][2], found[0][3], None) in B.REGISTER_LINES, (category, found)
