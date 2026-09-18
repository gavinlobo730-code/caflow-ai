"""Stock ageing — the units ON HAND, not the item (INV-04).

DAYS IDLE AND AGEING ARE DIFFERENT QUESTIONS, and getting one does not get the
other. The register already shows Last Moved and Days Idle off migration 363,
which answers "has this ITEM moved". An item selling steadily has a recent
answer and may still be carrying units bought three years ago behind the ones
that keep turning over — and those are the AS-2 paragraph 24 obsolescence the
write-down endpoint has always offered with nothing to decide it on.

The SQL twin is pinned against this rule by
`tests/test_stock_ageing_parity_pg.py`; this module exercises the rule itself,
in mock mode, including the three things that are easy to get wrong and would
never surface as an exception:

  * FIFO CONSUMPTION — 120 units out of 150 must eat the OLD layer, not the new
  * THE VALUE FOOTING — the bands must sum to the carrying amount exactly
  * WHAT AN EMPTY ROW OF BANDS MEANS — nil is not "no old stock here"
"""
from __future__ import annotations

import ast
import inspect
from datetime import date
from decimal import Decimal as D

import pytest

from domain.reporting import stock_ageing as sa

AS_OF = date(2026, 9, 18)
META = {"service_catalogue_id": "i1", "name": "Widget", "unit": "PCS"}


def _one(movements, as_of=AS_OF):
    return sa.compute([(META, movements)], as_of)["items"][0]


def M(when, qty, value):
    return sa.Movement(movement_date=date.fromisoformat(when),
                       quantity_delta=D(str(qty)), value_delta_paise=value)


# ═════════════════════════════════════════════════════════════════════════════
# THE FINDING
# ═════════════════════════════════════════════════════════════════════════════

def test_an_item_that_keeps_selling_still_shows_its_old_stock():
    """THE FINDING, AS A NUMBER. Last Moved says 1 September and 70 of the 120
    units on hand have been there since June 2023 — which Days Idle cannot say
    and this must."""
    row = _one([M("2023-06-01", 100, 1_000_000),
                M("2026-08-20", 50, 600_000),
                M("2026-09-01", -30, -320_000)])
    assert D(row["band_qty"]["d365_plus"]) == 70
    assert D(row["band_qty"]["d0_30"]) == 50
    assert row["oldest_holding_date"] == "2023-06-01"


def test_fifo_consumes_the_oldest_layer_first():
    """120 out of 150 leaves 30 of the NEWEST, not 30 of the oldest. Getting
    this backwards reports three-year-old stock as a month old on every client
    whose sales exceed their oldest receipt."""
    row = _one([M("2023-06-01", 100, 1_000_000),
                M("2026-08-20", 50, 600_000),
                M("2026-09-01", -120, -1_280_000)])
    assert D(row["band_qty"]["d365_plus"]) == 0
    assert D(row["band_qty"]["d0_30"]) == 30


def test_the_bands_foot_to_the_quantity_and_the_carrying_amount():
    """The report's one hard invariant: somebody WILL foot it against the
    Inventories line."""
    row = _one([M("2023-06-01", 100, 1_000_000),
                M("2025-01-15", 40, 500_000),
                M("2026-08-20", 50, 600_000),
                M("2026-09-01", -30, -320_000)])
    assert sum(D(v) for v in row["band_qty"].values()) == D(row["qty_units"])
    assert sum(row["band_value_paise"].values()) == row["value_paise"]


@pytest.mark.parametrize("paise", [1, 2, 5, 7, 99, 101, 999_999_999])
def test_an_awkward_carrying_amount_still_foots(paise):
    """Largest remainder. A pro-rata split that loses a paisa on some values
    and not others is the defect `domain/gst/discount.py` records."""
    row = _one([M("2023-01-01", 1, 0), M("2026-09-01", 2, paise)])
    assert sum(row["band_value_paise"].values()) == row["value_paise"] == paise


# ═════════════════════════════════════════════════════════════════════════════
# THE BOUNDARIES, STATED ONCE
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("age,band", [
    (0, "d0_30"), (30, "d0_30"), (31, "d31_60"), (60, "d31_60"),
    (61, "d61_90"), (90, "d61_90"), (91, "d91_180"), (180, "d91_180"),
    (181, "d181_365"), (365, "d181_365"), (366, "d365_plus"), (5000, "d365_plus"),
])
def test_each_band_owns_its_upper_bound(age, band):
    """"Up to and including". The same figure appearing in two adjacent columns
    on two screens is what one authority for the boundary prevents."""
    assert sa.band_for_age(age) == band


def test_the_bands_are_rendered_in_the_servers_order_not_alphabetically():
    """'d0_30' sorts AFTER 'd181_365' alphabetically, so a screen that sorted
    the keys would show the oldest band first and label it '0–30 days'."""
    assert sa.BAND_KEYS == ("d0_30", "d31_60", "d61_90",
                            "d91_180", "d181_365", "d365_plus")
    assert sorted(sa.BAND_KEYS) != list(sa.BAND_KEYS)
    assert set(sa.BAND_LABELS) == set(sa.BAND_KEYS)


# ═════════════════════════════════════════════════════════════════════════════
# NOTHING TO AGE IS ITS OWN ANSWER
# ═════════════════════════════════════════════════════════════════════════════

def test_an_oversold_item_says_so_rather_than_showing_empty_bands():
    """Six zeroes beside a negative quantity read as 'no old stock here', which
    is the opposite of what an oversold item is telling the CA."""
    row = _one([M("2026-01-01", 10, 10_000), M("2026-02-01", -15, -15_000)])
    assert D(row["qty_units"]) == -5
    assert row["nothing_on_hand"] is True
    assert all(D(v) == 0 for v in row["band_qty"].values())
    assert row["oldest_holding_date"] is None


def test_an_item_that_netted_to_nil_is_still_reported():
    """Migration 363's rule: dropping nil lines is a display choice, and a
    report that silently omits rows cannot be tied to a control account by
    somebody who does not know which rows it dropped."""
    out = sa.compute([(META, [M("2026-01-01", 10, 10_000),
                              M("2026-02-01", -10, -10_000)])], AS_OF)
    assert len(out["items"]) == 1
    assert out["items"][0]["nothing_on_hand"] is True


# ═════════════════════════════════════════════════════════════════════════════
# AS AT A DATE
# ═════════════════════════════════════════════════════════════════════════════

def test_a_movement_after_the_date_is_not_in_the_answer():
    """The filter lives in the module, not on the caller: the SQL twin applies
    it in its own WHERE clause, so a Python half that trusted the caller would
    answer differently for the one caller that forgot."""
    rows = [
        {"service_catalogue_id": "i1", "movement_date": "2026-01-01",
         "quantity_delta": "10", "value_delta_paise": "10000", "id": "a"},
        {"service_catalogue_id": "i1", "movement_date": "2026-12-31",
         "quantity_delta": "90", "value_delta_paise": "90000", "id": "b"},
    ]
    out = sa.ageing(rows, "2026-09-18", {"i1": {"name": "W", "unit": "PCS"}})
    assert D(out["items"][0]["qty_units"]) == 10


def test_an_item_with_nothing_on_or_before_the_date_is_absent():
    rows = [{"service_catalogue_id": "i1", "movement_date": "2026-12-31",
             "quantity_delta": "90", "value_delta_paise": "90000", "id": "b"}]
    assert sa.ageing(rows, "2026-09-18", {})["items"] == []


def test_an_item_the_caller_could_not_name_is_kept():
    rows = [{"service_catalogue_id": "gone", "movement_date": "2026-01-01",
             "quantity_delta": "5", "value_delta_paise": "5000", "id": "a"}]
    out = sa.ageing(rows, "2026-09-18", {})
    assert out["items"][0]["name"] == "(deleted item)"


def test_the_answer_does_not_depend_on_the_order_the_rows_were_fetched_in():
    """Two receipts on one date written in one transaction share a created_at,
    so only the row id separates them.

    THE OBVIOUS CLAIM HERE IS WRONG AND THIS SAYS THE TRUE ONE. It is tempting
    to write "without the third sort key the layers come out in a different
    order and the answer changes" — it does not: two receipts sharing a
    movement_date share a BAND by construction, so whichever is consumed
    first, the band quantities and the pro-rated value are identical. A
    negative control that dropped the key passed, which is how this was found.

    What the key buys is DETERMINISM — the same answer whatever order the
    caller fetched the rows in — and that the SQL twin walks the same layers,
    so a later change that does make layer identity matter cannot make the two
    halves disagree quietly."""
    rows = [
        {"service_catalogue_id": "i1", "movement_date": "2024-01-01", "id": "b",
         "created_at": "2024-01-01T00:00:00+00:00",
         "quantity_delta": "10", "value_delta_paise": "90000"},
        {"service_catalogue_id": "i1", "movement_date": "2024-01-01", "id": "a",
         "created_at": "2024-01-01T00:00:00+00:00",
         "quantity_delta": "10", "value_delta_paise": "10000"},
        {"service_catalogue_id": "i1", "movement_date": "2026-09-01", "id": "c",
         "created_at": "2026-09-01T00:00:00+00:00",
         "quantity_delta": "-15", "value_delta_paise": "-50000"},
    ]
    out = sa.ageing(rows, "2026-09-18", {"i1": {"name": "W", "unit": "PCS"}})
    # Whichever order it picks it must be STABLE and must foot; the parity test
    # is what proves the SQL picks the same one.
    row = out["items"][0]
    assert D(row["qty_units"]) == 5
    assert sum(row["band_value_paise"].values()) == row["value_paise"]
    again = sa.ageing(list(reversed(rows)), "2026-09-18",
                      {"i1": {"name": "W", "unit": "PCS"}})
    assert again["items"][0] == row, (
        "the answer must not depend on the order the caller fetched the rows in")


# ═════════════════════════════════════════════════════════════════════════════
# WHAT IT REFUSES
# ═════════════════════════════════════════════════════════════════════════════

def _code_only(mod) -> str:
    """The code, not the prose. Both modules EXPLAIN these rules at length, so
    a substring scan fails on the sentence stating the very rule it checks."""
    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _reads(mod) -> set[str]:
    """Everything the module actually READS: identifiers, attributes, keyword
    arguments, and the string keys it pulls out of a row.

    WORD-ABSENCE IS NOT THE RULE, and this file learned it twice. The module
    carries its four caveats as module-level STRINGS — they are code, not
    docstrings, so stripping docstrings does not remove them — and those
    sentences name the very things the guard forbids: "about the godown",
    "no provision or write-down percentage is applied". A scan for the WORD
    fails on the sentence stating the rule it is checking.

    So the rule is stated as what the code reaches for. A caveat mentioning a
    godown is prose; `r.get("godown_id")` is a read, and only the second is
    what "nothing is bucketed by godown" is about.
    """
    tree = ast.parse(inspect.getsource(mod))
    # A MODULE-LEVEL NAME BOUND TO A STRING IS A CAVEAT, and a caveat is prose
    # wearing an identifier. `NO_PROVISION_IS_COMPUTED` is the module REFUSING
    # to compute a provision, and a guard that reads its own refusal's name as
    # a violation is the same mistake one level up — which is exactly what
    # happened the first time this was written.
    prose = {
        t.id
        for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id in prose:
                continue
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            out.add(node.arg)
        elif isinstance(node, ast.Call):
            # A field read off a row: `r.get("godown_id")`, `r["batch_id"]`.
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in ("get", "pop"):
                for a in node.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        out.add(a.value)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                out.add(node.slice.value)
    return out


def test_no_provision_is_computed_anywhere():
    """AS-2 paragraph 21 makes net realisable value an estimate of selling
    price less the costs to complete and sell — a fact about the market no
    ledger holds. A 25%-at-a-year sliding scale is a policy some firms run and
    no standard states, and putting one here would produce a write-down figure
    that looks computed.

    Asserted TWO ways, because either alone is weak: no name in the module
    reaches for a provision, and no arithmetic anywhere multiplies by a
    fraction. The second is what a sliding scale would actually be."""
    names = _reads(sa)
    for forbidden in ("provision", "writedown", "write_down", "nrv",
                      "net_realisable_value", "obsolescence_rate"):
        assert not any(forbidden in n.lower() for n in names), (
            f"stock_ageing reads {forbidden}: the quantities are the report "
            f"and the write-down is the CA's")

    tree = ast.parse(inspect.getsource(sa))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            raise AssertionError(
                f"stock_ageing holds the float {node.value}: a provision rate "
                f"is a policy no standard states, and every figure here is "
                f"integer paise or a Decimal quantity")
    assert len(names) > 40, "the scan must have something to look at"


def test_the_ageing_never_reads_the_costing_policy():
    """AGEING IS FIFO WHATEVER THE COST FORMULA IS. AS-2 paragraph 14's choice
    governs what an issue is VALUED at, not which carton was carried out, so a
    weighted-average client's ageing is the same physical answer."""
    names = _reads(sa)
    for forbidden in ("inventory_costing_method", "CostingPolicy", "costing"):
        assert forbidden not in names


def test_the_costing_engine_never_learns_about_the_bands():
    """The other direction. A band leaking into costing would make specific
    identification (AS-2 paragraph 13) a third cost formula by accident."""
    from domain.inventory import costing
    names = _reads(costing)
    assert "stock_ageing" not in names
    assert "d365_plus" not in names
    assert len(names) > 40


def test_nothing_is_bucketed_by_godown_or_batch():
    """Both are on the ledger since migration 398 and neither is what the
    obsolescence question turns on; `domain/inventory/batches.py` already ages
    by EXPIRY, which is the other question and a different one.

    On what the module READS, not on the word: its own caveat says the ageing
    is "about the godown"."""
    names = _reads(sa)
    for forbidden in ("godown_id", "godown_name", "batch_id", "batch_no",
                      "expiry_date"):
        assert forbidden not in names
    # And no FIELD of the row shape names one either.
    assert not any(n.lower().startswith(("godown", "batch", "expiry"))
                   for n in names)


def test_the_caveats_travel_on_every_answer():
    out = sa.compute([], AS_OF)
    assert len(out["notes"]) == 4
    joined = " ".join(out["notes"])
    assert "convention" in joined            # the bands are not prescribed
    assert "first-in-first-out" in joined    # whatever the cost formula is
    assert "proportion to quantity" in joined
    assert "net realisable value" in joined


def test_no_caveat_states_a_rate_or_an_amount():
    """The `table_4a_gaps` discipline: a sentence explaining why something is
    not computed must not quietly compute it."""
    import re
    for note in sa.compute([], AS_OF)["notes"]:
        assert not re.search(r"\d+\s*%", note)
        assert "₹" not in note
