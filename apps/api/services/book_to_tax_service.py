"""Fetching the book-to-tax bridge's inputs, so a CA does not re-key them.

WHY THIS EXISTS (FA-06 ≡ IT-09)

    `domain/income_tax/book_to_tax_bridge.py` has been complete since it was
    written, `POST /api/income-tax/book-to-tax-bridge` has served it, and
    `grep -rn "book-to-tax\\|bookToTax" apps/web` returned TWO COMMENTS AND NO
    CALLER. So a CA could compute §32 block depreciation and record it, and
    there was nowhere in the product showing profit per the accounts reconciled
    down to taxable income — the one document the client actually reads and an
    assessing officer asks for.

    The bridge module's own docstring names the reason its inputs were typed:
    "Book profit was taken as an INPUT by the minimum-tax engine PRECISELY
    BECAUSE NOTHING DERIVED IT."

    Something does now. Three of the four inputs are figures these books
    already hold, and a screen that asks a CA to type them is the defect
    `/accounting/msme-tracker` had before PUR-15 and the 2B reconciliation had
    before GST-04: the number drifts from the ledger the moment anything is
    corrected, and nobody can tell which of the two is right.

WHAT IS DERIVED, AND WHAT IS NOT

    book profit          the P&L's own `net_profit_paise` for the year, through
                         the SAME `ReportingService` the Profit & Loss screen
                         renders — so the bridge opens on the figure the client
                         has already seen, not a second opinion about it.
    depreciation (books) `fixed_asset_movement.posted_depreciation_paise`,
                         which reads what was actually POSTED to the ledger.
                         Imported rather than restated: FA-05 records why this
                         must be the ledger's figure and not the register's
                         theoretical charge, and two readers of one fact is how
                         they come to disagree.
    §43B(h)              `msme_43bh_service.for_financial_year`'s own
                         `disallowed_paise`. Its rule is elaborate (fifteen
                         days, the written agreement, the forty-five day cap,
                         the goods receipt) and re-deciding any of it here
                         would be a second §43B(h).
    §32                  fetched by the ROUTER, unchanged, and deliberately not
                         moved here — `section_32_service.assemble` already
                         does it and its `is_complete` gate is what stops the
                         bridge footing on an assumption.

    BROUGHT-FORWARD LOSSES ARE NOT DERIVED. `loss_set_off` needs the head-wise
    split of this year's income to decide what a brought-forward loss may
    reach, and the bridge holds one number for the whole computation. Deriving
    a set-off from a single figure would claim a head-wise answer this module
    cannot see, so it stays the caller's — NAMED, so a nil reads as "nobody
    said" rather than "there were none".

EVERY DERIVED FIGURE SAYS WHERE IT CAME FROM, AND A CALLER'S VALUE WINS

    `resolve_inputs` returns the figure AND its provenance sentence, and a
    value the caller supplied is never overwritten — the `domain/tds/deductor`
    shape. A CA's own book profit may legitimately differ from this ledger's:
    they may be bridging a client whose accounts were prepared elsewhere, and
    refusing that would make the screen useless for exactly the clients whose
    bridge is hardest.

    A figure that could NOT be derived comes back as None with a sentence, and
    the router passes 0 with the sentence carried into the bridge's reasons.
    None and zero are different facts and the difference is the whole point:
    zero depreciation in the accounts and depreciation that could not be read
    are not the same bridge.
"""
from __future__ import annotations

import logging
from typing import Optional

from domain.reporting import fixed_asset_movement as _mv

_logger = logging.getLogger("caflow.book_to_tax")


class DerivedInput:
    """One figure, where it came from, and whether it is real.

    A plain object rather than a dataclass because it carries three things a
    caller must not confuse: `value` (None where nothing could be read),
    `source` (the sentence shown beside the figure) and `derived` (False where
    the caller supplied it, which the bridge line already distinguishes).
    """

    __slots__ = ("value", "source", "derived")

    def __init__(self, value: Optional[int], source: str, derived: bool):
        self.value = value
        self.source = source
        self.derived = derived

    def to_dict(self) -> dict:
        return {"value_paise": self.value, "source": self.source,
                "derived": self.derived}


CALLER_SUPPLIED = "Supplied on the request; not taken from these books."

BF_LOSS_IS_NOT_DERIVED = (
    "Brought-forward loss set-off is not derived. §72, §73(4), §74 and §71B each "
    "allow a loss to reach only certain HEADS of income, and this bridge holds "
    "one figure for the whole computation — so a set-off derived from it would "
    "assert a head-wise answer nothing here can see. Record it from the "
    "carried-forward losses panel."
)


def book_profit(db, firm_id: str, client_id: str, fy_start: str,
                fy_end: str, current_user: dict) -> DerivedInput:
    """Profit per the accounts, from the same P&L the client has already read.

    Through `routers.accounting._reporting_service` so the CALLER'S SCOPE
    applies: a report built without it spans the whole firm for an Executive
    (ACC-17), and a bridge is a per-client document.
    """
    try:
        from routers.accounting import _reporting_service
        pl = _reporting_service(current_user).profit_loss(
            firm_id, client_id, fy_start, fy_end, basis="accrual")
    except Exception as e:                                        # noqa: BLE001
        _logger.warning("book profit for %s %s: %s", client_id, fy_end, e)
        return DerivedInput(None, (
            "Profit per the accounts could not be read from the ledger for this "
            "year. Enter it from the financial statements."), True)
    value = pl.get("net_profit_paise")
    if value is None:
        return DerivedInput(None, (
            "The Profit & Loss for this year returned no net profit figure."), True)
    return DerivedInput(int(value), (
        f"Net profit per the Profit & Loss for {fy_start} to {fy_end}, accrual "
        f"basis — the same statement the Accounting module renders."), True)


def depreciation_per_books(db, firm_id: str, client_id: str, fy_start: str,
                           fy_end: str) -> DerivedInput:
    """What was POSTED as depreciation in the year, per the accounts.

    `posted_depreciation_paise` is imported, never restated. FA-05 records the
    reason it must be the LEDGER's figure rather than the register's
    theoretical full-year charge, and a second reader of one fact is how the
    note and the Reports tab came to disagree.
    """
    try:
        value = _mv.posted_depreciation_paise(db, firm_id, client_id,
                                              fy_start, fy_end)
    except Exception as e:                                        # noqa: BLE001
        _logger.warning("book depreciation for %s: %s", client_id, e)
        value = None
    if value is None:
        return DerivedInput(None, (
            "Depreciation charged in the accounts could not be read — the "
            "Depreciation Expense account could not be resolved, or nothing was "
            "cached for the year. A ZERO here would claim nothing was charged."),
            True)
    return DerivedInput(int(value), (
        "Depreciation actually posted to the Depreciation Expense account for "
        "the year, read from account_period_balances."), True)


def section_43bh_disallowance(db, firm_id: str, client_id: str,
                              financial_year: str) -> DerivedInput:
    """§43B(h)'s own add-back, from the module that decides it.

    NOT the whole of `disallowances_paise`. §40(a)(ia), §40A(3), MSMED §23 and
    every other add-back a CA makes are theirs to add — this names the one the
    product computes, so a caller starting from zero is not starting from a
    figure that is wrong by exactly what §43B(h) disallows.
    """
    try:
        from services.msme_43bh_service import for_financial_year
        out = for_financial_year(db, firm_id, client_id, financial_year)
    except Exception as e:                                        # noqa: BLE001
        _logger.warning("43B(h) for %s %s: %s", client_id, financial_year, e)
        return DerivedInput(None, (
            "The §43B(h) disallowance could not be computed for this year."), True)
    value = int(out.get("disallowed_paise") or 0)
    return DerivedInput(value, (
        f"§43B(h) — sums payable to a micro or small enterprise beyond the "
        f"MSMED §15 limit, derived from the purchase ledger. This is the ONLY "
        f"disallowance derived here; §40(a)(ia), §40A(3) and MSMED §23 are the "
        f"CA's to add."), True)


def resolve_inputs(db, firm_id: str, client_id: str, financial_year: str,
                   current_user: dict, *,
                   book_profit_paise: Optional[int] = None,
                   disallowances_paise: Optional[int] = None,
                   depreciation_per_books_paise: Optional[int] = None) -> dict:
    """Each of the three derivable inputs, with its provenance.

    A CALLER'S VALUE WINS and is marked `derived: False`. That is not a
    fallback — a CA may be bridging a client whose accounts were prepared
    elsewhere, and refusing their figure would make the screen useless for
    exactly the clients whose bridge is hardest.
    """
    fy_end = _mv.fy_end_for_label(financial_year)
    fy_start, fy_last = _mv.fy_window(fy_end)
    if not fy_start or not fy_last:
        unusable = DerivedInput(None, (
            f"'{financial_year}' could not be read as a financial year, so "
            f"nothing was derived from the books."), True)
        return {"book_profit": unusable, "disallowances": unusable,
                "depreciation_per_books": unusable}

    def _or_caller(supplied, derive):
        if supplied is not None:
            return DerivedInput(int(supplied), CALLER_SUPPLIED, False)
        return derive()

    return {
        "book_profit": _or_caller(
            book_profit_paise,
            lambda: book_profit(db, firm_id, client_id, fy_start, fy_last,
                                current_user)),
        "disallowances": _or_caller(
            disallowances_paise,
            lambda: section_43bh_disallowance(db, firm_id, client_id,
                                              financial_year)),
        "depreciation_per_books": _or_caller(
            depreciation_per_books_paise,
            lambda: depreciation_per_books(db, firm_id, client_id, fy_start,
                                           fy_last)),
    }
