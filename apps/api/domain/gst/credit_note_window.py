"""
When a credit note can still reduce the tax — CGST Act §34(2).

THE RULE, and the word that decides it

    §34(2): "...no credit note shall be issued in respect of a supply after the
    thirtieth day of November following the end of the financial year in which
    SUCH SUPPLY was made, or the date of furnishing of the relevant annual
    return, whichever is earlier."

    The window runs from the financial year of the ORIGINAL SUPPLY, not from
    the note's own date. A June 2025 invoice credited in January 2027 is inside
    an open period — January 2027's GSTR-1 has not been filed — and outside
    §34(2)'s window, which closed on 30 November 2026 for FY 2025-26.

WHAT WAS WRONG (SALES-25a)
    `routers/credit_notes.py` asked two questions and neither was this one. It
    asked whether the note's OWN date sits in a locked financial year, and
    whether a return covering the note's OWN period has been filed. Both are
    right and both are about the wrong period. Nothing anywhere compared the
    note against the supply it credits, so a note that can never lawfully
    reduce output tax was accepted, posted, and reduced it in the books.

WHY IT WARNS AND DOES NOT REFUSE — and this is the part that is easy to get
backwards. §34(2) does not make the DOCUMENT unlawful; it bars the tax
ADJUSTMENT. A supplier may still issue a commercial credit note after the
window to settle a genuine dispute — it simply carries no GST and reduces no
liability. Refusing outright would stop a legitimate commercial act; saying
nothing lets a CA declare a reduction the portal will not accept. So the note
is written and the consequence is stated.

WHAT THIS IS NOT
    * NOT the §34(3) debit note. §34(4) requires a debit note to be declared in
      the return for the month it is issued and sets NO outer limit — the tax
      it carries is payable whenever it is raised. Do not add a window here.
    * NOT the recipient's side. A purchase credit note records the SUPPLIER's
      §34 document; what binds the client there is §16(4) and Rule 37, which
      are a different test on a different party.
    * NOT the period lock. `services/period_lock_service.py` answers "is this
      document's own period closed", which is asked as well, not instead.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from core.ist_clock import ist_fy_label


def _fy_end_year(supply_date: date) -> int:
    """The calendar year the supply's financial year ENDS in. FY 2025-26 → 2026."""
    return int(ist_fy_label(supply_date)[:4]) + 1


def window_closes(supply_date: date, annual_return_filed_on: Optional[date] = None) -> date:
    """The last day a credit note against this supply can carry tax.

    Delegates the "whichever is earlier" to
    `services/compliance_engine.correction_window_closes`, which is the one
    place that knows an early GSTR-9 shuts the window early (GST-09). Written
    as a delegation rather than a `date(y, 11, 30)` so a change to that rule
    reaches this one.
    """
    from services.compliance_engine import correction_window_closes
    return correction_window_closes(_fy_end_year(supply_date), annual_return_filed_on)


def late_credit_note(note_date: date, supply_date: Optional[date],
                     annual_return_filed_on: Optional[date] = None) -> Optional[str]:
    """Why this credit note can no longer reduce tax, or None.

    A WARNING. The note is still a valid commercial document; what it cannot do
    is carry GST. The message says which, because "too late" on its own reads
    as "do not raise it" and that is not what the section does.

    Silent when the supply date is unknown — a note with no linked invoice has
    no supply to measure against, and guessing the supply's financial year from
    the NOTE's date would reproduce the exact error this exists to catch.
    """
    if supply_date is None:
        return None
    closes = window_closes(supply_date, annual_return_filed_on)
    if note_date <= closes:
        return None
    early = annual_return_filed_on is not None and annual_return_filed_on <= closes
    because = ("the annual return for that year was furnished on "
               f"{closes.isoformat()}" if early
               else f"the window closed on {closes.isoformat()}")
    return (f"This credits a supply of {supply_date.isoformat()}, and {because} — "
            f"CGST §34(2) allows a credit note to reduce tax only up to 30 November "
            f"following the supply's financial year, or the date the annual return "
            f"was furnished, whichever is earlier. The note can still be issued as a "
            f"commercial credit, but it cannot reduce output tax and GSTR-1 will not "
            f"take the reduction.")
