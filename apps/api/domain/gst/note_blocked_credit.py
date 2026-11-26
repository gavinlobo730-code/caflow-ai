"""A purchase note's blocked input credit, CGST Act s.17(5) (POST-A-459, migration 685).

A purchase bill line says whether its credit is blocked (`itc_eligible`, `blocked_credit_reason`, migration 240) and the bill's header
carries the blocked tax per head (`ineligible_itc_{cgst,sgst,igst,cess}_paise`); the bill's journal debits the credit ledgers with the
creditable tax only. A purchase debit note (a return to the supplier) and a purchase credit note (the supplier's increase) adjust that
supply, so a line of either says the same thing, CA-set and never inferred, and this module turns the lines the router computed into the
columns it stores.

THE KEYS ARE WRITTEN ONLY WHEN A LINE IS BLOCKED. The API is deployed minutes before the migration that adds the columns, and both
insert paths would refuse a key for a column that does not exist yet (the draft path inserts every key its lines name). So a note with
no blocked line is stored exactly as before; and where any line is blocked, EVERY line carries `itc_eligible`, because the draft path
inserts the union of the lines' keys and a line that did not name it would store NULL in a NOT NULL column.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

#: (header column, line column) for each head the bill splits, in the bill's order.
HEADS = (
    ("ineligible_itc_cgst_paise", "cgst_paise"),
    ("ineligible_itc_sgst_paise", "sgst_paise"),
    ("ineligible_itc_igst_paise", "igst_paise"),
    ("ineligible_itc_cess_paise", "cess_paise"),
)


def is_blocked(line: Mapping[str, Any]) -> bool:
    """Only an explicit False is blocked: a line that does not say is eligible, which is the column's default and how it was posted."""
    return line.get("itc_eligible") is False


def mark_lines(computed: list[dict], lines_in: Iterable[Mapping[str, Any]]) -> list[dict]:
    """The computed line rows with the blocked mark of the line each was computed from (same order), under the rule in the module
    docstring: nothing added when no line is blocked, `itc_eligible` on every line (and the reason on the blocked ones) when one is."""
    sources = [ln if isinstance(ln, Mapping) else ln.model_dump() for ln in lines_in]
    if len(sources) != len(computed):
        raise ValueError("each computed line is marked from the line it was computed from")
    if not any(is_blocked(s) for s in sources):
        return computed
    out = []
    for row, src in zip(computed, sources, strict=True):
        blocked = is_blocked(src)
        out.append({**row, "itc_eligible": not blocked,
                    "blocked_credit_reason": (str(src.get("blocked_credit_reason") or "").strip() or None) if blocked else None})
    return out


def header_columns(lines: Iterable[Mapping[str, Any]], *, always: bool = False) -> dict:
    """The four blocked heads, the blocked lines' sums. Empty when all four are nil and `always` is false (the module docstring says
    why); `always` is for an edit of a note that already carries one, which must be able to set it back to nil."""
    blocked = [ln for ln in lines if is_blocked(ln)]
    cols = {h: sum(int(ln.get(c) or 0) for ln in blocked) for h, c in HEADS}
    return cols if always or any(cols.values()) else {}


def carries_any(header: Mapping[str, Any]) -> bool:
    """Whether a stored header carries a blocked head (and so the columns exist on the database it came from)."""
    return any(int(header.get(h) or 0) for h, _c in HEADS)


def blocked_of(header: Mapping[str, Any]) -> dict:
    """{'cgst': .., 'sgst': .., 'igst': .., 'cess': ..} of a stored header, 0 where it carries none."""
    return {c.split("_")[0]: int(header.get(h) or 0) for h, c in HEADS}
