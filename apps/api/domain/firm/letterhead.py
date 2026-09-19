"""Whose name goes on a document this practice produces.

── WHY ──────────────────────────────────────────────────────────────────────
The year-end pack's cover read

    Prepared by:  PracticeSync AI — Practice Management Platform

on a set of financial statements a CA SIGNS and hands to their client. The
software did not prepare them; the practice did. A reader of a signed statement
set asks who stands behind it, and the answer was the name of a tool.

── WHY IT IS A MODULE AND NOT A STRING ──────────────────────────────────────
Because the ABSENCE has to be handled, and handled the same way everywhere. The
PDF services are given an engagement, which carries `firm_id` and no name, so
the name is fetched and threaded through — and a fetch can fail, or return a
row with a blank name on a database where `firms.name` was not always NOT NULL.

`prepared_by` therefore has three answers, and the third is the point: where no
name is known it says the statements were prepared BY THE PRACTICE without
naming one, rather than falling back to the product's name. A wrong attribution
on a signed document is worse than a vague one.

── WHAT THIS DELIBERATELY DOES NOT DO ───────────────────────────────────────
It puts NO branding on a document that belongs to the CLIENT. CLAUDE.md records
three separately-fixed bugs where the practice's logo, signature placement or
UPI id reached a sales invoice, a payslip or a customer statement — documents
the client issues to a stranger. This is for the pack the PRACTICE issues.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

#: What the cover says when no firm name is known. It names the ROLE, not the
#: product: the statements were prepared by a practice, and this document
#: cannot say which. Never "PracticeSync".
UNNAMED_PRACTICE = "The practice"


def firm_name_of(firm: Optional[Mapping[str, Any]]) -> Optional[str]:
    """`firms.name`, or None. A blank string is None — a name of spaces is not
    a name, and it would print as an empty cell beside the label."""
    if not firm:
        return None
    raw = firm.get("name")
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def prepared_by(firm_name: Optional[str]) -> str:
    """The cover's "Prepared by" line."""
    return firm_name.strip() if firm_name and firm_name.strip() else UNNAMED_PRACTICE


def generated_note(firm_name: Optional[str], when: str) -> str:
    """The footer line under the last schedule.

    It says WHEN and WHO, and no longer says by what software. `when` is
    already formatted by the caller — this module knows nothing about clocks,
    and the year-end pack's own IST rule lives with the pack.
    """
    return f"Prepared by {prepared_by(firm_name)}. Generated on {when}. For internal use only."
