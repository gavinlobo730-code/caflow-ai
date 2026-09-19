"""
What a Tally export's customer and vendor identifiers may carry into the
masters — CGST Act 2017 section 16(2)(aa), and section 206AA of the
Income-tax Act 1961.

WHY THIS IS A RULE AND NOT A LINE IN THE IMPORTER

    `validate_migration_data` tested a customer's GSTIN against a private
    shape regex, appended a sentence to `validation_errors` and left the
    item's `status` at "validated" — so `preview_migration` did not count it,
    `execute_migration` did not skip it, and `_import_single_item` wrote the
    value straight into `customers.gstin` over PostgREST, which is the one
    door `models/parties.CustomerIn` does not stand in front of. The error was
    recorded and moved nothing. The vendor branch did not ask at all, and the
    vendor side is where a wrong GSTIN costs the client their input tax
    credit.

WHAT IS WITHHELD, AND WHY NOT THE WHOLE PARTY

    The party is imported; the identifier is not. A Tally book that has been
    kept for fifteen years carries typed identifiers nobody has ever checked,
    and refusing the customer would lose the name, the address, the email and
    the PAN — all of which are fine — while refusing the JOB (which is what
    marking the item `failed` does, since the migration screen disables the
    import button on any error count) would make a migration impossible for
    exactly the clients who most need one. That is the reasoning
    `domain/accounting/opening_documents` records for not checking a
    carried-over document number against Rule 46(b).

THE DIRECTION OF THE ERROR DECIDES IT, FOR BOTH IDENTIFIERS

    GSTIN. A party with no GSTIN is unregistered as far as this product is
    concerned, so supplies to them are B2C and that customer's credit waits
    until somebody records the real number — which they will, because the
    customer asks. A party carrying somebody ELSE'S well-formed GSTIN has
    every invoice declared under it: the stranger's GSTR-2B carries the
    supply, the real customer never gets the credit, and the correction is an
    amendment under section 37(3) inside the window that closes on 30 November
    following the financial year or the date GSTR-9 was furnished, whichever
    is earlier. Both lose the credit; only one hands it to a stranger and
    needs an amendment to undo.

    PAN. `domain/tds/tds_computer.has_pan` reads any non-empty value as a PAN
    on file, so a malformed one suppresses section 206AA's 20% floor and the
    bill is under-deducted — and section 40(a)(ia) disallows the WHOLE
    expenditure for an under-deduction, while an excess is the payee's to
    reclaim under section 199. Withholding is the safe direction, which is the
    direction `domain/tds/section_rates` already takes on a rate nobody has
    read off the Finance Act.

THE CHECK DIGIT, NOT A SHAPE

    `domain/gst/gstin.problem_with` is the authority and every transposition
    inside the PAN passes a shape regex — 27AAPFU0939F1ZV and 27AAPFU0399F1ZV
    are both well-formed and only one is a real registration. A Tally import
    is a bulk import of a GSTIN a human typed, which is exactly the population
    that rule exists for. The value is normalised the way every other door
    normalises it (stripped and upper-cased) before it is judged, because a
    Tally field routinely carries trailing whitespace and lower case, and a
    party whose only fault is a stray space should not lose their
    registration.

WHAT THIS DOES NOT DO

    It does not compare the GSTIN's state code against the party's own
    recorded state, as `models/parties` does: a Tally LEDGER carries no state
    field, so there is nothing to compare against and inventing one would be a
    guess about where the customer is. The first two characters are still
    tested against the GST state list, because `problem_with` does that on the
    GSTIN's own account.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.validators import validate_pan
from domain.gst.gstin import problem_with as gstin_problem


@dataclass(frozen=True)
class ResolvedIdentifiers:
    """What may be written to the master, and what was held back."""

    gstin: Optional[str] = None
    pan: Optional[str] = None
    #: One sentence per identifier withheld, naming the value and the reason.
    withheld: tuple[str, ...] = field(default_factory=tuple)

    @property
    def anything_withheld(self) -> bool:
        return bool(self.withheld)


def resolve(gstin: Optional[str], pan: Optional[str]) -> ResolvedIdentifiers:
    """Decide which of a Tally party's identifiers may be imported.

    A blank identifier is not a fault — a party who is not registered has no
    GSTIN, and plenty of small suppliers have no PAN on the ledger — so it is
    returned as None with nothing said about it. Only a value that is present
    and wrong is withheld, and each one is named.
    """
    withheld: list[str] = []

    clean_gstin = (gstin or "").strip().upper() or None
    if clean_gstin is not None:
        problem = gstin_problem(clean_gstin)
        if problem:
            withheld.append(
                f"GSTIN {clean_gstin!r} was not imported: {problem} "
                "Supplies to this party will be treated as unregistered (B2C) "
                "until the registration is recorded — CGST Act s.16(2)(aa)."
            )
            clean_gstin = None

    clean_pan = (pan or "").strip().upper() or None
    if clean_pan is not None:
        problem = validate_pan(clean_pan)
        if problem:
            withheld.append(
                f"PAN {clean_pan!r} was not imported: {problem} "
                "Tax on payments to this party will be withheld at the "
                "s.206AA floor until a PAN is recorded."
            )
            clean_pan = None

    return ResolvedIdentifiers(
        gstin=clean_gstin, pan=clean_pan, withheld=tuple(withheld)
    )
