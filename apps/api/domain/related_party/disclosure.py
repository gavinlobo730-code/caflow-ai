"""WHO IS A RELATED PARTY, AND WHAT THE NOTE HAS TO SAY ABOUT THEM.

AS 18 *Related Party Disclosures* requires the financial statements to name
every related party, state the nature of the relationship, and — where there
were transactions — describe them with their volume and the amounts
outstanding at the year end. It is a note a statutory audit cannot omit, and
this product held every input for it and produced none of it.

`routers/relationships.py::related_party_report` existed and had ZERO CALLERS
anywhere in `apps/web`, which is the `capital_wip` shape this codebase keeps
finding: built, mounted, reachable by nobody. What it computed also could not
have been rendered — it returned raw `entity_roles` rows carrying an
`entity_id` UUID and no name, so the note would have listed identifiers.

── THE SILENT DROP THIS MODULE EXISTS TO FIX ────────────────────────────────

The old test was a literal set — ``{"Director", "Shareholder", "Partner",
"Trustee", "Guarantor", "related_party"}`` — against a role the client screen
lets a CA choose from ELEVEN values. So a **Karta of an HUF**, a
**Proprietor** and a **Beneficiary** of a trust were dropped from the
disclosure without a word. A note that omits a related party is a WRONG
disclosure, which is worse than no note at all: the reader believes it is
complete.

── THREE ANSWERS, NOT TWO, AND THE THIRD IS THE POINT ───────────────────────

A role resolves to `INCLUDED`, `EXCLUDED` or `UNDETERMINED`, and every answer
carries its own reason:

  INCLUDED      the role is a related party by its own nature — a director is
                key management personnel, a proprietor IS the enterprise.
  EXCLUDED      the role does not by itself make somebody a related party. A
                **guarantor** is the clear case: a bank guaranteeing a loan is
                not a related party, and a director who guarantees one is
                already caught as a director.
  UNDETERMINED  the role MIGHT. An **authorised signatory** may be a person
                who plans and directs the enterprise, or a clerk who signs
                cheques; AS 18's key-management test is about authority and
                responsibility, which no column holds. Naming it is the only
                honest answer — guessing IN puts a stranger in a statutory
                note, guessing OUT hides a director who happens to be
                recorded under that label.

A SHAREHOLDER IS THE SUBTLE ONE AND IT IS NOT A ROLE QUESTION AT ALL. AS 18
reaches a shareholder whose interest gives control or significant influence,
not everybody on the register — so a 1% holder is not a related party and
including them by role would inflate the note. `ownership_percent` decides it
where it is recorded, against `SIGNIFICANT_INFLUENCE_PERCENT`; where it is
NOT recorded the answer is UNDETERMINED and says so, because both guesses are
wrong in the ordinary case.

── WHAT IS REFUSED, AND NAMED ON EVERY ANSWER ───────────────────────────────

AS 18 asks for the VOLUME of transactions, and this module derives it by
matching the party's PAN against `customers.pan` and `vendors.pan` — which is
the identifier a CA matches on by hand. Four things it cannot derive and must
not invent:

  · A related party with NO PAN recorded cannot be matched at all, so their
    transactions are NOT nil — they are unknown, and the party is named.
  · A transaction with a related party who is neither a customer nor a vendor
    (a director's remuneration, a loan repayment, rent paid to a relative)
    runs through the journal, and nothing tags a journal line as related
    party. Named, never estimated.
  · **RELATIVES** (AS 18's own definition reaches a related party's spouse,
    children, parents and siblings) are not modelled — `entities` records a
    person, not a family — so a transaction with a director's wife is
    invisible. This is the largest gap and the note says so.
  · KMP **remuneration**, which Ind AS 24 requires split by category, is in
    payroll and is not linked to an entity.

⚠️ `VERIFIED` IS FALSE AND EVERY THRESHOLD IS `[S]`-GRADED. Egress is refused
at this environment's proxy, so AS 18's text is recorded from knowledge rather
than read. Each constant is pinned exactly by
`tests/test_who_is_a_related_party.py`, so a later correction is a deliberate
edit rather than a drift.

Prepare-only: this module decides and reports. It posts nothing, files
nothing, and produces no signed note.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

#: Whether the statutory positions below were read from a primary source.
#: False — see the module docstring. A test pins every figure exactly.
VERIFIED = False


class Standing(str, Enum):
    """Whether a recorded role makes its holder a related party."""

    INCLUDED = "included"
    EXCLUDED = "excluded"
    UNDETERMINED = "undetermined"


#: AS 23 treats a 20% interest as significant influence, and AS 18 reaches a
#: shareholder whose interest confers control OR significant influence. Stated
#: as a named constant rather than written into a branch, because it is a
#: threshold somebody may need to move and because the answer says which
#: figure it applied.
SIGNIFICANT_INFLUENCE_PERCENT = 20

#: IT Act s.92 — an international transaction with an associated enterprise
#: above this value brings the transfer-pricing provisions into play. In
#: paise, integer, like every other money figure in this product.
TRANSFER_PRICING_THRESHOLD_PAISE = 1_00_00_000_00


@dataclass(frozen=True)
class RoleRule:
    """One recorded role, and what AS 18 makes of it."""

    standing: Standing
    #: Written for a CA, because it is printed beside the party in the note.
    reason: str
    #: True where `ownership_percent` decides the answer rather than the role.
    turns_on_ownership: bool = False


#: Keyed on the role EXACTLY as the client screen records it. A role absent
#: from this map is UNDETERMINED with a reason naming itself, rather than
#: silently dropped — which is what the literal set it replaced did to three
#: real related parties.
ROLE_RULES: dict[str, RoleRule] = {
    "Director": RoleRule(
        Standing.INCLUDED,
        "A director is key management personnel — AS 18 reaches a person with "
        "authority and responsibility for planning, directing and controlling "
        "the enterprise's activities.",
    ),
    "Partner": RoleRule(
        Standing.INCLUDED,
        "A partner participates in the control of the firm.",
    ),
    "Proprietor": RoleRule(
        Standing.INCLUDED,
        "A sole proprietor is the enterprise; the two are not separate persons.",
    ),
    "Karta (HUF)": RoleRule(
        Standing.INCLUDED,
        "The Karta manages the Hindu Undivided Family and is its key "
        "management personnel.",
    ),
    "Trustee": RoleRule(
        Standing.INCLUDED,
        "A trustee controls the trust's affairs.",
    ),
    "Beneficiary": RoleRule(
        Standing.INCLUDED,
        "A beneficiary of the trust is a related party of it.",
    ),
    "Manager": RoleRule(
        Standing.INCLUDED,
        "A manager is named as key managerial personnel by the Companies Act "
        "2013 — but a person recorded here as a departmental or branch manager "
        "is not, so check the appointment before relying on this row.",
    ),
    "Shareholder": RoleRule(
        Standing.UNDETERMINED,
        "AS 18 reaches a shareholder whose interest gives control or "
        "significant influence, not every holder on the register.",
        turns_on_ownership=True,
    ),
    "Authorized Signatory": RoleRule(
        Standing.UNDETERMINED,
        "An authorised signatory may be a person who directs the enterprise or "
        "may only be authorised to sign — AS 18's test is authority over the "
        "enterprise's activities, which this record does not hold.",
    ),
    "Guarantor": RoleRule(
        Standing.EXCLUDED,
        "Guaranteeing a borrowing does not by itself make somebody a related "
        "party; a director who guarantees one is already included as a "
        "director.",
    ),
}

#: The answer for a role this module has no rule for. Its own sentence, so a
#: screen can tell "we have no rule" from "the rule needs a figure".
UNKNOWN_ROLE = RoleRule(
    Standing.UNDETERMINED,
    "This role is not one AS 18 settles on its own — decide whether the "
    "person controls or significantly influences the enterprise.",
)


def standing_for(role: str, ownership_percent: Optional[float]) -> RoleRule:
    """What AS 18 makes of one recorded role.

    `ownership_percent` decides only where the rule says it does. Passing it
    for a director changes nothing, which is deliberate: a director is key
    management personnel whether or not they hold a share.
    """
    rule = ROLE_RULES.get((role or "").strip(), UNKNOWN_ROLE)
    if not rule.turns_on_ownership:
        return rule
    if ownership_percent is None:
        return RoleRule(
            Standing.UNDETERMINED,
            rule.reason + " No holding is recorded against this person, so it "
            "cannot be decided here.",
            turns_on_ownership=True,
        )
    if ownership_percent >= SIGNIFICANT_INFLUENCE_PERCENT:
        return RoleRule(
            Standing.INCLUDED,
            f"A holding of {_pct(ownership_percent)} is at or above the "
            f"{SIGNIFICANT_INFLUENCE_PERCENT}% taken as significant influence.",
            turns_on_ownership=True,
        )
    return RoleRule(
        Standing.EXCLUDED,
        f"A holding of {_pct(ownership_percent)} is below the "
        f"{SIGNIFICANT_INFLUENCE_PERCENT}% taken as significant influence, so "
        "this holding alone does not make them a related party.",
        turns_on_ownership=True,
    )


def _pct(v: float) -> str:
    return f"{v:g}%"


@dataclass(frozen=True)
class Dealings:
    """What a related party transacted, where it could be matched at all.

    `matched_on_pan` is False when the party carries no PAN — and then every
    figure below is NOT nil but UNKNOWN, which is why the flag travels with
    them rather than being inferred from a zero.
    """

    matched_on_pan: bool
    sales_paise: int = 0
    purchases_paise: int = 0
    receivable_paise: int = 0
    payable_paise: int = 0


@dataclass(frozen=True)
class Party:
    """One related party, as the note names them."""

    entity_id: str
    name: str
    pan: Optional[str]
    role: str
    ownership_percent: Optional[float]
    standing: Standing
    reason: str
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    dealings: Optional[Dealings] = None


@dataclass(frozen=True)
class Disclosure:
    """The note, and everything it could not derive."""

    client_id: str
    parties: list[Party]
    #: s.185 — a company advancing a loan to its director. Rows as stored.
    section_185_loans: list[dict]
    #: IT Act s.92 — inter-company loans at or above the threshold.
    transfer_pricing_flags: list[dict]
    #: Entity-to-entity edges touching any of these parties.
    entity_relationships: list[dict]
    #: Sentences a CA must read before relying on the note.
    gaps: list[str] = field(default_factory=list)
    #: Standing positions this module takes, printed with the note.
    notes: list[str] = field(default_factory=list)

    @property
    def included(self) -> list[Party]:
        return [p for p in self.parties if p.standing is Standing.INCLUDED]

    @property
    def undetermined(self) -> list[Party]:
        return [p for p in self.parties if p.standing is Standing.UNDETERMINED]

    @property
    def disclosure_required(self) -> bool:
        """AS 18 asks for the relationship to be disclosed where control
        exists, whether or not there were any transactions — so this turns on
        a related party EXISTING, never on a figure being non-nil."""
        return bool(self.included)


#: Printed on every answer. Each names something the note needs and this
#: product cannot derive, so a nil beside it is never read as "there was none".
STANDING_GAPS: tuple[str, ...] = (
    "A related party's RELATIVES are not recorded — this product holds a "
    "person, not a family — so a transaction with a director's spouse, "
    "child, parent or sibling does not appear below.",
    "Transactions that are not a sale or a purchase (director's remuneration, "
    "rent, a loan repayment) run through the journal, and no journal line "
    "records that its counterparty is a related party. They are not below.",
    "Key management personnel remuneration is in payroll and is not linked to "
    "an entity, so it is not totalled here.",
)

#: Positions this module takes deliberately, printed beside the note so a
#: reviewer can see them rather than having to infer them.
STANDING_NOTES: tuple[str, ...] = (
    "Transactions are matched on the party's PAN against the customer and "
    "vendor masters. A party with no PAN recorded is named with no figures — "
    "that is unknown, not nil.",
    "This is an AS 18 note. Ind AS 24 asks for more, including key management "
    "personnel compensation by category, and is not produced here.",
    "Prepared for review. Nothing here is filed, signed or posted.",
)


def build(
    *,
    client_id: str,
    parties: list[Party],
    section_185_loans: list[dict],
    transfer_pricing_flags: list[dict],
    entity_relationships: list[dict],
    extra_gaps: Optional[list[str]] = None,
) -> Disclosure:
    """Assemble the note. Decides nothing a caller has not already resolved
    through `standing_for` — this exists so the gap list cannot be forgotten
    by a caller building the dataclass directly."""
    gaps = list(STANDING_GAPS)
    unmatched = [p.name for p in parties
                 if p.standing is Standing.INCLUDED
                 and (p.dealings is None or not p.dealings.matched_on_pan)]
    if unmatched:
        gaps.append(
            "No PAN is recorded for " + ", ".join(sorted(unmatched)) +
            ", so their transactions could not be matched. The figures beside "
            "them are absent rather than nil."
        )
    undecided = [f"{p.name} ({p.role})" for p in parties
                 if p.standing is Standing.UNDETERMINED]
    if undecided:
        gaps.append(
            "Whether these are related parties could not be decided from what "
            "is recorded: " + ", ".join(sorted(undecided)) +
            ". They are listed apart and are NOT in the note above."
        )
    gaps.extend(extra_gaps or [])
    return Disclosure(
        client_id=client_id,
        parties=parties,
        section_185_loans=section_185_loans,
        transfer_pricing_flags=transfer_pricing_flags,
        entity_relationships=entity_relationships,
        gaps=gaps,
        notes=list(STANDING_NOTES),
    )
