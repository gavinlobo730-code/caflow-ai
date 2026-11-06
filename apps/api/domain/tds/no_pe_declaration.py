"""
Who recorded a payee's no-permanent-establishment declaration (POST-A-401).

WHY THIS EXISTS
    Nil withholding on a payment to a non-resident rests on the payee's
    declaration that it has no permanent establishment in India, because s.195
    reaches only a sum chargeable under the Act (see migration 311's comment and
    `domain/tds/section_195.py`). s.201(1) and (1A) put the consequence of a
    wrong nil on the DEDUCTOR, so the register asks of the declaration who
    recorded it and when: `services/tds_register_service.py` adds
    `GAP_NO_PE_DECLARATION_UNDATED` to every s.195 bill whose supplier has the
    declaration ticked and does not hold BOTH a date (`no_pe_declaration_on`)
    and a member (`no_pe_declaration_by`, migration 311).

    The supplier form wrote the date whenever it was filled in. NOTHING wrote
    the member, so the gap could never be cleared: a CA who did everything the
    sentence asks ("record the date and the reference on the vendor") was told
    on every bill, for ever, that nobody had recorded who obtained it.

WHAT THE COLUMN HOLDS
    The signed-in member whose save RECORDED the declaration in this product:
    the one whose request left it ticked and dated and either changed it or
    found it unattributed. It is not the person who obtained the paper from the
    payee (nobody records that), and it is never stamped by a migration or a
    sweep. Migration 311 says why: every supplier that predates the column has
    no declarer, "backfilling either would be inventing evidence". A person's
    save of the supplier form is not a backfill; a row nobody saves again stays
    reported as a gap, which is the honest reading of it.

    A save that does not touch the declaration at all (a request carrying none
    of its three fields) never writes the column. A request that un-ticks the
    declaration, or leaves it with no date, empties the column: a name on a
    declaration that is not on file attributes nothing.

    THE CONSEQUENCE OF THE RULE FOR A SUPPLIER RECORDED BEFORE THIS EXISTED, said
    here so nobody finds it later: the supplier form sends the three fields on
    every save, so the next save of such a supplier with the declaration ticked
    and dated, by whoever makes it and for whatever reason (a changed phone
    number is enough), names that member. It is the first time a person has put
    a name on it, and the register's gap then clears; it is not evidence that
    the member obtained the paper. No screen shows who is named (an open item).

THE REASONING OF s.195 AND OF s.201 IS NOT RESTATED HERE and is not changed.
"""
from __future__ import annotations

from typing import Optional

#: The three supplier fields that make up the declaration (migration 311 and the supplier model).
DECLARATION_FIELDS = ("no_pe_declaration_on_file", "no_pe_declaration_on", "no_pe_declaration_ref")
#: The column this module decides.
DECLARANT_COLUMN = "no_pe_declaration_by"


def _read(row: dict, key: str):
    """One field of the declaration, normalised so that a stored 'date' and a sent 'str' compare as the same thing."""
    value = row.get(key)
    if key == "no_pe_declaration_on_file":
        return bool(value)
    if key == "no_pe_declaration_on":
        return str(value or "").strip()[:10]
    return str(value or "").strip()


def declarant_write(*, sent: dict, stored: Optional[dict], actor_id: Optional[str]) -> dict:
    """The write that goes with a supplier write for `no_pe_declaration_by`: `{}` (leave the column alone),
    `{"no_pe_declaration_by": <member>}` (attribute it to the member whose save this is) or
    `{"no_pe_declaration_by": None}` (the declaration is no longer on file, so it names nobody).

    `sent` is what the request carries (a create's whole payload, or a PATCH's present fields); `stored` is the row as it
    stands (None for a create); `actor_id` is the member's INTERNAL id (`users.id`, which is what the column references,
    and not the sign-in id).
    """
    if not any(field in sent for field in DECLARATION_FIELDS):
        return {}
    before = stored or {}
    after = {**before, **{field: sent[field] for field in DECLARATION_FIELDS if field in sent}}
    on_file_and_dated = _read(after, "no_pe_declaration_on_file") and bool(_read(after, "no_pe_declaration_on"))
    already_named = before.get(DECLARANT_COLUMN)
    if not on_file_and_dated:
        return {DECLARANT_COLUMN: None} if already_named else {}
    if not actor_id:
        return {}
    changed = any(_read(after, field) != _read(before, field) for field in DECLARATION_FIELDS)
    if changed or not already_named:
        return {DECLARANT_COLUMN: actor_id}
    return {}
