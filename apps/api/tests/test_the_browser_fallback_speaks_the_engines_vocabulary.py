"""The browser's Schedule III fallback may only say what the engine can hear.

WHAT THIS GUARDS, AND WHY IT IS WRITTEN IN PYTHON

`apps/web/lib/accounting/scheduleIiiCaptions.ts` classifies an account into a
Schedule III caption in the browser. It exists as a FALLBACK — for the window
where the frontend has redeployed ahead of the backend — and a fallback that
returns a caption the engine does not know is not a fallback. It is the drift it
was meant to cover for, presented to a CA as a statement line.

That is not hypothetical. Until 11-09-2026 the module returned `Tangible
Assets`, `Intangible Assets` and `Non-Current Investments` where
domain/reporting/schedule_iii.py says `Tangible Fixed Assets`, `Intangible Fixed
Assets` and `Long-term Investments`; it returned `Employee Benefit Expense`
(singular) for the plural the engine uses; and it had a `Tax Liabilities` that
appears nowhere in Schedule III, nowhere in the engine, and nowhere in any other
statement this product produces.

The Balance Sheet tab grouped by that function rather than by the caption the
API already sent, so the drift was live. Measured against production the same
day: **13 of the 26 mapped balance-sheet accounts** were presented under a
different caption than the year-end statements gave them.

The test lives HERE rather than in apps/web because this package owns the
vocabulary. A guard written on the other side would be asserting the engine
against a copy of itself, and would pass whenever both drifted together —
exactly what happened with the mapping screen's hardcoded list.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from domain.reporting.schedule_iii import (
    BALANCE_SHEET_CAPTIONS, CAPTION_ALIASES, CAPTIONS, PROFIT_LOSS_CAPTIONS)

MODULE = (pathlib.Path(__file__).resolve().parents[3]
          / "apps" / "web" / "lib" / "accounting" / "scheduleIiiCaptions.ts")


@pytest.fixture(scope="module")
def source() -> str:
    assert MODULE.exists(), f"{MODULE} has moved — update this guard, do not delete it"
    return MODULE.read_text(encoding="utf-8")


def _returned_captions(src: str) -> set[str]:
    """Every string the two classifiers can hand back.

    `return "..."` is the only shape either function uses, which is checked
    below so a rewrite into some other form fails here rather than silently
    stopping the scan.
    """
    return set(re.findall(r'return\s+"([^"]+)"\s*;', _strip_line_comments(src)))


def _strip_line_comments(text: str) -> str:
    """Drop `//` comments before reading string literals out of a block.

    Found by this file's own first run: the comment explaining why
    "Tax Liabilities" was REMOVED from BS_LIAB_ORDER quotes the caption, and a
    naive scan read the explanation as an entry. A guard that fails on a comment
    is a guard nobody trusts the next time it fires.
    """
    return re.sub(r"//[^\n]*", "", text)


def _order_array(src: str, name: str) -> list[str]:
    body = re.search(rf"export const {name} = \[(.*?)\];", src, re.S)
    assert body, f"{name} not found — the guard cannot check what it cannot read"
    return re.findall(r'"([^"]+)"', _strip_line_comments(body.group(1)))


# ── the scan has to keep working ────────────────────────────────────────────

def test_the_classifiers_still_return_string_literals(source):
    """A guard that stops matching keeps passing while checking nothing, which
    is the main way a check like this rots."""
    found = _returned_captions(source)
    assert len(found) >= 15, (
        f"only {len(found)} captions found in {MODULE.name} — the parser has "
        "probably stopped matching, not the file stopped classifying")


# ── the rule ────────────────────────────────────────────────────────────────

def test_every_caption_the_browser_can_return_is_one_the_engine_knows(source):
    invented = sorted(_returned_captions(source) - set(CAPTIONS) - {"Other"})
    assert not invented, (
        f"{MODULE.name} can return {invented}, which domain/reporting/"
        f"schedule_iii.py does not present. A caption the engine cannot hear is "
        f"a statement line no other report in this product shows.")


def test_the_browser_does_not_return_a_caption_by_its_old_spelling(source):
    """CAPTION_ALIASES exists so STORED data written before a rename still
    resolves. A classifier RETURNING an old spelling is a different thing: it is
    writing new drift, and the alias table would quietly absorb it."""
    stale = sorted(_returned_captions(source) & set(CAPTION_ALIASES))
    assert not stale, (
        f"{MODULE.name} returns {stale}, which are aliases of a current caption "
        f"rather than the caption. Aliases are for data already stored.")


@pytest.mark.parametrize("array,allowed", [
    ("BS_ASSET_ORDER", BALANCE_SHEET_CAPTIONS),
    ("BS_LIAB_ORDER", BALANCE_SHEET_CAPTIONS),
    ("BS_EQ_ORDER", BALANCE_SHEET_CAPTIONS),
    ("PL_REV_ORDER", PROFIT_LOSS_CAPTIONS),
    ("PL_EXP_ORDER", PROFIT_LOSS_CAPTIONS),
])
def test_every_ordering_entry_is_a_caption_the_engine_presents(source, array, allowed):
    """An ORDER array is what the statement's shape is built from. An entry the
    engine never emits is a heading that can never have a line under it."""
    unknown = sorted(set(_order_array(source, array)) - set(allowed))
    assert not unknown, f"{array} lists {unknown}, which the engine does not present"


def test_the_balance_sheet_arrays_between_them_cover_every_balance_sheet_caption(source):
    """The other direction, and the one that loses a real balance.

    A caption the engine emits and no array lists renders in the screens'
    "extra" group — visible, but outside the statement's shape. `Deferred Tax
    Liability` sat there until 11-09-2026.
    """
    listed = set(_order_array(source, "BS_ASSET_ORDER")) \
        | set(_order_array(source, "BS_LIAB_ORDER")) \
        | set(_order_array(source, "BS_EQ_ORDER"))
    missing = sorted(set(BALANCE_SHEET_CAPTIONS) - listed)
    assert not missing, (
        f"the engine presents {missing} and no BS_*_ORDER array lists it, so it "
        f"renders outside the statement's shape")


def test_tax_expense_is_the_one_p_and_l_caption_left_out_on_purpose(source):
    """The exception, pinned so it is not "tidied" back in — which nearly
    happened on 11-09-2026.

    Schedule III Part II presents tax BELOW profit before tax, and the client
    accounting P&L tab has no below-the-line row. Listing Tax Expense among the
    operating expenses would fold it into total expenses, which is a worse
    presentation than the extra-bucket fallback that renders it separately.
    """
    listed = set(_order_array(source, "PL_REV_ORDER")) \
        | set(_order_array(source, "PL_EXP_ORDER"))
    assert sorted(set(PROFIT_LOSS_CAPTIONS) - listed) == ["Tax Expense"]


# ── and the screen must only ever use it AS a fallback ──────────────────────
#
# Speaking the right vocabulary is half of it. The other half is not being
# asked: the Balance Sheet tab called bsBucket() as its PRIMARY source and threw
# the server's caption away in fromSection, so the account's own
# schedule_iii_mapping — the CA's explicit choice — never reached the screen at
# all. The P&L tab had already been fixed the right way; the Balance Sheet was
# never converted with it.

PAGE = (pathlib.Path(__file__).resolve().parents[3] / "apps" / "web" / "app"
        / "clients" / "[id]" / "accounting" / "page.tsx")


@pytest.fixture(scope="module")
def page() -> str:
    assert PAGE.exists(), f"{PAGE} has moved — update this guard, do not delete it"
    return PAGE.read_text(encoding="utf-8")


def test_the_balance_sheet_carries_the_servers_caption_onto_its_rows(page):
    """`fromSection` maps the API's balance-sheet lines into the row type the
    screen groups. It used to stop at account_subtype, which is how a field the
    backend had always sent was fetched and dropped."""
    body = re.search(r"const fromSection = .*?\}\)\)\);", page, re.S)
    assert body, "fromSection not found — the guard cannot check what it cannot read"
    assert "schedule_iii_caption" in body.group(0), (
        "the Balance Sheet drops the server's Schedule III caption when mapping "
        "API rows, so grouping falls back to guessing from the subtype — which "
        "cannot see the account's schedule_iii_mapping")


@pytest.mark.parametrize("fn", ["bsBucket", "plBucket"])
def test_the_browser_classifier_is_only_ever_reached_through_a_fallback(page, fn):
    """Every call is `<server caption> ?? fn(...)`, never `fn(...)` alone.

    Stated as the RULE rather than as a list of call sites: a new statement tab
    added later has to go through the same shape, and there is no line number
    here to go stale.
    """
    src = _strip_line_comments(page)
    bare = [m.start() for m in re.finditer(rf"\b{fn}\s*\(", src)
            if not re.search(r"\?\?\s*$", src[max(0, m.start() - 40):m.start()])]
    assert not bare, (
        f"{fn}() is called {len(bare)} time(s) as a primary source in "
        f"{PAGE.name}. It is a fallback for the window where the frontend has "
        f"redeployed ahead of the backend — used on its own it silently "
        f"discards the CA's own schedule_iii_mapping.")
