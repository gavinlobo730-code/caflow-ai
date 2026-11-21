"""The unit price before GST that a GST-inclusive figure stands for (POST-A-490).

WHAT IT IS FOR
    A tester asked, and the owner said on 21-11-2026 to build it: while raising a sales invoice a person often knows only
    the price INCLUDING GST ("Rs 11,800 all in") and has to work the price before tax out on a calculator. This module is
    that working, done by the server, so the screen does no arithmetic.

IT ANSWERS A RATE, AND THE LINE IS SAVED AS AN ORDINARY LINE
    The invoice stores a line as quantity and a unit rate in whole paise, and everything downstream (the value of supply
    under CGST s.15, the tax, the journal, GSTR-1, the PDF, the check that a draft adds up to its own lines) computes from
    those two. An "inclusive" flag stored on the line would need every one of them taught a second way to value a line.
    So nothing new is stored: this module answers "which unit rate, typed into the rate box, gives the figure you have",
    the person accepts it, and the line is then exactly like any other.

THE FIGURES IT SHOWS ARE THE ENGINE'S, NOT ITS OWN
    Every figure in the answer is computed the way the invoice routes compute a line: the gross is
    `int(Decimal(str(quantity)) * rate_paise)` (truncated), the discount is `domain/gst/discount.apply_to_lines`, and the
    tax is `domain/sales/line_tax.compute_line_gst`, which takes the full tax first, rounded DOWN to the paisa, and only
    then halves it into CGST and SGST. The total tax is therefore the same whether the supply turns out intra-State or
    inter-State, which is why this module needs no place of supply. A test drives the real create route with the rate
    answered here and compares the stored line with the answer, so "as the invoice will compute it" is held and not said.

AN EXACT RATE DOES NOT ALWAYS EXIST, AND THE ANSWER SAYS SO
    A unit rate is a whole number of paise, a line's value is quantity times that rate, and the tax on it is rounded
    down. So some inclusive totals cannot be reached to the paisa (measured over every whole-rupee total to Rs 10,000 at
    quantity one: none at 12%, but 476 at 5%, 1,523 at 18% and 1,250 at 28% are one paisa out), and with a large quantity
    the gap grows, because one paisa on the rate moves the line by the quantity. The answer is the NEAREST rate (the
    lower one on a tie, so the customer is never charged more than the typed figure by a choice of ours), the line's
    real total, and the difference in words. Nothing is rounded to make the two agree: a silent difference between what
    a person typed and what the invoice says is the failure this product does not allow.

WHAT THE TYPED FIGURE MEANS WHEN THE LINE HAS A DISCOUNT
    It is the price BEFORE the line's discount, inclusive of GST: the list price. A discount recorded on the invoice
    reduces the value of supply (CGST s.15(3)(a)), so it comes off the value before tax, and the tax is charged on what
    is left; the answer shows both the line before the discount, which is what is compared with the typed figure, and
    the line as it will stand after it. A discount on the whole invoice is allocated across the lines later and is not
    this module's to know.

WHAT IT REFUSES
    A line carrying compensation cess: the cess is charged on the same value (and, for some goods, per unit as well), so
    an inclusive price includes it too, and backing two levies out of one figure is not built. It is refused in a
    sentence, not answered as if the cess were not there.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from domain.gst import discount as gst_discount
from domain.money_sentence import rupee_text
from domain.quantity import quantity_violation
from domain.sales.line_tax import compute_line_gst

#: The typed figure is the price of ONE unit, or of the whole line.
BASES = ("unit", "line")
#: A bound on the typed figure, so the search below is over a finite range whatever is sent. Rs 1,00,000 crore.
MAX_INCLUSIVE_PAISE = 10 ** 14
BPS = 10_000


class CannotWorkBack(ValueError):
    """The question cannot be answered as asked. The message is written for the person who typed the figure."""


@dataclass(frozen=True)
class InclusiveAnswer:
    #: The unit rate before GST, in whole paise: what goes in the line's rate box.
    rate_paise: int
    #: The typed figure as a total for the line, before any discount (for a per-unit figure, quantity times it).
    typed_total_paise: int
    #: The line at that rate BEFORE its discount: value, tax and total. `list_total_paise` is what is compared with the typed figure.
    list_value_paise: int
    list_tax_paise: int
    list_total_paise: int
    #: `list_total_paise - typed_total_paise`: zero when the rate reproduces the typed figure exactly.
    difference_paise: int
    exact: bool
    #: The line as the invoice will hold it, after the line's own discount (the same three figures when there is none).
    discount_paise: int
    taxable_paise: int
    tax_paise: int
    total_paise: int
    #: What happened, in words, for the screen to show as it is.
    sentence: str

    def as_dict(self) -> dict:
        return asdict(self)


def _gross(quantity: Decimal, rate_paise: int) -> int:
    """A line's value before discount, exactly as the invoice routes compute it: truncated toward zero."""
    return int(quantity * int(rate_paise))


def _tax(taxable_paise: int, gst_rate_bps: int) -> int:
    cgst, sgst, igst = compute_line_gst(taxable_paise, gst_rate_bps, False)
    return cgst + sgst + igst


def _list_total(quantity: Decimal, rate_paise: int, gst_rate_bps: int) -> int:
    value = _gross(quantity, rate_paise)
    return value + _tax(value, gst_rate_bps)


def _quantity(value) -> Decimal:
    problem = quantity_violation(value)
    if problem:
        raise CannotWorkBack(problem)
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise CannotWorkBack("Enter the quantity as a number.") from None
    if not quantity.is_finite() or quantity <= 0:
        raise CannotWorkBack("The quantity must be more than zero.")
    return quantity


def rate_for_inclusive(*, inclusive_paise: int, basis: str, quantity, gst_rate_bps: int,
                       discount_percent_bps: Optional[int] = None, discount_paise: Optional[int] = None,
                       has_cess: bool = False) -> InclusiveAnswer:
    """The unit rate before GST nearest to a GST-inclusive figure, with the line it gives. Raises `CannotWorkBack`."""
    if basis not in BASES:
        raise CannotWorkBack("Say whether the figure is the price of one unit or of the whole line.")
    if has_cess:
        raise CannotWorkBack(
            "This line carries compensation cess, and a price that includes both GST and cess cannot be worked back "
            "yet. Type the price before tax for this line.")
    if isinstance(inclusive_paise, bool) or not isinstance(inclusive_paise, int) or inclusive_paise <= 0:
        raise CannotWorkBack("Enter the price including GST as an amount more than zero.")
    if inclusive_paise > MAX_INCLUSIVE_PAISE:
        raise CannotWorkBack("That amount is too large to work back.")
    if isinstance(gst_rate_bps, bool) or not isinstance(gst_rate_bps, int) or not 0 <= gst_rate_bps <= BPS:
        raise CannotWorkBack("Choose the line's GST rate first.")
    qty = _quantity(quantity)

    # The typed figure as a line total. A per-unit figure is multiplied out the way the engine multiplies a rate.
    typed_total = inclusive_paise if basis == "line" else _gross(qty, inclusive_paise)
    if typed_total <= 0:
        raise CannotWorkBack("At this quantity the figure comes to less than one paisa for the line.")
    if typed_total > MAX_INCLUSIVE_PAISE:
        raise CannotWorkBack("That amount is too large to work back.")

    # The line's total rises (never falls) as the rate rises, so the largest rate whose total does not pass the typed
    # figure is found by halving, and the answer is that rate or the next one up, whichever lands nearer. The upper
    # bound is a rate that certainly passes it: a quantity is at least 0.001, so a rate of 1000 x the total (+1) does.
    low, high = 0, typed_total * 1000 + 1
    while low < high:
        mid = (low + high + 1) // 2
        if _list_total(qty, mid, gst_rate_bps) <= typed_total:
            low = mid
        else:
            high = mid - 1
    under, over = low, low + 1
    under_gap = typed_total - _list_total(qty, under, gst_rate_bps)
    over_gap = _list_total(qty, over, gst_rate_bps) - typed_total
    # The lower rate on a tie: where two rates are equally near, the customer is not charged more than was typed.
    rate = over if over_gap < under_gap else under
    # With a quantity that is not a whole number several rates give the SAME line (the value is truncated to the paisa:
    # half a unit at Rs 1.90 and at Rs 1.91 are both 95 paise). Of those the lowest is answered: it is the one whose
    # quantity times rate is nearest the value the line actually holds, so the rate printed on the invoice multiplies
    # out to the line beside it as closely as a rate can.
    chosen_total = _list_total(qty, rate, gst_rate_bps)
    low, high = 0, rate
    while low < high:
        mid = (low + high) // 2
        if _list_total(qty, mid, gst_rate_bps) >= chosen_total:
            high = mid
        else:
            low = mid + 1
    rate = low
    if rate <= 0:
        raise CannotWorkBack("At this quantity the unit price would be less than one paisa, which a line cannot hold. "
                             "Type the price before tax for this line.")

    list_value = _gross(qty, rate)
    list_tax = _tax(list_value, gst_rate_bps)
    list_total = list_value + list_tax
    difference = list_total - typed_total

    try:
        resolved = gst_discount.apply_to_lines([{
            "gross_paise": list_value,
            "discount_percent_bps": discount_percent_bps,
            "discount_paise": discount_paise,
        }])[0]
    except ValueError as exc:
        raise CannotWorkBack(str(exc)) from None
    discount = int(resolved["discount_paise"])
    taxable = int(resolved["taxable_paise"])
    tax = _tax(taxable, gst_rate_bps)

    answer = InclusiveAnswer(
        rate_paise=rate, typed_total_paise=typed_total,
        list_value_paise=list_value, list_tax_paise=list_tax, list_total_paise=list_total,
        difference_paise=difference, exact=difference == 0,
        discount_paise=discount, taxable_paise=taxable, tax_paise=tax, total_paise=taxable + tax,
        sentence="",
    )
    return InclusiveAnswer(**{**asdict(answer), "sentence": _sentence(answer, gst_rate_bps)})


def _sentence(a: InclusiveAnswer, gst_rate_bps: int) -> str:
    rate = rupee_text(a.rate_paise)
    if gst_rate_bps == 0:
        opening = f"At a nil rate of GST the price before tax is the price itself: {rate} a unit."
    elif a.exact:
        opening = (f"A price of {rate} a unit before GST gives exactly the {rupee_text(a.typed_total_paise)} you typed "
                   f"for the line: {rupee_text(a.list_value_paise)} and {rupee_text(a.list_tax_paise)} of GST.")
    else:
        gap = rupee_text(abs(a.difference_paise))
        side = "more" if a.difference_paise > 0 else "less"
        opening = (f"The nearest price is {rate} a unit before GST. The line then comes to "
                   f"{rupee_text(a.list_total_paise)} ({rupee_text(a.list_value_paise)} and "
                   f"{rupee_text(a.list_tax_paise)} of GST), which is {gap} {side} than the "
                   f"{rupee_text(a.typed_total_paise)} you typed. No price reaches it exactly, because a unit price is "
                   "a whole number of paise and the GST on a line is rounded down to the paisa.")
    if a.discount_paise:
        opening += (" The figure you typed is taken as the price before this line's discount. After the discount of "
                    f"{rupee_text(a.discount_paise)} the line is {rupee_text(a.taxable_paise)} and "
                    f"{rupee_text(a.tax_paise)} of GST, {rupee_text(a.total_paise)} in all.")
    return opening
