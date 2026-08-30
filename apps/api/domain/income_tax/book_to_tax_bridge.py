"""
The book-to-tax bridge — from profit per the accounts to taxable income.

Every Indian tax computation a CA hands a client starts with the profit shown
in the financial statements and works down to the figure the return is filed
on, one named adjustment at a time. It is the document the client actually
reads, the document an assessing officer asks for, and the document that shows
whether the return and the accounts are telling the same story.

The pieces existed separately and nothing joined them. Disallowances were
detected (§40A(3), §43B) and could be accepted. Losses were tracked (§72).
Depreciation was charged under the Companies Act. Book profit was taken as an
INPUT by the minimum-tax engine precisely because nothing derived it. What was
missing was the statement that puts them in one column and makes them add up.

THE LINE THAT MATTERS MOST IS THE ONE THIS PRODUCT CANNOT YET COMPUTE

Depreciation is charged twice, on two different systems, and the difference is
usually the largest single adjustment in the bridge:

    Companies Act 2013, Schedule II — per ASSET, over its useful life. This is
    what routers/fixed_assets.py computes and what the accounts carry.

    IT Act 1961, §32 — per BLOCK OF ASSETS, at a rate fixed for the block,
    on the block's written-down value. Assets lose their identity inside the
    block; there is no per-asset life at all.

They are not two rates for one calculation, they are two systems, and NOTHING
IN THIS CODEBASE IMPLEMENTS THE SECOND ONE. So the §32 figure has to be
supplied, and when it is not, this bridge says so and marks itself incomplete.

It would be trivial to default the §32 figure to the book figure. That is the
one thing that must not happen: the two would net to zero, the bridge would
foot perfectly, and it would be silently wrong by whatever the real difference
is. A bridge that reconciles and lies is worse than one that refuses to
reconcile.

All monetary values are integer paise. Never float.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Direction = Literal["add", "deduct"]


@dataclass(frozen=True)
class BridgeLine:
    label: str
    amount_paise: int
    direction: Direction
    # The section the adjustment is made under, so a reader can check it.
    reference: str
    # True where the figure came from the books or from a detection this
    # product performed; False where a human supplied it or it is still
    # missing.
    derived: bool
    note: str = ""

    @property
    def signed_paise(self) -> int:
        return self.amount_paise if self.direction == "add" else -self.amount_paise


@dataclass(frozen=True)
class BookToTaxBridge:
    book_profit_paise: int
    lines: tuple[BridgeLine, ...]
    taxable_income_paise: int
    # False where an adjustment the bridge knows it needs was not supplied.
    # A bridge that foots is not the same as a bridge that is complete.
    is_complete: bool
    missing: tuple[str, ...]
    reasons: tuple[str, ...]

    def foots(self) -> bool:
        """The arithmetic property: the lines must actually get from book
        profit to the stated taxable income."""
        return (self.book_profit_paise + sum(l.signed_paise for l in self.lines)
                == self.taxable_income_paise)


def build_bridge(
    *,
    book_profit_paise: int,
    disallowances_paise: int = 0,
    depreciation_per_books_paise: int = 0,
    depreciation_under_section_32_paise: Optional[int] = None,
    brought_forward_loss_set_off_paise: int = 0,
    other_add_backs: Optional[list[tuple[str, int, str]]] = None,
    other_deductions: Optional[list[tuple[str, int, str]]] = None,
) -> BookToTaxBridge:
    """Build the statement.

    `depreciation_under_section_32_paise` is deliberately Optional with NO
    default figure. None means "not supplied", and the bridge then omits BOTH
    depreciation lines and marks itself incomplete — rather than adding back
    the book charge and allowing nothing, which would overstate income by the
    whole depreciation, or netting them to zero, which would understate the
    difference to nil. Neither wrong answer is safer than saying so.

    `other_add_backs` and `other_deductions` are (label, paise, reference)
    triples for adjustments a CA makes that this product does not detect —
    §14A, §36(1)(va), a prior-period item. They are marked as not derived.

    A nil adjustment produces no LINE. A statement does not print rows of
    zeros, and a supplied nil is still supplied — completeness is tracked by
    `is_complete`, not by whether a line happens to appear.
    """
    lines: list[BridgeLine] = []
    missing: list[str] = []
    reasons: list[str] = []

    # ── Disallowances already detected and accepted ──────────────────────────
    if disallowances_paise:
        lines.append(BridgeLine(
            label="Expenditure disallowed",
            amount_paise=abs(disallowances_paise), direction="add",
            reference="§40A(3), §43B and others accepted in the computation",
            derived=True,
            note="Added back because the expense was taken in the books but is "
                 "not deductible.",
        ))

    # ── Depreciation: two systems, not two rates ─────────────────────────────
    if depreciation_under_section_32_paise is None:
        missing.append("Depreciation allowable under IT Act §32")
        reasons.append(
            "Depreciation under IT Act §32 was not supplied, so the bridge is "
            "INCOMPLETE. §32 works on blocks of assets at block rates, while "
            "the accounts carry Companies Act Schedule II depreciation per "
            "asset over its useful life — two different systems, and nothing "
            "in this product computes the second. The two depreciation lines "
            "are omitted rather than assumed equal: assuming that would make "
            "the bridge foot perfectly while understating the difference to "
            "nil."
        )
    else:
        if depreciation_per_books_paise:
            lines.append(BridgeLine(
                label="Depreciation charged in the accounts",
                amount_paise=abs(depreciation_per_books_paise), direction="add",
                reference="Companies Act 2013, Schedule II",
                derived=True,
                note="Added back in full; the Act's own allowance is deducted "
                     "below.",
            ))
        if depreciation_under_section_32_paise:
            lines.append(BridgeLine(
                label="Depreciation allowable",
                amount_paise=abs(depreciation_under_section_32_paise),
                direction="deduct",
                reference="IT Act 1961, §32 — blocks of assets",
                derived=False,
                note="Supplied. Computed on the written-down value of each "
                     "block at the block's rate, not per asset.",
            ))

    # ── Anything the CA adds that this product does not detect ───────────────
    for label, amount, reference in (other_add_backs or []):
        lines.append(BridgeLine(
            label=label, amount_paise=abs(amount), direction="add",
            reference=reference, derived=False,
            note="Supplied by the CA; not detected by this product.",
        ))
    for label, amount, reference in (other_deductions or []):
        lines.append(BridgeLine(
            label=label, amount_paise=abs(amount), direction="deduct",
            reference=reference, derived=False,
            note="Supplied by the CA; not detected by this product.",
        ))

    # ── Brought-forward losses, set off LAST ─────────────────────────────────
    # §72 sets off a brought-forward business loss against the business income
    # of the year, which means against the figure AFTER every other adjustment.
    # Setting it off earlier would let a later add-back resurrect income the
    # loss had already absorbed.
    if brought_forward_loss_set_off_paise:
        lines.append(BridgeLine(
            label="Brought-forward business loss set off",
            amount_paise=abs(brought_forward_loss_set_off_paise),
            direction="deduct",
            reference="IT Act 1961, §72",
            derived=True,
            note="Set off against the income of the year after all other "
                 "adjustments.",
        ))

    taxable = book_profit_paise + sum(l.signed_paise for l in lines)
    if not missing:
        reasons.append(
            "Every adjustment this product knows of has a figure, so the "
            "bridge is complete. It is still the CA's to review — adjustments "
            "it does not detect are not adjustments that do not exist."
        )
    return BookToTaxBridge(
        book_profit_paise=book_profit_paise,
        lines=tuple(lines),
        taxable_income_paise=taxable,
        is_complete=not missing,
        missing=tuple(missing),
        reasons=tuple(reasons),
    )
