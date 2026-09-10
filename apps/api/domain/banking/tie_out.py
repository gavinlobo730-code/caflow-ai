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

import re
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


# ── The statement's own totals ───────────────────────────────────────────────

#: "Grand Total", specifically. A statement that prints per-page subtotals and
#: then a grand total has said WHICH row is the whole statement, and that is the
#: only way this module will choose between several candidates. It must stay a
#: SUBSET of the normalizer's _TOTAL_LABEL — a row this matches and that one
#: does not would be a total the parser never skipped — and a test pins that.
_GRAND_LABEL = re.compile(r"^\s*grand\s+totals?\s*:?\s*$", re.IGNORECASE)


def printed_totals(rows: Sequence[Sequence], adapter: dict) -> Optional[dict]:
    """The withdrawal and deposit totals the BANK printed, if it printed them.

    WHY THIS IS BETTER THAN ASKING THE CA FOR THE BALANCES

        `tie_out` needs the opening and closing balances typed in, which makes
        the strongest check in the import optional and manual — and an optional
        check on a 300-line statement is one that mostly does not happen.

        But most Indian statements END WITH THEIR OWN TOTALS. The real 33-page
        Cosmos Co-op statement this was built against prints

            Grand Total   251528.32   252361.07

        and the parse summed to exactly that. So the evidence for "every line was
        read" is usually already IN THE FILE, and asking for it was asking the CA
        to retype something the bank had already written down.

    WHY IT REFUSES TO GUESS

        A totals row does NOT follow the column mapping — Cosmos puts the label
        in column 0 and the two figures in 1 and 2, while the transaction rows
        have their amounts in 3 and 4. So the figures are read positionally, and
        that is only safe when there is no ambiguity about which is which:

          * exactly TWO numbers in the row. Three could include a closing
            balance and there would be no way to tell which two are the totals;
          * the ORDER comes from the adapter, not from a guess: whichever of
            the debit and credit columns appears first in the header is the one
            the first figure belongs to.

        Anything else returns None, and the caller falls back to the balances.
        A totals check that is right most of the time is worse than one that
        says it could not find them.

    AND WHY IT NO LONGER TAKES THE FIRST ROW IT FINDS (BANK-01)

        It used to return the FIRST matching row, which on a multi-page
        statement is a PAGE SUBTOTAL. The parse then disagreed with it — of
        course it did, the parse covers every page — and `statement_check`
        refused the import outright, with a message telling the CA to check
        their column mapping when no mapping was involved and nothing had been
        misread. Per-page and per-month subtotals labelled "Total" are ordinary
        in Indian bank exports, so a good statement could not be imported at
        all without editing the bank's file by hand.

        The rule now is that the FILE has to say which row is the whole
        statement, and there are exactly two ways it can:

          * it prints one totals row, and that row is the statement's;
          * it prints several, and exactly one of them is labelled "Grand
            Total" — the bank itself distinguishing the whole from the parts.

        Anything else is AMBIGUOUS and this says so rather than choosing: the
        return carries `ambiguous: True` and a sentence, `totals_agreement`
        reports the check as not made, and the import falls back to the typed
        balances exactly as it does for a statement that prints no totals. An
        unchecked import is a worse outcome than a checked one and a better
        outcome than a wrong refusal.

        WHAT IS DELIBERATELY NOT DONE, because it is the obvious idea: pick
        whichever candidate agrees with the parsed sums. That makes the check
        prove itself. The whole value of this evidence is that it comes from
        outside the reading being checked, and a rule that selects the row our
        own arithmetic already matches can never fail — it would turn the
        strongest check in the import into a decoration.
    """
    # The label pattern lives in the normalizer, because the parser has to
    # recognise the same row: it is the row _rows_to_txns skips for having no
    # date, and one definition is what keeps "skipped there" and "read here"
    # describing the same row.
    candidates = totals_candidates(rows, adapter)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    grand = [c for c in candidates if _GRAND_LABEL.match(c["label"])]
    if len(grand) == 1:
        return grand[0]

    labels = []
    for c in candidates:                       # distinct, in the file's order
        if c["label"] not in labels:
            labels.append(c["label"])
    quoted = ", ".join(f'"{l}"' for l in labels)
    return {
        "ambiguous": True,
        "candidates": len(candidates),
        "labels": labels,
        "gap": (
            f"This statement prints {len(candidates)} totals rows ({quoted}) and "
            f"none of them is marked as the grand total, so which one totals the "
            f"whole statement cannot be told from the file — they may be page or "
            f"month subtotals. The parse was not checked against any of them. "
            f"Give the opening and closing balances printed on the statement to "
            f"have it checked."),
    }


def totals_candidates(rows: Sequence[Sequence], adapter: dict) -> list[dict]:
    """Every row that could be a totals row, in the order the file prints them.

    Separate from the choosing so that the choice is testable on its own, and
    so a caller that wants to SHOW the CA what was found can.
    """
    from .normalizer import _TOTAL_LABEL

    debit_col, credit_col = adapter.get("debit"), adapter.get("credit")
    if debit_col is None or credit_col is None:
        # The single-amount + Dr/Cr layout has no two columns to order.
        return []

    out: list[dict] = []
    for row in rows:
        cells = [("" if c is None else str(c)).strip() for c in row]
        if not cells or not _TOTAL_LABEL.match(cells[0]):
            continue
        numbers = [c for c in cells[1:] if _looks_numeric(c)]
        if len(numbers) != 2:
            continue
        first, second = _paise(numbers[0]), _paise(numbers[1])
        if first is None or second is None:
            continue
        debit_first = debit_col < credit_col
        out.append({
            "label": cells[0],
            "total_debits_paise": abs(first if debit_first else second),
            "total_credits_paise": abs(second if debit_first else first),
        })
    return out


def _looks_numeric(cell: str) -> bool:
    """A money cell, and not a date or a reference number. `_to_paise` is happy
    to read "01/04/2026" as something, so the shape is checked first."""
    return bool(re.fullmatch(r"[₹\s]*-?[\d,]+(\.\d{1,2})?\s*(dr|cr)?", cell,
                             re.IGNORECASE)) and any(ch.isdigit() for ch in cell)


def _paise(cell: str) -> Optional[int]:
    from .normalizer import _to_paise
    try:
        return _to_paise(cell)
    except Exception:  # noqa: BLE001 — an unparseable cell is simply not a total
        return None


def totals_agreement(txns: Sequence, printed: Optional[dict]) -> dict:
    """Do the rows we parsed sum to the totals the bank printed?

    The same question `tie_out` asks, against evidence the file supplies itself.
    Where both are available both are checked: they are not the same check —
    this one catches a misread AMOUNT that leaves the balance column consistent,
    and the tie-out catches rows missing from the ends. Neither implies the
    other.
    """
    debits, credits = totals(txns)
    if not printed or printed.get("ambiguous"):
        # AMBIGUOUS IS NOT THE SAME AS ABSENT, and the CA is told which it was.
        # "This statement does not print its own totals" in front of a statement
        # that visibly does would send somebody looking for a parsing bug.
        return {
            "checked": False,
            "gap": (printed or {}).get("gap") or (
                "This statement does not print its own totals, so the "
                "opening and closing balances are the only way to check it."),
            "ambiguous": bool(printed and printed.get("ambiguous")),
            "total_debits_paise": debits,
            "total_credits_paise": credits,
        }

    pd_, pc_ = printed["total_debits_paise"], printed["total_credits_paise"]
    dd, dc = debits - pd_, credits - pc_
    out = {
        "checked": True,
        "agrees": dd == 0 and dc == 0,
        "label": printed["label"],
        "total_debits_paise": debits,
        "total_credits_paise": credits,
        "printed_debits_paise": pd_,
        "printed_credits_paise": pc_,
        "debit_difference_paise": dd,
        "credit_difference_paise": dc,
    }
    if not out["agrees"]:
        parts = []
        if dd:
            parts.append(f"withdrawals came to {_r(debits)} against the "
                         f"statement's {_r(pd_)}")
        if dc:
            parts.append(f"deposits came to {_r(credits)} against the "
                         f"statement's {_r(pc_)}")
        out["reason"] = (
            f"This statement does not match its own \"{printed['label']}\" row: "
            + " and ".join(parts)
            # THREE explanations, not two. The old sentence named only the two
            # that are our fault — lines missed, a column mapped wrong — and a
            # CA whose file was fine was sent hunting for a mapping error that
            # did not exist (BANK-01). The bank's own row not being comparable
            # is a real and common third case: it can include a brought-forward
            # line, or cover a period the export was filtered out of.
            + ". Either some lines were not read, or a column is mapped to the "
              "wrong thing, or the row does not cover the same lines this file "
              "does. Nothing has been imported. If you have compared the two "
              "yourself and the file is right, import it again with a note "
              "saying why.")
    return out


def statement_check(
    txns: Sequence,
    *,
    opening_paise: Optional[int],
    closing_paise: Optional[int],
    printed: Optional[dict],
    totals_mismatch_acknowledged: bool = False,
) -> dict:
    """The whole verification of one import, as a single answer.

    There are two independent pieces of evidence that a statement was read
    completely, and they are NOT interchangeable:

      * the totals the bank PRINTED on the statement (`totals_agreement`) —
        free, universal wherever the bank prints them, and evidence from inside
        the file about the file;
      * the opening and closing balances a CA TYPES IN (`tie_out`) — evidence
        from outside the file, which is the only thing that can say the file is
        the whole period.

    Both are run whenever they are available, and EITHER failing refuses the
    import. Combining them here rather than in the router keeps the decision in
    one testable place, and lets the refusal say something the two checks cannot
    say separately: when the rows match the statement's own totals but not the
    typed balances, nothing was misread — the file simply is not the period
    those balances belong to, and telling the CA to go looking for a mapping
    error would send them after a bug that is not there.

    THE ACKNOWLEDGEMENT, AND WHY ONLY ONE OF THE TWO HAS ONE (BANK-01)

    `totals_mismatch_acknowledged` lets a CA who has compared the figures
    themselves import over a printed-totals mismatch. It exists because that
    refusal was the only one in the import with NO way past it: the evidence
    comes out of the file, so a CA who knows the bank's own row is not
    comparable — it carries a brought-forward line, or the export was filtered —
    could do nothing but edit the bank's statement by hand, which destroys the
    evidence and leaves nothing checked at all. A refusal should be a stop, not
    a wall.

    The tie-out deliberately gets no such door, and the asymmetry is the point:
    the balances it checks were typed into THIS request, so a CA who does not
    want that check simply does not type them. There is nothing to acknowledge
    — only a figure to correct or to omit.

    An acknowledged import is NEVER `verified`, even when the typed balances tie
    out. Something in the file contradicts the parse; that a second check passed
    does not unsay it, and a response that read as verified would put an
    acknowledged import and a clean one in the same box. What it gets instead is
    a `gap` that states the disagreement — and the caller records the CA's
    reason beside the two differences it excused.
    """
    tie = tie_out(txns, opening_paise=opening_paise, closing_paise=closing_paise)
    tot = totals_agreement(txns, printed)

    tot_ok = tot.get("checked") and tot.get("agrees")
    tie_ok = tie.get("checked") and tie.get("agrees")
    tot_bad = tot.get("checked") and not tot.get("agrees")
    tie_bad = tie.get("checked") and not tie.get("agrees")

    acknowledged = bool(tot_bad and totals_mismatch_acknowledged)

    refusal = None
    refusal_code = None
    if tot_bad and not acknowledged:
        refusal = tot["reason"]
        refusal_code = "totals_mismatch"
    elif tie_bad:
        refusal = tie["reason"]
        refusal_code = "tie_out"
        if tot_ok:
            refusal += (
                f" The lines DO add up to the statement's own \"{tot['label']}\" "
                f"row, so nothing was missed in the reading — check the two "
                f"balances that were typed in, and that this file covers the "
                f"period they belong to.")

    verified = bool((tot_ok or tie_ok) and not refusal and not acknowledged)
    gap = None
    if acknowledged:
        gap = (
            f"The lines do not agree with the statement's own "
            f"\"{tot['label']}\" row and the import was accepted anyway, on a "
            f"written note. "
            + ("The opening and closing balances given do tie out."
               if tie_ok else
               "Nothing else confirmed that every line was read."))
    elif not verified and not refusal:
        gap = (
            (tot.get("gap") + " ") if tot.get("gap") and tot.get("ambiguous") else
            "Nothing confirms that every line was read: this statement prints "
            "no totals of its own, and the opening and closing balances were "
            "not given. ") + f"{len(txns)} transactions were parsed."

    return {
        "verified": verified,
        "refusal": refusal,
        # What was refused, for a caller that has something to offer the CA. The
        # sentence is written for a human and must stay the thing that is shown;
        # matching a screen's behaviour on its wording is how a message becomes
        # unfixable.
        "refusal_code": refusal_code,
        "acknowledged": acknowledged,
        "gap": gap,
        "tie_out": tie,
        "totals_check": tot,
    }
