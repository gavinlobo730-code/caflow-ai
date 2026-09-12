"""Four defects in the fixed-asset register, from the 12 September probe pass.

They are unrelated in subject and share one shape: the register answered
CONFIDENTLY with something it had not actually worked out.

  FA-12  Five reads of `fixed_assets` were bare `.execute()` calls, capped at
         PostgREST's ~1000 rows with no error and no flag. The worst was
         `run_depreciation`, added by the FA-04 fix: above a thousand assets a
         "run the year" depreciated the first thousand and reported
         `assets_considered` as a thousand — a month-end that looks finished
         and is two-thirds done. A sixth read paged, through a LOCAL copy of a
         helper the codebase already keeps in one place.

  FA-13  A reducing balance approaches its floor and never reaches it, so a
         WDV asset with the default salvage of zero was charged for ever.
         FA-02's correct Schedule II rates sharpened it: a derived rate lands
         the asset exactly on its residual at the end of its life, so the
         overshoot begins precisely when the asset is fully depreciated.

  FA-14  `data.useful_life_years or default` cannot tell an unstated life from
         a typed zero, so a CA who entered 0 silently got the category default.

  FA-17  `FixedAssetIn` had no `asset_code`, so the box the form has always
         shown was dropped by Pydantic and overwritten by the generated
         `FA-nnnn`. The client's own asset tag — the number stencilled on the
         machine, which a physical verification is carried out against — never
         reached the register.
"""
from __future__ import annotations

import inspect
import math
import re
from decimal import Decimal
from pathlib import Path

import pydantic
import pytest

import routers.fixed_assets as fa
from models.accounting import FixedAssetIn, FixedAssetUpdateIn

API_ROOT = Path(__file__).resolve().parents[1]


def _asset(**kw) -> dict:
    base = {
        "purchase_cost_paise": 100_000_00,
        "salvage_value_paise": 0,
        "wdv_rate_percent": 63.16,
        "depreciation_method": "WDV",
        "asset_category": "Computer & IT Equipment",
        "useful_life_years": 3,
        "accumulated_depreciation_paise": 0,
        "asset_code": "FA-0001",
        "asset_name": "Laptop",
        "is_disposed": False,
    }
    base.update(kw)
    return base


def _walk(asset: dict, years: int) -> list[int]:
    """The yearly charges this asset would actually take, in order."""
    charges, accum = [], int(asset.get("accumulated_depreciation_paise") or 0)
    for _ in range(years):
        row = {**asset, "accumulated_depreciation_paise": accum}
        c = fa._compute_annual_depreciation(row)
        charges.append(c)
        accum += c
    return charges


# ═══════════════════════════════════════════════════════════════════════════
# FA-13 — the charge has a stopping point, derived from the row's own numbers
# ═══════════════════════════════════════════════════════════════════════════

def test_a_wdv_asset_stops_at_the_end_of_its_useful_life():
    """The probe's worked example. A three-year ₹1,00,000 computer at the
    derived 63.16% reaches ₹5,000 — Part C Note 5's 5% residual — after three
    years, and used to be charged ₹3,158 in year four and to keep going."""
    charges = _walk(_asset(), 6)
    assert charges[0] > 0 and charges[1] > 0 and charges[2] > 0
    assert charges[3:] == [0, 0, 0], (
        f"the asset is still being depreciated after its useful life: {charges}")
    closing = 100_000_00 - sum(charges)
    assert 4_900_00 <= closing <= 5_100_00, (
        f"should settle at about 5% of cost; settled at {closing}")


def test_year_four_is_nil_and_not_one_paisa():
    """The floor is the same CHAIN the charges run, not the closed form
    `cost × (1 − rate/100) ^ life`.

    Every year's charge is floored to the paise, so the balance the asset
    actually reaches is a little above the smooth curve. Using the closed form
    leaves the asset one paisa above its own floor and takes a ₹0.01 charge in
    year four — a journal entry, in a period after the asset was finished, for
    a rounding difference.
    """
    rate = Decimal("63.16")
    chain = fa._wdv_residual_at_end_of_life(_asset(), rate)
    closed_form = int(Decimal(100_000_00) * (Decimal(1) - rate / 100) ** 3)
    assert chain > closed_form, (
        "the flooring makes the real balance HIGHER than the smooth curve; if "
        "these are equal the floor is no longer derived from the same chain")
    assert _walk(_asset(), 4)[3] == 0


def test_a_row_with_no_useful_life_is_unchanged():
    """Every WDV row in the register today may have no life recorded. The floor
    needs one, so those rows keep exactly the behaviour they have — the CA's
    salvage and nothing else. `register-integrity` names them instead."""
    no_life = _asset(useful_life_years=None)
    assert fa._wdv_residual_at_end_of_life(no_life, Decimal("63.16")) == 0
    charges = _walk(no_life, 6)
    assert all(c > 0 for c in charges), (
        "changing these rows silently is what the fix must not do")


def test_a_salvage_the_ca_recorded_wins_where_it_is_higher():
    """Part C Note 5 caps the residual at 5%; it does not require it. A CA who
    recorded ₹20,000 on a ₹1,00,000 asset has made a judgement, and the derived
    floor must not depreciate through it."""
    charges = _walk(_asset(salvage_value_paise=20_000_00), 6)
    closing = 100_000_00 - sum(charges)
    assert closing == 20_000_00, closing


def test_a_zero_rate_charges_nothing_and_the_floor_says_so():
    assert fa._wdv_residual_at_end_of_life(_asset(), Decimal("0")) == 100_000_00
    assert _walk(_asset(wdv_rate_percent=0), 3) == [0, 0, 0]


def test_a_hundred_percent_rate_leaves_no_residual_to_protect():
    assert fa._wdv_residual_at_end_of_life(_asset(), Decimal("100")) == 0


def test_straight_line_is_untouched():
    """SL divides by the life, so it already terminates. The floor must not
    reach it — an SL asset's terminal is the stored salvage and always was.

    Asserted as "the same arithmetic it always did", including the trailing
    paisa: ₹1,00,000 over three years floors to ₹33,333.33 a year, three of
    which leave one paisa that falls into a fourth charge. That tail is
    pre-existing, is not what FA-13 is about — which is a charge with no
    terminal at all, not a rounding remainder — and moving it into year three
    would change the final-year charge on every SL asset in the register. That
    is exactly the "changes what is already recorded" hazard the probe pass
    warned about, so it stays and is written down instead.
    """
    charges = _walk(_asset(depreciation_method="SL", wdv_rate_percent=None), 5)
    assert sum(charges) == 100_000_00, charges
    assert charges[:3] == [math.floor(100_000_00 / 3)] * 3, charges
    assert charges[3] == 100_000_00 - 3 * math.floor(100_000_00 / 3)
    assert charges[4] == 0


def test_the_floor_is_not_a_five_percent_constant():
    """Derived from the row's OWN rate and life. An asset whose CA recorded a
    rate that is not the Schedule II derived one gets ITS residual, not 5% of
    cost from a different asset's arithmetic."""
    got = fa._wdv_residual_at_end_of_life(
        _asset(useful_life_years=5), Decimal("40.00"))
    assert got != 5_000_00
    expected = 100_000_00
    for _ in range(5):
        expected -= math.floor(Decimal(expected) * Decimal("40.00") / 100)
    assert got == expected


# ── and the rows the floor cannot reach are NAMED ───────────────────────────

def test_a_wdv_row_with_no_life_and_no_salvage_is_reported():
    f = fa._wdv_with_no_stopping_point(_asset(useful_life_years=None))
    assert f and f["kind"] == "wdv_asset_has_no_stopping_point"
    assert "3" in f["what_it_means"], (
        "the sentence must name the Part C lives, or the CA has to go and look "
        "them up to act on it")
    assert f["prescribed_useful_life_years"] == [3, 6]


@pytest.mark.parametrize("why,row", [
    ("a life is recorded",        {}),
    ("a salvage is recorded",     {"useful_life_years": None,
                                   "salvage_value_paise": 1}),
    ("straight line terminates",  {"useful_life_years": None,
                                   "depreciation_method": "SL"}),
    ("land is never depreciated", {"useful_life_years": None,
                                   "asset_category": "Land"}),
    ("no Part C class to cite",   {"useful_life_years": None,
                                   "asset_category": "Other"}),
    ("nothing is being charged",  {"useful_life_years": None,
                                   "wdv_rate_percent": 0}),
    ("already fully written off", {"useful_life_years": None,
                                   "accumulated_depreciation_paise": 100_000_00}),
])
def test_the_no_stopping_point_check_does_not_cry_wolf(why, row):
    assert fa._wdv_with_no_stopping_point(_asset(**row)) is None, why


def test_a_disposed_asset_is_not_reported():
    """Its basis is settled — the gain or loss was computed from it — so a
    finding there is noise the CA cannot act on. Same rule as FA-02's.

    Behavioural since FA-20 moved the rule into
    `domain/fixed_assets/integrity.py`. It used to scan the endpoint's source
    for the guard clause, which could not tell a guard that is present from a
    guard that is correct.
    """
    from domain.fixed_assets import integrity

    no_terminal = _asset(useful_life_years=None, journal_entry_id="j1", id="a1")
    kinds = {f["kind"] for f in integrity.register_findings(
        [no_terminal], live_bill_ids=set())}
    assert "wdv_asset_has_no_stopping_point" in kinds
    assert integrity.register_findings(
        [{**no_terminal, "is_disposed": True}], live_bill_ids=set()) == []


# ═══════════════════════════════════════════════════════════════════════════
# FA-14 — a life of zero is refused, not swallowed
# ═══════════════════════════════════════════════════════════════════════════

_CREATE = dict(client_id="c1", asset_name="Lathe", purchase_date="2026-04-01",
               purchase_cost_paise=100_000_00)


@pytest.mark.parametrize("model,extra", [(FixedAssetIn, _CREATE),
                                         (FixedAssetUpdateIn, {})])
@pytest.mark.parametrize("life", [0, -1, -12])
def test_a_life_below_one_year_is_refused_at_every_door(model, extra, life):
    """A validator only on the create door is one PATCH away from being none,
    and the life is a tier-C field — exactly the one a CA revises later under
    Schedule II Part C Note 7."""
    with pytest.raises(pydantic.ValidationError):
        model(**extra, useful_life_years=life)


@pytest.mark.parametrize("model,extra", [(FixedAssetIn, _CREATE),
                                         (FixedAssetUpdateIn, {})])
@pytest.mark.parametrize("life", [None, 1, 3, 60])
def test_a_real_life_and_an_unstated_one_are_both_fine(model, extra, life):
    assert model(**extra, useful_life_years=life).useful_life_years == life


def test_the_refusal_says_what_to_do_instead():
    with pytest.raises(pydantic.ValidationError) as e:
        FixedAssetIn(**_CREATE, useful_life_years=0)
    msg = str(e.value)
    assert "Land" in msg or "0.00" in msg, (
        "a refusal that does not say how to record a non-depreciable asset "
        "just moves the CA's problem")


def test_a_stored_zero_still_computes_rather_than_dividing_by_zero():
    """The compute-time `or` stays DELIBERATELY. The door refuses a 0 now, but
    rows written before it — or straight over PostgREST, which the browser does
    — can still carry one, and `is None` there divides `cost - salvage` by zero
    and answers a 500 instead of a charge."""
    charge = fa._compute_annual_depreciation(
        _asset(depreciation_method="SL", useful_life_years=0,
               wdv_rate_percent=None))
    assert charge > 0
    # 3 years is the category default the `or` falls through to.
    assert charge == math.floor(100_000_00 / 3)


# ═══════════════════════════════════════════════════════════════════════════
# FA-17 — the client's own asset tag reaches the register
# ═══════════════════════════════════════════════════════════════════════════

def test_the_field_exists_at_all():
    """It did not, which is the whole defect: Pydantic drops an unknown key
    without complaint, so the form's box was posted and discarded in silence."""
    assert "asset_code" in FixedAssetIn.model_fields
    assert FixedAssetIn(**_CREATE, asset_code="PLANT/2026/17").asset_code == \
        "PLANT/2026/17"


@pytest.mark.parametrize("typed", ["FA-0500", "fa-0500", "Fa-1", "FA-00000001"])
def test_a_code_in_the_generated_shape_is_refused(typed):
    """`sequence_after` hands out the next `FA-{n:04d}` as max+1 over anything
    starting `FA-` with an all-digit tail. A typed FA-0500 leaves 500 numbers
    that can never be issued; a typed FA-0001 collides with the row that
    already has it — and `asset_code` is what every FA-* journal reference is
    built from, where a collision does not raise but silently lands the second
    asset's acquisition on the first asset's entry.

    Case-insensitive: `fa-0500` reads as the same tag to a human and is a
    different row to a unique index.
    """
    with pytest.raises(pydantic.ValidationError):
        FixedAssetIn(**_CREATE, asset_code=typed)


@pytest.mark.parametrize("typed", ["PLANT/2026/17", "MC-17", "A.1", "FA-ACQ-1",
                                   "FAX-0500", "FA-12A"])
def test_a_real_asset_tag_is_accepted(typed):
    """The other half of the rule, and the half that gets forgotten: a
    validator that also blocks what a CA legitimately types gets reverted."""
    assert FixedAssetIn(**_CREATE, asset_code=typed).asset_code == typed


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_box_is_not_stated_and_takes_the_generated_code(blank):
    assert FixedAssetIn(**_CREATE, asset_code=blank).asset_code is None


@pytest.mark.parametrize("bad", ["X" * 33, "has space", "-leading", "semi;colon"])
def test_a_code_a_journal_reference_could_not_carry_is_refused(bad):
    with pytest.raises(pydantic.ValidationError):
        FixedAssetIn(**_CREATE, asset_code=bad)


def test_the_router_uses_the_typed_code_and_generates_only_without_one():
    src = inspect.getsource(fa.create_asset)
    assert 'asset_code = data.asset_code or "FA-{:04d}".format(' in src, (
        "the generated code must be the FALLBACK, not the answer")
    clash = src[src.index("if data.asset_code:"):src.index("asset_code = data.asset_code")]
    assert '.eq("asset_code", data.asset_code)' in clash
    assert 'status_code=409' in clash
    assert 'deleted_at' not in clash, (
        "migration 351's index is not partial on deleted_at — a soft-deleted "
        "row keeps its code because the FA-* references are built from it, so "
        "this read must not filter one out and promise a code the index will "
        "then refuse")


def test_the_code_cannot_be_edited_afterwards():
    """Renaming an asset after a posting orphans every journal reference
    already written. Recorded as immutable rather than simply absent, so the
    creatable-is-correctable guard states the reason."""
    from tests.test_a_field_you_can_create_is_a_field_you_can_correct import (
        IMMUTABLE_ON_UPDATE)
    assert "asset_code" not in FixedAssetUpdateIn.model_fields
    reason = IMMUTABLE_ON_UPDATE[("FixedAssetUpdateIn", "asset_code")]
    assert "FA-ACQ" in reason and "FA-DEPN" in reason


# ═══════════════════════════════════════════════════════════════════════════
# FA-12 — every read of the register reads all of it, through ONE helper
# ═══════════════════════════════════════════════════════════════════════════

READERS = {
    "routers/fixed_assets.py": ["list_assets", "run_depreciation",
                                "depreciation_schedule", "register_integrity"],
    "routers/year_end_notes.py": ["_compute_fixed_assets_note_data",
                                  "_compute_accounting_policies_data"],
}


def test_every_read_of_the_register_pages():
    import routers.year_end_notes as yen
    modules = {"routers/fixed_assets.py": fa, "routers/year_end_notes.py": yen}
    for path, fns in READERS.items():
        for fn in fns:
            body = inspect.getsource(getattr(modules[path], fn))
            if 'table("fixed_assets")' not in body:
                continue
            assert "fetch_all(" in body, (
                f"{path}::{fn} reads fixed_assets with a bare execute() — it is "
                f"capped at ~1000 rows and reports nothing when it is")


def test_there_is_no_second_paginator_in_the_router():
    """It had a local copy whose own docstring said the other reads had the
    same gap. Two implementations of one helper in one repo is how they
    diverge; this one had already lost `fetch_all`'s page cap and its
    cursor-missing log."""
    src = (API_ROOT / "routers" / "fixed_assets.py").read_text()
    assert "def _paginate_all" not in src
    assert "from core.db_paging import fetch_all" in src


def test_the_shared_helper_is_inside_the_cursor_column_guard():
    """`test_paginated_selects_carry_their_key` scanned only the PRIVATE
    copies, so a call site moving to the shared helper moved out of the rule at
    the same time."""
    from tests.test_paginated_selects_carry_their_key import PAGINATORS
    assert "fetch_all" in PAGINATORS


@pytest.mark.parametrize("fn,column", [("list_assets", "purchase_date"),
                                       ("run_depreciation", "asset_code")])
def test_an_order_the_query_carried_moves_after_the_walk(fn, column):
    """`fetch_all` imposes its own ORDER BY id — a cursor cannot page one order
    while sorting by another — so an ordering the endpoint wants has to be
    applied to the rows it got back."""
    body = inspect.getsource(getattr(fa, fn))
    assert f'.order("{column}"' not in body, (
        f"{fn} still sorts inside the paged query; the keyset walk will not "
        f"honour it and may repeat or drop rows at a page boundary")
    assert f'assets.sort(key=' in body and column in body


def test_the_run_depreciation_sort_survives_a_null_asset_code():
    """`asset_code` is NULLABLE (migration 054 added it as plain TEXT), and
    `sorted` raises TypeError comparing None with str. The previous ORDER BY
    was the database's, which sorts NULLs happily."""
    body = inspect.getsource(fa.run_depreciation)
    assert 'str(a.get("asset_code") or "")' in body
    rows = [{"asset_code": None, "id": "b"}, {"asset_code": "FA-0001", "id": "a"}]
    rows.sort(key=lambda a: (str(a.get("asset_code") or ""), str(a.get("id") or "")))
    assert [r["id"] for r in rows] == ["b", "a"]


# ── and the walk actually walks: 2,500 assets, not 1,000 ────────────────────

class _PagedResp:
    def __init__(self, data):
        self.data = data


class _PagedQuery:
    """Enough of a PostgREST builder to page over, INCLUDING the ~1000-row cap.

    The cap is the point. A double that returns everything from one
    `.execute()` cannot tell a paged read from an unpaged one, so it would have
    passed against the bug this test exists for.
    """
    DB_MAX_ROWS = 1000

    def __init__(self, rows):
        self._rows, self._eq, self._gt = rows, [], None
        self._order, self._desc, self._limit = None, False, None

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._eq.append((k, v))
        return self

    def is_(self, col, _null="null"):
        self._eq.append((col, None))
        return self

    def gt(self, col, value):
        self._gt = (col, value)
        return self

    def order(self, col, desc=False):
        self._order, self._desc = col, desc
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = [r for r in self._rows
                if all(r.get(k) == v for k, v in self._eq)]
        if self._gt:
            col, value = self._gt
            rows = [r for r in rows if str(r.get(col)) > str(value)]
        if self._order:
            rows.sort(key=lambda r: str(r.get(self._order) or ""), reverse=self._desc)
        cap = min(self._limit or self.DB_MAX_ROWS, self.DB_MAX_ROWS)
        return _PagedResp(rows[:cap])


class _PagedDB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _PagedQuery(self._rows)


def test_a_register_of_2500_assets_is_read_whole(monkeypatch):
    """`run_depreciation` was the worst of the five: above a thousand assets a
    "run the year" depreciated the first thousand and reported
    `assets_considered` as a thousand."""
    rows = [{"id": f"{i:06d}", "firm_id": "f1", "client_id": "c1",
             "deleted_at": None, "is_disposed": False,
             "purchase_date": f"2025-{(i % 12) + 1:02d}-01",
             "purchase_cost_paise": 1_000_00,
             "accumulated_depreciation_paise": 0,
             "asset_code": f"TAG-{i:06d}", "asset_name": f"Asset {i}"}
            for i in range(2500)]
    monkeypatch.setattr(fa, "_db", lambda: _PagedDB(rows))
    resp = fa.list_assets(client_id="c1", include_disposed=True,
                          current_user={"id": "u1", "firm_id": "f1",
                                        "role": "Partner",
                                        "auth_user_id": "a1", "email": "a@b.c"})
    got = resp["data"]
    assert len(got) == 2500, f"read {len(got)} of 2500 — the walk stopped short"
    dates = [a["purchase_date"] for a in got]
    assert dates == sorted(dates, reverse=True), (
        "the newest-first order the grid wants must survive the walk")


def test_the_double_would_have_caught_the_bug_it_is_written_for(monkeypatch):
    """Guard on the guard: an unpaged read against this double returns exactly
    a thousand rows and raises nothing, which is what production does."""
    rows = [{"id": f"{i:06d}", "firm_id": "f1", "client_id": "c1"}
            for i in range(2500)]
    unpaged = _PagedDB(rows).table("fixed_assets").select("*") \
        .eq("firm_id", "f1").execute().data
    assert len(unpaged) == 1000
