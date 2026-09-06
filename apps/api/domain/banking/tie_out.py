"""
Does the statement we PARSED add up to the statement the bank PRINTED?

WHY THIS EXISTS, AND WHY IT IS NOT balance_agreement

`normalizer.balance_agreement` already checks the bank's running-balance column:
between consecutive rows the balance must move by exactly that row's own
movement. It is a good check and it catches the most damaging mapping error
there is — debit and credit read the wrong way round.

It cannot catch three things, and each of them loses money quietly:

  1. NO BALANCE COLUMN AT ALL. Plenty of exports omit it, and most PDF
     statements do. `balance_agreement` then returns `checked: False` and
     NOTHING verifies the parse. Today that is the silent case.
  2. ROWS DROPPED AT THE START OR THE END. A delta chain is still perfectly
     self-consistent after you remove rows from either end of it — every
     remaining pair still agrees. Truncate a page and nothing complains.
  3. WHETHER THE FILE WE READ IS THE WHOLE STATEMENT. Consecutive deltas are an
     INTERNAL check: they ask whether the rows agree with each other, never
     whether they agree with anything outside the file.

This asks a different question, against evidence from outside the file: the
opening and closing balances the bank prints on the statement itself.

    opening + Σ credits − Σ debits  ==  closing

If that does not hold to the paisa, something between the paper and the parse
is wrong, and the import is refused rather than posted.

WHY THE ARITHMETIC IS ORDER-BLIND, DELIBERATELY

`balance_agreement` had to learn about newest-first statements, because a
reversed delta chain has every sign inverted. A SUM does not care what order it
is added in, so this check needs no such special case and cannot be broken by
one. That is a property worth having in the check that blocks an import.

WHY IT IS ONLY CHECKED WHEN THE FIGURES ARE GIVEN

The two balances have to come from the CA reading the statement, because taking
them from the parsed rows would make the check circular — it would be proving
the file against itself, which is what `balance_agreement` already does better.
So when they are not supplied this returns `checked: False` AND NAMES ITSELF AS
A GAP, in the same shape as payroll's `statutory_gaps`: an unverified import and
a verified one must not look identical in the response.
"""
from __future__ import annotations

from typing import Optional, Sequence


def totals(txns: Sequence) -> tuple[int, int]:
    """(total debits, total credits) in paise. Integer arithmetic throughout —
    a statement tie-out done in floats would fail on rounding and be switched
    off within a month (CLAUDE.md, money rules)."""
    debits = sum(int(t.debit_paise or 0) for t in txns)
    credits = sum(int(t.credit_paise or 0) for t in txns)
    return debits, credits


def tie_out(
    txns: Sequence,
    *,
    opening_paise: Optional[int],
    closing_paise: Optional[int],
) -> dict:
    """Whether the parsed rows carry the statement from opening to closing.

    Returns a dict rather than raising: the caller decides whether a failure
    refuses the import or is merely reported, and the same structure is shown to
    the CA either way.
    """
    debits, credits = totals(txns)

    if opening_paise is None or closing_paise is None:
        missing = []
        if opening_paise is None:
            missing.append("opening")
        if closing_paise is None:
            missing.append("closing")
        return {
            "checked": False,
            "gap": (
                f"The {' and '.join(missing)} balance printed on the statement "
                f"was not given, so nothing confirms that every line was read. "
                f"{len(txns)} transactions were parsed."),
            "rows": len(txns),
            "total_debits_paise": debits,
            "total_credits_paise": credits,
        }

    opening = int(opening_paise)
    closing = int(closing_paise)
    computed = opening + credits - debits
    difference = computed - closing

    result = {
        "checked": True,
        "agrees": difference == 0,
        "rows": len(txns),
        "opening_balance_paise": opening,
        "closing_balance_paise": closing,
        "total_debits_paise": debits,
        "total_credits_paise": credits,
        "computed_closing_paise": computed,
        "difference_paise": difference,
    }
    if difference:
        result["reason"] = (
            f"The statement does not add up. Opening {_r(opening)} plus credits "
            f"{_r(credits)} less debits {_r(debits)} comes to {_r(computed)}, but "
            f"the statement's closing balance is {_r(closing)} — a difference of "
            f"{_r(abs(difference))}. Either some lines were not read, or a column "
            f"is mapped to the wrong thing. Nothing has been imported.")
    return result


def _r(paise: int) -> str:
    """Paise as rupees, grouped the way an Indian statement prints them.

    INDIAN GROUPING, NOT WESTERN. Three digits, then twos: 1,30,000 and not
    130,000. This sentence is read beside a bank statement and compared against
    it, and a CA reading `₹130,000.00` next to `₹1,30,000.00` has to stop and
    count digits. This repository already carries a scar from the other
    direction — `parseFloat("1,25,000")` is 1, which recorded one rupee for one
    and a quarter lakh (CLAUDE.md, "Money in the browser").

    Formatting only. Every comparison above is done on the integers.
    """
    sign = "-" if paise < 0 else ""
    whole, part = divmod(abs(int(paise)), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        # The leading group may be 1 or 2 digits; everything before it is twos.
        groups = [head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1]
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}.{part:02d}"
