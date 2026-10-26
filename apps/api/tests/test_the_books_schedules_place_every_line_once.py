"""POST-A-070 — the books laid out as Part A-BS and Part A-P&L of ITR-3, ITR-5 and ITR-6, with a tie-out that proves nothing was dropped.

WHAT WAS MISSING

    `itr_json.generate_itr_json` refuses a return because "for ITR-3, ITR-5 and ITR-6 [it needs] the balance sheet and
    profit-and-loss schedules the form requires", and the product held the books in Schedule III shape with nothing saying which box
    of the return each figure belongs in. `domain/income_tax/books_schedules.py` is that statement.

WHAT THIS FILE HOLDS

    * EVERY BOX NAMED IS IN THE DEPARTMENT'S OWN SCHEMA, with the type the figure needs (an integer to key, an object to key parts
      under). A path that drifts from a revised schema fails here and not at the portal.
    * EVERY LINE OF THE STATEMENTS IS PLACED EXACTLY ONCE per form, asserted over the plan's DATA against the statements' own vocabulary
      (`domain/reporting/year_end_lines`), so a line added there without a place here fails, and no two slots answer one box.
    * THE TIE-OUT IS ZERO on hand-computed fixtures for all three forms, and on every balanced set of books a property test can
      produce, and it is NOT zero when a line is dropped or counted twice (the negative controls at the foot).
    * A FIGURE IS PLACED ONLY WHERE THE BOOKS SETTLE THE BOX: a group the books keep whole is a total with the split NOT RECORDED, the
      fixed-asset register fills the gross block and the depreciation only where it ties to the ledger, and the answer never says the
      line-to-box table has been confirmed against the form's instructions.
"""
from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from domain.income_tax import books_schedules as B
from domain.income_tax import itr_schema
from domain.reporting import year_end_lines as lines
from tests._books_statements import L, balanced_statements

FORMS = list(B.FORMS)
MODULE = Path(B.__file__)


_statements = balanced_statements


def _assemble(form: str, statements=None, **kw) -> dict:
    return B.assemble(form=form, assessment_year="2026-27", financial_year="2025-26",
                      statements=statements or _statements(), **kw)


def _slot(out: dict, key: str) -> dict:
    return next(s for s in out["balance_sheet"]["liability_slots"] + out["balance_sheet"]["asset_slots"] if s["key"] == key)


# ── every box named is the Department's, with the type its figure needs ───────────────────────────────────────────────────────
def _paths(form: str):
    plan = B.plan_for(form)
    for key in ("liability_slots", "asset_slots", "pl_slots"):
        for slot in plan[key]:
            yield (slot.path, "integer", f"{key}:{slot.key}")
            if slot.group:
                yield (slot.group, "object", f"{key}:{slot.key}.group")
            for part in slot.parts:
                yield (part.path, "integer", f"{key}:{slot.key}.{part.label}")
    for c in list(plan["pl_checks"]) + list(plan["bs_checks"]):
        yield (c.path, "integer", f"check:{c.label}")


@pytest.mark.parametrize("form", FORMS)
def test_every_box_the_plan_names_exists_in_the_schema_with_the_type_its_figure_needs(form):
    bad = []
    for path, kind, what in _paths(form):
        node = itr_schema.resolve(form, B.root_path(form, path))
        if node is None:
            bad.append(f"{what}: {path} is not in the schema")
        elif node.get("type") != kind:
            bad.append(f"{what}: {path} is a {node.get('type')}, needs a {kind}")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("form", FORMS)
def test_no_two_slots_answer_one_box(form):
    seen: dict[str, str] = {}
    for path, kind, what in _paths(form):
        if kind != "integer":
            continue
        assert path not in seen, f"{path} is answered by both {seen[path]} and {what}"
        seen[path] = what


@pytest.mark.parametrize("form", FORMS)
def test_a_group_with_parts_says_why_the_books_cannot_split_it(form):
    """`question` is what turns "not recorded" from a shrug into a sentence the CA acts on."""
    plan = B.plan_for(form)
    for key in ("liability_slots", "asset_slots", "pl_slots"):
        for slot in plan[key]:
            if slot.group:
                assert slot.question.strip(), f"{form}:{slot.key} names a group of parts and never says why they are not split"
    for u in list(plan["unplaced"]) + list(plan["pl_unplaced"]):
        assert u.question.strip(), f"{form}: {u.line} is unplaced and never says what would place it"


# ── every line of the statements is placed exactly once ───────────────────────────────────────────────────────────────────────
def test_the_modules_line_vocabulary_is_the_statements_vocabulary():
    assert set(B.BS_LIABILITY_LINES) == set(lines.BS_EQUITY_LIABILITY_LINES)
    assert set(B.BS_ASSET_LINES) == set(lines.BS_ASSET_LINES)
    assert set(B.PL_INCOME_LINES) == set(lines.PL_INCOME_LINES)
    assert set(B.PL_EXPENSE_LINES) == set(lines.PL_EXPENSE_LINES)
    assert set(B.PL_TAX_LINES) == set(lines.PL_TAX_LINES)
    every = set(B.BS_LIABILITY_LINES + B.BS_ASSET_LINES + B.PL_INCOME_LINES + B.PL_EXPENSE_LINES + B.PL_TAX_LINES)
    assert every == set(B.LINE_LABELS), "a line has no label, or a label has no line"


@pytest.mark.parametrize("form", FORMS)
def test_every_balance_sheet_line_is_in_exactly_one_slot_or_unplaced(form):
    plan = B.plan_for(form)
    placed = [n for s in plan["liability_slots"] + plan["asset_slots"] for n in s.lines] + [u.line for u in plan["unplaced"]]
    assert sorted(placed) == sorted(B.BS_LIABILITY_LINES + B.BS_ASSET_LINES)


@pytest.mark.parametrize("form", FORMS)
def test_every_profit_and_loss_line_is_in_exactly_one_slot_or_unplaced(form):
    plan = B.plan_for(form)
    placed = [n for s in plan["pl_slots"] for n in s.lines] + [u.line for u in plan["pl_unplaced"]]
    assert sorted(placed) == sorted(B.PL_INCOME_LINES + B.PL_EXPENSE_LINES + B.PL_TAX_LINES)


def test_the_company_form_has_a_place_for_every_line_and_the_firm_forms_name_what_they_cannot_place():
    assert B.plan_for("ITR-6")["unplaced"] == ()
    for form in ("ITR-3", "ITR-5"):
        assert {u.line for u in B.plan_for(form)["unplaced"]} == {
            "other_long_term_liabilities", "long_term_provisions", "other_non_current_assets"}


# ── the tie-out ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("form", FORMS)
def test_the_tie_out_is_zero_on_balanced_books(form):
    out = _assemble(form)
    bad = [(c["name"], c["difference_paise"]) for c in out["tie_out"]["checks"] if c["difference_paise"]]
    assert out["tie_out"]["ok"] is True and out["tie_out"]["difference_paise"] == 0, bad


@pytest.mark.parametrize("form", ["ITR-3", "ITR-5"])
def test_the_funds_layout_hand_computed(form):
    out = _assemble(form)
    assert _slot(out, "owners_fund")["amount_paise"] == 12_50_000_00
    assert _slot(out, "loan_funds")["amount_paise"] == 6 * L
    assert _slot(out, "deferred_tax_liability")["amount_paise"] == 10_000_00
    assert _slot(out, "fixed_assets")["amount_paise"] == 10_50_000_00
    assert _slot(out, "investments")["amount_paise"] == 30_000_00
    assert _slot(out, "inventories")["amount_paise"] == 4 * L
    assert _slot(out, "sundry_debtors")["amount_paise"] == 5 * L
    assert _slot(out, "cash_and_bank")["amount_paise"] == 2 * L
    assert _slot(out, "other_current_assets")["amount_paise"] == 35_000_00
    assert _slot(out, "loans_and_advances")["amount_paise"] == 50_000_00
    cl = _slot(out, "current_liabilities_and_provisions")
    assert cl["amount_paise"] == 4 * L and cl["deduct"] is True
    rec = out["balance_sheet"]["reconciliation"]
    assert rec["funds_sourced_paise"] == 18_60_000_00
    assert rec["funds_applied_paise"] == 18_65_000_00
    # They differ by the five thousand rupees of long-term provisions the form has no box for, and by nothing else.
    assert rec["unplaced_liabilities_paise"] == 5_000_00 and rec["difference_paise"] == 0


def test_the_company_layout_hand_computed():
    out = _assemble("ITR-6")
    assert out["balance_sheet"]["layout"] == B.LAYOUT_SCHEDULE_III
    assert _slot(out, "share_capital")["amount_paise"] == 10 * L
    assert _slot(out, "long_term_borrowings")["amount_paise"] == 5 * L
    assert _slot(out, "trade_payables")["amount_paise"] == 3 * L
    assert _slot(out, "tangible_assets")["amount_paise"] == 9 * L
    assert _slot(out, "capital_wip")["amount_paise"] == 1 * L
    assert out["balance_sheet"]["reconciliation"] == {
        "total_equity_and_liabilities_paise": 22_65_000_00, "total_assets_paise": 22_65_000_00, "difference_paise": 0}
    totals = {c["label"]: c["amount_paise"] for c in out["balance_sheet"]["checks"]}
    assert totals == {"Total equity and liabilities": 22_65_000_00, "Total assets": 22_65_000_00}


@pytest.mark.parametrize("form", FORMS)
def test_the_profit_and_loss_reaches_the_statements_profit_before_tax(form):
    out = _assemble(form)
    pl = out["profit_loss"]
    assert pl["reconciliation"]["income_paise"] == 50_50_000_00
    assert pl["reconciliation"]["expense_paise"] == 43_10_000_00
    assert pl["reconciliation"]["profit_before_tax_paise"] == 7_40_000_00
    assert pl["reconciliation"]["profit_after_tax_paise"] == 5_80_000_00
    checks = {c["label"]: c["amount_paise"] for c in pl["checks"]}
    assert checks == {"Profit before tax": 7_40_000_00, "Profit after tax": 5_80_000_00}
    placed = {s["key"]: s["amount_paise"] for s in pl["slots"]}
    assert placed == {"other_income": 50_000_00, "employee_benefit_expense": 8 * L, "finance_costs": 60_000_00,
                      "depreciation_and_amortisation": 1_50_000_00, "current_tax": 1_50_000_00, "deferred_tax": 10_000_00}
    assert {u["line"] for u in pl["unplaced"]} == {
        "revenue_from_operations", "cost_of_materials_consumed", "purchases_of_stock_in_trade", "changes_in_inventories",
        "other_expenses"}
    # A line that nets to a negative (stock built up) keeps its sign: a changes-in-inventories of -1 lakh is a credit to the account.
    assert next(u for u in pl["unplaced"] if u["line"] == "changes_in_inventories")["amount_paise"] == -1 * L


@pytest.mark.parametrize("form", FORMS)
def test_every_rupee_figure_is_the_paise_figure_rounded_half_away_from_zero(form):
    out = _assemble(form, _statements(assets={"cash_and_bank": 2 * L + 50}, liabilities={"reserves_and_surplus": 2_50_000_00 + 50}))
    cash = _slot(out, "cash_and_bank")
    assert cash["amount_paise"] == 2 * L + 50 and cash["amount_rupees"] == 2 * L // 100 + 1
    assert B._to_rupees(-150) == -2 and B._to_rupees(149) == 1


@pytest.mark.parametrize("form", FORMS)
def test_every_json_path_is_the_schemas_own_root_first(form):
    out = _assemble(form)
    root = "ITR." + form.replace("-", "")
    for s in out["balance_sheet"]["liability_slots"] + out["balance_sheet"]["asset_slots"] + out["profit_loss"]["slots"]:
        assert s["json_path"].startswith(root + "."), s["json_path"]
        assert itr_schema.is_integer_field(form, s["json_path"]), s["json_path"]


# ── a figure is placed only where the books settle the box ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("form", FORMS)
def test_a_group_the_books_keep_whole_is_a_total_with_the_split_not_recorded(form):
    out = _assemble(form)
    loan_key = "loan_funds" if form != "ITR-6" else "long_term_borrowings"
    loans = _slot(out, loan_key)
    assert loans["role"] == "group_total" and loans["parts"] == [] and loans["not_split_paise"] == loans["amount_paise"]
    assert loans["parts_under"] and loans["question"]
    assert "secured" in loans["question"]


@pytest.mark.parametrize("form", FORMS)
def test_a_single_box_is_keyed_directly_and_carries_no_split(form):
    out = _assemble(form)
    other = _slot(out, "other_current_assets")
    assert other["role"] == "box" and other["parts_under"] is None and other["not_split_paise"] == 0
    if form == "ITR-3":     # the one form whose debtors are a single box
        assert _slot(out, "sundry_debtors")["role"] == "box"


def test_funds_applied_sets_the_current_liabilities_against_the_assets():
    out = _assemble("ITR-3")
    rec = out["balance_sheet"]["reconciliation"]
    assert rec["funds_applied_paise"] == 22_65_000_00 - 4 * L
    out = _assemble("ITR-3", _statements(liabilities={"trade_payables": 3 * L + 1, "reserves_and_surplus": 2_50_000_00 - 1}))
    assert out["balance_sheet"]["reconciliation"]["funds_applied_paise"] == 22_65_000_00 - 4 * L - 1


def test_a_debit_balance_in_reserves_is_not_keyed_as_a_negative_reserve():
    # Reserves of minus one lakh instead of plus 2.5 lakh: the tangible assets fall by the same 3.5 lakh so the books still balance.
    out = _assemble("ITR-3", _statements(liabilities={"reserves_and_surplus": -1 * L},
                                          assets={"tangible_assets": 9 * L - 3_50_000_00}))
    owners = _slot(out, "owners_fund")
    # The group itself is positive (capital outweighs the deficit): the note is about the LINE, not the total.
    assert owners["amount_paise"] > 0
    assert len(owners["negative_notes"]) == 1 and "accumulated loss" in owners["negative_notes"][0]
    assert "negative_notes" not in _slot(_assemble("ITR-3"), "owners_fund")


# ── the fixed-asset register fills the gross block only where it ties to the ledger ─────────────────────────────────────────────
def _register(**kw):
    base = {"gross": 15 * L, "accumulated": 5 * L, "net": 9 * L + 50_000_00, "split_known": True}
    base.update(kw)
    return base


@pytest.mark.parametrize("form", ["ITR-3", "ITR-5"])
def test_the_register_fills_the_gross_block_and_the_depreciation_when_it_ties(form):
    out = _assemble(form, register=_register())
    parts = {p["label"]: p for p in _slot(out, "fixed_assets")["parts"]}
    assert parts["Gross block"]["amount_paise"] == 15 * L and parts["Gross block"]["state"] == "placed"
    assert parts["Depreciation"]["amount_paise"] == 5 * L
    assert parts["Net block"]["amount_paise"] == 9 * L + 50_000_00           # the ledger's, not the register's
    assert parts["Capital work-in-progress"]["amount_paise"] == 1 * L
    assert not any("register" in g and "left for the CA" in g for g in out["gaps"])


@pytest.mark.parametrize("why,reg", [
    ("differs from the ledger", _register(net=9 * L)),
    ("could not say how much of each asset's depreciation belongs to this year", _register(split_known=False)),
])
def test_the_register_is_withheld_with_its_reason_when_it_does_not_tie(why, reg):
    out = _assemble("ITR-3", register=reg)
    parts = {p["label"]: p for p in _slot(out, "fixed_assets")["parts"]}
    assert parts["Gross block"]["amount_paise"] is None and parts["Gross block"]["state"] == "not_recorded"
    assert parts["Depreciation"]["amount_paise"] is None
    assert parts["Net block"]["amount_paise"] == 9 * L + 50_000_00            # the ledger's net is still given
    assert any(why in g for g in out["gaps"]), out["gaps"]


def test_no_register_read_is_said_and_gives_no_gross_block():
    out = _assemble("ITR-3", register=None)
    parts = {p["label"]: p for p in _slot(out, "fixed_assets")["parts"]}
    assert parts["Gross block"]["amount_paise"] is None
    assert any("register was not read" in g for g in out["gaps"])


def test_the_company_form_says_its_gross_block_is_left_for_the_ca_whether_or_not_the_register_ties():
    for reg in (None, _register()):
        out = _assemble("ITR-6", register=reg)
        gaps = [g for g in out["gaps"] if "gross block" in g]
        assert len(gaps) == 1 and "tangible and of intangible" in gaps[0], gaps
        assert not any("register was not read" in g for g in out["gaps"])


def test_a_register_that_disagrees_is_reported_in_the_tie_out_without_failing_it():
    out = _assemble("ITR-3", register=_register(net=9 * L))
    row = next(c for c in out["tie_out"]["checks"] if c["name"] == "register_net_block_vs_ledger")
    assert row["difference_paise"] == -50_000_00 and row["informational"] is True
    assert out["tie_out"]["ok"] is True and out["tie_out"]["difference_paise"] == 0


# ── what it does not know, it says ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("form", FORMS)
def test_the_mapping_is_never_presented_as_confirmed(form):
    out = _assemble(form)
    assert out["mapping_confirmed"] is False and B.MAPPING_CONFIRMED is False
    assert any("has not been read against the form's instructions" in g for g in out["gaps"])
    assert any("Ind AS" in g for g in out["gaps"]) and out["framework"] == "AS (Schedule III, Division I)"


def test_the_module_does_not_claim_the_table_is_confirmed():
    text = MODULE.read_text()
    assert "MAPPING_CONFIRMED = False" in text
    assert not re.search(r"MAPPING_CONFIRMED\s*=\s*True", text)


def test_the_assembly_reads_no_database_and_computes_no_tax():
    """It takes the statements and the §32 working as they are. A second reader of the ledger is a second answer to what the
    balance sheet says, and a rate here is a second tax engine."""
    tree = ast.parse(MODULE.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any(m.startswith(("core.db", "core.supabase", "supabase", "services.")) for m in imported), imported
    source = MODULE.read_text()
    assert ".table(" not in source and ".execute(" not in source


def test_a_form_without_a_balance_sheet_is_refused_not_answered_empty():
    for form in ("ITR-1", "ITR-2", "ITR-4", "ITR-7", "nonsense"):
        with pytest.raises(ValueError):
            B.assemble(form=form, assessment_year="2026-27", financial_year="2025-26", statements=_statements())
        with pytest.raises(ValueError):
            B.plan_for(form)


# ── a figure the schema's own minimum refuses is said, wherever it lands ─────────────────────────────────────────────────────────
def _slot_boxes(out: dict):
    """Every box dict a slot or one of its parts carries, in the balance sheet and the profit and loss account."""
    bs, pl = out["balance_sheet"], out["profit_loss"]
    for slot in bs["liability_slots"] + bs["asset_slots"] + pl["slots"]:
        yield slot
        yield from slot["parts"]


def _every_box_under_its_schemas_minimum_is_flagged_and_said(form: str, out: dict) -> None:
    """The rule, judged against the schema read here and not through the module: a box is flagged exactly when its whole-rupee figure
    is under the schema's `minimum`, and a flagged slot box is in the answer's list of what the layout cannot settle."""
    for box in _slot_boxes(out):
        if box.get("amount_rupees") is None:
            assert "below_form_minimum" not in box
            continue
        minimum = (itr_schema.resolve(form, box["json_path"]) or {}).get("minimum")
        under = minimum is not None and box["amount_rupees"] < minimum
        assert ("below_form_minimum" in box) is under, (form, box["json_path"], box["amount_rupees"], minimum)
        if under:
            assert box["below_form_minimum"]["minimum_rupees"] == minimum
            assert box["below_form_minimum"]["sentence"] in out["gaps"], (form, box["json_path"])


def _slot_holding(out: dict, line: str) -> dict:
    slots = out["balance_sheet"]["liability_slots"] + out["balance_sheet"]["asset_slots"] + out["profit_loss"]["slots"]
    return next(s for s in slots if line in [ln["line"] for ln in s["lines"]])


@pytest.mark.parametrize("form", FORMS)
def test_a_negative_receivables_balance_is_said_on_its_box_and_the_books_still_tie(form):
    # Customers' advances held inside receivables: trade receivables of minus one lakh, balanced by cash of eight lakh (was two).
    out = _assemble(form, _statements(assets={"trade_receivables": -1 * L, "cash_and_bank": 8 * L}))
    slot = _slot_holding(out, "trade_receivables")
    assert slot["amount_paise"] == -1 * L
    # The Department's schema accepts nothing below nil in the box that holds receivables, on all three forms.
    assert slot["below_form_minimum"]["minimum_rupees"] == 0
    sentence = slot["below_form_minimum"]["sentence"]
    assert "minus ₹1,00,000.00" in sentence and "accepts nothing below ₹0.00" in sentence and "CA's decision" in sentence
    assert sentence in slot["negative_notes"] and sentence in out["gaps"]
    # The books tie, and say so: the tie-out is about the books, and the schema is a second question the box itself answers.
    assert out["tie_out"]["ok"] is True and out["tie_out"]["difference_paise"] == 0
    # An ordinary balance carries no flag and no sentence.
    assert "below_form_minimum" not in _slot_holding(_assemble(form), "trade_receivables")


@pytest.mark.parametrize("form", FORMS)
def test_a_negative_profit_and_loss_total_in_a_bounded_box_is_said_too(form):
    # Employee benefit expense of minus one lakh (a reversal larger than the year's cost), the loss absorbed by a smaller profit.
    out = _assemble(form, _statements(expenses={"employee_benefit_expense": -1 * L}, current_tax=0, deferred_tax=0))
    box = _slot_holding(out, "employee_benefit_expense")
    minimum = (itr_schema.resolve(form, box["json_path"]) or {}).get("minimum")
    if minimum is None:
        pytest.skip(f"{form}'s box for employee benefit expense states no minimum")
    assert box["amount_paise"] < 0 and box["below_form_minimum"]["minimum_rupees"] == minimum
    assert box["below_form_minimum"]["sentence"] in out["gaps"]


def test_the_flag_is_the_schemas_minimum_and_not_a_zero_typed_here():
    # ITR-5 and ITR-6 bound a few boxes at minus ninety-nine trillion; a figure of minus one lakh is inside that bound, so it is not flagged
    # there, which a test for "negative" would get wrong.
    for form in ("ITR-5", "ITR-6"):
        bounds = {}
        for slot in B.plan_for(form)["liability_slots"] + B.plan_for(form)["asset_slots"]:
            bounds[slot.path] = (itr_schema.resolve(form, B.root_path(form, slot.path)) or {}).get("minimum")
        wide = [path for path, m in bounds.items() if isinstance(m, int) and m < -10**12]
        assert wide, f"{form} has no box with a wide minimum; the test's premise is gone"
        out = _assemble(form, _statements(liabilities={"reserves_and_surplus": -1 * L}, assets={"tangible_assets": 9 * L - 3_50_000_00}))
        for box in _slot_boxes(out):
            if box["json_path"].split(".", 2)[2] in wide and box["amount_rupees"] is not None:
                assert "below_form_minimum" not in box, (form, box["json_path"])


# ── a count is not money ──────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("form", FORMS)
def test_the_placed_once_checks_are_counts_and_the_money_difference_is_money_only(form, monkeypatch):
    out = _assemble(form)
    units = {c["name"]: c["unit"] for c in out["tie_out"]["checks"]}
    assert units["balance_sheet_lines_placed_once"] == "count" == units["profit_loss_lines_placed_once"]
    assert all(u == "paise" for n, u in units.items() if not n.endswith("_placed_once"))
    # A line placed twice is one misplaced LINE: the count says one, and the paise difference is not made of it.
    real = B.plan_for

    def doubled(f):
        plan = dict(real(f))
        first = plan["liability_slots"][0]
        plan["liability_slots"] = (first,) + tuple(plan["liability_slots"])
        return plan
    monkeypatch.setattr(B, "plan_for", doubled)
    bad = _assemble(form)
    assert bad["tie_out"]["ok"] is False and bad["tie_out"]["lines_misplaced"] >= 1
    assert bad["tie_out"]["difference_paise"] == sum(
        abs(c["difference_paise"]) for c in bad["tie_out"]["checks"] if c["unit"] == "paise" and not c["informational"])


# ── the property: any balanced books tie out, on every form ─────────────────────────────────────────────────────────────────────
_amount = st.integers(min_value=-5_000_000_00, max_value=50_000_000_00)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(liab=st.fixed_dictionaries({k: _amount for k in B.BS_LIABILITY_LINES if k != "reserves_and_surplus"}),
       asset=st.fixed_dictionaries({k: _amount for k in B.BS_ASSET_LINES}),
       income=st.fixed_dictionaries({k: _amount for k in B.PL_INCOME_LINES}),
       expense=st.fixed_dictionaries({k: _amount for k in B.PL_EXPENSE_LINES}),
       tax=st.tuples(_amount, _amount))
def test_any_balanced_books_tie_out_on_every_form(liab, asset, income, expense, tax):
    # Reserves is the balancing figure, exactly as the statements make it (the surplus carried into equity).
    reserves = sum(asset.values()) - sum(liab.values())
    stmts = _statements(liabilities={**liab, "reserves_and_surplus": reserves}, assets=asset, income=income, expenses=expense,
                        current_tax=tax[0], deferred_tax=tax[1])
    for form in FORMS:
        out = _assemble(form, stmts)
        bad = [(c["name"], c["difference_paise"]) for c in out["tie_out"]["checks"] if c["difference_paise"]]
        assert not bad, (form, bad)
        # Every line is somewhere: the placed and unplaced amounts add to the statements' totals, side by side.
        bs = out["balance_sheet"]
        in_slots = sum(ln["amount_paise"] for s in bs["liability_slots"] + bs["asset_slots"] for ln in s["lines"])
        in_unplaced = sum(u["amount_paise"] for u in bs["unplaced"])
        assert in_slots + in_unplaced == stmts["balance_sheet"]["total_equity_and_liabilities_paise"] + \
            stmts["balance_sheet"]["total_assets_paise"]
        _every_box_under_its_schemas_minimum_is_flagged_and_said(form, out)


# ── negative controls: the tie-out is not decorative ────────────────────────────────────────────────────────────────────────────
def test_a_line_dropped_from_the_plan_is_caught_by_the_tie_out(monkeypatch):
    real = B.plan_for

    def without_trade_receivables(form):
        plan = dict(real(form))
        key = "asset_slots"
        plan[key] = tuple(s for s in plan[key] if "trade_receivables" not in s.lines)
        return plan
    monkeypatch.setattr(B, "plan_for", without_trade_receivables)
    out = _assemble("ITR-6")
    assert out["tie_out"]["ok"] is False
    names = {c["name"] for c in out["tie_out"]["checks"] if c["difference_paise"]}
    assert {"balance_sheet_lines_placed_once", "balance_sheet_assets"} <= names


def test_a_line_counted_twice_is_caught_by_the_tie_out(monkeypatch):
    real = B.plan_for

    def twice(form):
        plan = dict(real(form))
        extra = B.Slot("again", "Again", plan["asset_slots"][0].path + "X", ("inventories",))
        plan["asset_slots"] = plan["asset_slots"] + (extra,)
        return plan
    monkeypatch.setattr(B, "plan_for", twice)
    out = _assemble("ITR-6")
    assert out["tie_out"]["ok"] is False
    assert any(c["name"] == "balance_sheet_lines_placed_once" and c["difference_paise"] for c in out["tie_out"]["checks"])


def test_books_that_do_not_balance_are_reported_not_absorbed():
    stmts = _statements()
    stmts["balance_sheet"]["assets"]["cash_and_bank"] += 700
    stmts["balance_sheet"]["total_assets_paise"] += 700
    stmts["balance_sheet"]["is_balanced"] = False
    out = _assemble("ITR-6", stmts)
    assert out["tie_out"]["ok"] is False
    assert any(c["name"] == "balance_sheet_balances" and c["difference_paise"] == -700 for c in out["tie_out"]["checks"])
    assert out["tie_out"]["balance_sheet_is_balanced"] is False


def test_a_profit_that_the_lines_do_not_reach_is_reported():
    stmts = copy.deepcopy(_statements())
    stmts["profit_loss"]["profit_before_tax_paise"] += 100
    out = _assemble("ITR-3", stmts)
    assert any(c["name"] == "profit_before_tax" and c["difference_paise"] == -100 for c in out["tie_out"]["checks"])


# ── end to end: the REAL statements engine over a ledger, then the layout ────────────────────────────────────────────────────────
# Everything above feeds the assembly a hand-made statements dict. This is the same assembly over what `generate_financial_statements`
# actually returns for a small ledger, so a key the engine does not serve, or serves under another name, fails here and not in front of a CA.
_E2E_ACCOUNTS = [
    ("A-CAP", "Equity", "Share Capital"), ("A-LOAN", "Liability", "Long-term Borrowings"),
    ("A-PAY", "Liability", "Trade Payables"), ("A-OCL", "Liability", "Other Current Liabilities"),
    ("A-FA", "Asset", "Tangible Fixed Assets"), ("A-INV", "Asset", "Inventories"), ("A-DEB", "Asset", "Trade Receivables"),
    ("A-BANK", "Asset", "Cash & Cash Equivalents"), ("A-SALE", "Revenue", "Revenue from Operations"),
    ("A-OI", "Revenue", "Other Income"), ("A-PUR", "Expense", "Cost of Materials Consumed"),
    ("A-EMP", "Expense", "Employee Benefits Expense"), ("A-FIN", "Expense", "Finance Costs"),
    ("A-DEP", "Expense", "Depreciation & Amortisation"), ("A-OTH", "Expense", "Other Expenses"),
]
#: account -> (debit, credit) in paise, all in April 2025. The bank balance is the figure that makes the books balance.
_E2E_BALANCES = {
    "A-CAP": (0, 10 * L), "A-LOAN": (0, 5 * L), "A-PAY": (0, 2 * L), "A-OCL": (0, 50_000_00),
    "A-FA": (9 * L, 0), "A-INV": (3 * L, 0), "A-DEB": (4 * L, 0), "A-BANK": (4_90_000_00, 0),
    "A-SALE": (0, 30 * L), "A-OI": (0, 20_000_00), "A-PUR": (18 * L, 0), "A-EMP": (5 * L, 0),
    "A-FIN": (40_000_00, 0), "A-DEP": (90_000_00, 0), "A-OTH": (2_50_000_00, 0),
}


class _Ledger:
    """Answers the tables `generate_financial_statements` reads, from the balances above; every filter is ignored, as in the other
    year-end tests (a fixed ledger is exactly as faithful as one the filters would have cut down to itself)."""
    def __init__(self):
        self._t = None

    def table(self, name):
        self._t = name
        return self

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def gt(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def or_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        if self._t == "account_period_balances":
            data = [{"id": f"b-{a}", "account_id": a, "period_month": "2025-04-01", "debit_paise": dr, "credit_paise": cr}
                    for a, (dr, cr) in _E2E_BALANCES.items()]
        elif self._t == "chart_of_accounts":
            data = [{"id": a, "account_type": t, "account_subtype": None, "schedule_iii_mapping": caption}
                    for a, t, caption in _E2E_ACCOUNTS]
        elif self._t == "journal_lines":
            data = [{"id": f"l-{a}", "journal_entry_id": f"l-{a}", "account_id": a, "debit_paise": dr, "credit_paise": cr,
                     "journal_entries": {"entry_date": "2025-04-01"}} for a, (dr, cr) in _E2E_BALANCES.items()]
        else:
            data = []
        return type("R", (), {"data": data})()


def _real_statements() -> dict:
    import unittest.mock as m
    import services.year_end_financial_service as mod
    with m.patch.object(mod, "_USE_MOCK", False):       # the live branch; mock mode returns a constant and reads nothing
        return mod.generate_financial_statements(_Ledger(), client_id="C1", firm_id="F1",
                                                 fy_start="2025-04-01", fy_end="2026-03-31")


@pytest.mark.parametrize("form", FORMS)
def test_over_the_real_statements_engine_the_layout_ties_out_and_places_the_books(form):
    stmts = _real_statements()
    assert stmts["balance_sheet"]["total_assets_paise"] == 20_90_000_00 == stmts["balance_sheet"]["total_equity_and_liabilities_paise"]
    out = _assemble(form, stmts)
    bad = [(c["name"], c["difference_paise"]) for c in out["tie_out"]["checks"] if c["difference_paise"]]
    assert out["tie_out"]["ok"] is True and not bad, bad
    assert out["tie_out"]["trial_balance_hash"] == stmts["trial_balance_hash"] and out["period"]["end"] == "2026-03-31"
    pl = {s["key"]: s["amount_paise"] for s in out["profit_loss"]["slots"]}
    assert pl["other_income"] == 20_000_00 and pl["employee_benefit_expense"] == 5 * L
    assert pl["finance_costs"] == 40_000_00 and pl["depreciation_and_amortisation"] == 90_000_00
    assert out["profit_loss"]["reconciliation"]["profit_before_tax_paise"] == 3_40_000_00
    unplaced = {u["line"]: u["amount_paise"] for u in out["profit_loss"]["unplaced"]}
    assert unplaced["revenue_from_operations"] == 30 * L and unplaced["cost_of_materials_consumed"] == 18 * L
    assert unplaced["other_expenses"] == 2_50_000_00


@pytest.mark.parametrize("form", ["ITR-3", "ITR-5"])
def test_over_the_real_engine_the_funds_layout_hand_computed(form):
    out = _assemble(form, _real_statements())
    # Capital 10 lakh plus this year's profit of 3.4 lakh carried into reserves; five lakh of borrowings.
    assert _slot(out, "owners_fund")["amount_paise"] == 13_40_000_00
    assert _slot(out, "loan_funds")["amount_paise"] == 5 * L
    assert _slot(out, "fixed_assets")["amount_paise"] == 9 * L
    assert _slot(out, "cash_and_bank")["amount_paise"] == 4_90_000_00
    assert _slot(out, "current_liabilities_and_provisions")["amount_paise"] == 2_50_000_00
    rec = out["balance_sheet"]["reconciliation"]
    assert rec["funds_sourced_paise"] == 18_40_000_00 and rec["funds_applied_paise"] == 18_40_000_00 and rec["difference_paise"] == 0
