"""Which GST registrations a client holds (GST-20).

A CLIENT IS ONE ENTITY AND MAY HOLD SEVERAL REGISTRATIONS.
CGST Act s.25(1) requires registration in EVERY State or Union territory from
which a taxable supply is made, and s.25(2)'s proviso lets a person take a
separate registration for each PLACE OF BUSINESS within one state. So a
manufacturer with a depot, a services firm with two offices, an e-commerce
seller holding warehouse-state registrations — all one legal person, several
GSTINs, several sets of returns.

`clients.gstin` held exactly one, and both return tables were UNIQUE on
`(client_id, period)`, so a second registration could not have its own GSTR-1 or
GSTR-3B ROW whatever the code did. The CA's only route was a second fake
"client" per GSTIN, which then splits the ACCOUNTING of one entity across two
ledgers and breaks every client-scoped report.

WHY `clients.gstin` IS NOT REPLACED, AND THIS IS THE PART TO READ BEFORE
"TIDYING" IT. It stays the PRIMARY registration and remains the only place the
primary is stored. Around thirty callers read it — the invoice PDF, the
purchase-bill place of supply, the engagement letter, search, onboarding — and
every one of them wants the client's MAIN GSTIN, which is what they will still
get. `client_gst_registrations` (migration 390) holds the ADDITIONAL ones ONLY.

    That is a deliberate choice against the obvious alternative, which is to
    move every registration into the table and leave `clients.gstin` as a cache
    of the primary. A cache needs one write path, and `clients.gstin` already
    has several — onboarding, the client edit screen, the seed in migration 073
    — so it would drift the first time somebody edited a client, silently, and
    the drift would show up as a return filed under the wrong registration. A
    denormalised copy nobody can keep honest is worse than no copy.

So: the primary is `clients.gstin`; the rest are rows; `all_registrations`
presents the union in one shape and nothing else has to know the difference.

WHAT THIS MODULE DOES NOT DO. It reads nothing and writes nothing. Which
registration a RETURN belongs to is `gstr1_returns.gstin` /
`gstr3b_returns.gstin` — columns that existed from migration 036 and were
simply never varied, because the unique key forbade it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: What s.25 lets a registration BE. The portal's own vocabulary, and the value
#: decides which returns are due at all — a composition dealer files CMP-08 and
#: GSTR-4, not GSTR-1 and GSTR-3B, which is why `files_gstr1_and_3b` exists
#: rather than every caller testing the string.
REGULAR = "regular"
COMPOSITION = "composition"
CASUAL = "casual_taxable_person"
ISD = "input_service_distributor"
SEZ_UNIT = "sez_unit"
SEZ_DEVELOPER = "sez_developer"
TDS_DEDUCTOR = "tds_deductor"
TCS_COLLECTOR = "tcs_collector"
NON_RESIDENT = "non_resident_taxable_person"

REGISTRATION_TYPES = (
    REGULAR, COMPOSITION, CASUAL, ISD, SEZ_UNIT, SEZ_DEVELOPER,
    TDS_DEDUCTOR, TCS_COLLECTOR, NON_RESIDENT,
)

#: The types that file GSTR-1 and GSTR-3B. Everything else files something this
#: product does not build (GST-25), and saying so is the point: a composition
#: dealer given a GSTR-3B screen is offered a return they must not file.
#:
#: An SEZ UNIT and an SEZ DEVELOPER file the ordinary pair — they are ordinary
#: registered persons whose supplies are zero-rated under IGST s.16, not a
#: different return regime. A CASUAL and a NON-RESIDENT taxable person do too
#: (s.27 shortens the validity, it does not change the forms).
FILES_GSTR1_AND_3B = frozenset({
    REGULAR, CASUAL, SEZ_UNIT, SEZ_DEVELOPER, NON_RESIDENT,
})

#: Why each of the others does not, in the CA's own words. Held as data so the
#: refusal names the form the registration actually owes rather than saying
#: only that this one is unavailable.
OTHER_RETURN_FORMS = {
    COMPOSITION: ("a composition dealer pays under s.10 and files CMP-08 "
                  "quarterly with GSTR-4 annually, not GSTR-1 and GSTR-3B"),
    ISD: ("an Input Service Distributor distributes credit under s.20 and "
          "files GSTR-6"),
    TDS_DEDUCTOR: ("a s.51 deductor files GSTR-7"),
    TCS_COLLECTOR: ("a s.52 e-commerce operator files GSTR-8"),
}

MONTHLY = "monthly"
QUARTERLY = "quarterly"
FILING_FREQUENCIES = (MONTHLY, QUARTERLY)


@dataclass(frozen=True)
class Registration:
    """One GSTIN a client holds.

    `is_primary` is not a column on the additional rows — it is TRUE for the one
    synthesised from `clients.gstin` and FALSE for every row. A caller that
    needs "the client's GSTIN" in the old sense takes the primary.
    """
    gstin: str
    state_code: str
    registration_type: str = REGULAR
    filing_frequency: str = MONTHLY
    is_primary: bool = False
    #: None on the primary — `clients` has no registration row to point at.
    id: Optional[str] = None
    trade_name: Optional[str] = None
    effective_from: Optional[str] = None
    #: s.29 cancellation or surrender. A cancelled registration still owes the
    #: returns for the periods it was live, so it is never hidden — only
    #: reported as closed.
    effective_to: Optional[str] = None
    #: Which s.10 rate a COMPOSITION registration pays (GST-25, migration 420).
    #: Meaningless unless `registration_type == COMPOSITION`, and NULL there
    #: means unrecorded rather than any particular rate — see
    #: `domain/gst/composition.py`, which is the one place that reads this.
    composition_category: Optional[str] = None

    @property
    def files_gstr1_and_3b(self) -> bool:
        return self.registration_type in FILES_GSTR1_AND_3B

    @property
    def files_cmp08(self) -> bool:
        """Whether this registration owes FORM GST CMP-08 (GST-25) — the same
        boolean-not-a-string-comparison shape as `files_gstr1_and_3b`, so the
        browser never has to hardcode the word "composition" to decide whether
        to offer the panel."""
        return self.registration_type == COMPOSITION

    @property
    def files_gstr8(self) -> bool:
        """Whether this registration owes FORM GSTR-8 (GST-25) — a s.52
        e-commerce operator's TCS statement. Same shape as `files_cmp08`: the
        browser is never told to compare against the string "tcs_collector"."""
        return self.registration_type == TCS_COLLECTOR

    @property
    def files_gstr4_annual(self) -> bool:
        """Whether this registration owes FORM GSTR-4 Annual (GST-25) — the
        same COMPOSITION registrations that file CMP-08 quarterly also file
        this annually (Rule 80(3)), so the value always equals `files_cmp08`.
        Kept as its own boolean rather than reused under a different name for
        the same reason `files_gstr8` is not spelled as a string comparison:
        the browser must never infer one return's eligibility from another's
        property name coinciding with it today."""
        return self.registration_type == COMPOSITION

    @property
    def label(self) -> str:
        """What to show in a picker. The GSTIN is the identity; the trade name
        is what a human recognises, and a client with three registrations in one
        state is told apart only by it."""
        bits = [self.gstin]
        if self.trade_name:
            bits.append(self.trade_name.strip())
        if self.is_primary:
            bits.append("primary")
        return " · ".join(bits)


def state_code_of(gstin: str) -> str:
    """The first two characters — CGST s.25 makes a registration state-wise.

    THE PREFIX, not `gstin.state_code`: the question is WHICH state, and
    falling through on a bad check digit would leave the registration stateless
    rather than merely unverified. `place_of_supply` takes the prefix for the
    same reason and says so.
    """
    return (gstin or "").strip()[:2]


def primary_of(client: dict[str, Any]) -> Optional[Registration]:
    """The registration `clients.gstin` names, or None where the client has no
    GSTIN at all (the column is nullable — an unregistered client is real)."""
    gstin = (client.get("gstin") or "").strip().upper()
    if not gstin:
        return None
    return Registration(
        gstin=gstin,
        state_code=(client.get("state_code") or "").strip() or state_code_of(gstin),
        registration_type=((client.get("gst_registration_type") or "").strip().lower()
                           or REGULAR),
        filing_frequency=((client.get("gst_filing_frequency") or "").strip().lower()
                          or MONTHLY),
        is_primary=True,
        trade_name=(client.get("legal_name") or client.get("client_name") or None),
        effective_from=(str(client.get("gst_registration_date"))
                        if client.get("gst_registration_date") else None),
        composition_category=(client.get("composition_category") or None),
    )


def registration_of(row: dict[str, Any]) -> Registration:
    """One `client_gst_registrations` row."""
    gstin = (row.get("gstin") or "").strip().upper()
    return Registration(
        gstin=gstin,
        state_code=(row.get("state_code") or "").strip() or state_code_of(gstin),
        registration_type=(row.get("registration_type") or REGULAR),
        filing_frequency=(row.get("filing_frequency") or MONTHLY),
        is_primary=False,
        id=row.get("id"),
        trade_name=row.get("trade_name"),
        effective_from=(str(row["effective_from"]) if row.get("effective_from") else None),
        effective_to=(str(row["effective_to"]) if row.get("effective_to") else None),
        composition_category=(row.get("composition_category") or None),
    )


def all_registrations(client: dict[str, Any],
                      rows: list[dict[str, Any]]) -> list[Registration]:
    """Every GSTIN this client holds — the primary first, then the rest.

    The PRIMARY FIRST is load-bearing rather than cosmetic: a screen that opens
    on a client picks `[0]`, and that must be the registration every existing
    document already carries, or a CA who never touches the selector starts
    filing under a different GSTIN than yesterday.
    """
    out: list[Registration] = []
    primary = primary_of(client)
    if primary:
        out.append(primary)
    seen = {primary.gstin} if primary else set()
    for row in rows:
        reg = registration_of(row)
        if not reg.gstin or reg.gstin in seen:
            # A row duplicating the primary is refused at the door
            # (`problem_with_new`), so reaching here means data that predates
            # the check. Dropping it is right: one GSTIN, one registration.
            continue
        seen.add(reg.gstin)
        out.append(reg)
    return out


def resolve(client: dict[str, Any], rows: list[dict[str, Any]],
            gstin: Optional[str]) -> Registration:
    """Which registration a request means.

    No `gstin` means the PRIMARY, which is what every caller predating this
    module meant and still means. A `gstin` the client does not hold is an
    error rather than a silent fall back to the primary: filing one
    registration's return under another's number is the failure this whole
    feature exists to prevent.
    """
    regs = all_registrations(client, rows)
    if not regs:
        raise ValueError(
            "This client has no GST registration recorded, so a GST return "
            "cannot be prepared for it. Record the GSTIN on the client first.")
    wanted = (gstin or "").strip().upper()
    if not wanted:
        return regs[0]
    for reg in regs:
        if reg.gstin == wanted:
            return reg
    held = ", ".join(r.gstin for r in regs)
    raise ValueError(
        f"{wanted} is not a GST registration recorded for this client. "
        f"The registrations on file are: {held}. Record it under the client's "
        f"GST registrations before filing under it.")


# ── Adding one ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Refusal:
    """Why a registration cannot be recorded, or None-equivalent when empty."""
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons


def problem_with_new(client: dict[str, Any], existing: list[dict[str, Any]],
                     *, gstin: str, state_code: Optional[str] = None,
                     registration_type: str = REGULAR,
                     filing_frequency: str = MONTHLY,
                     composition_category: Optional[str] = None) -> Refusal:
    """Whether this registration can be added to this client.

    Shape and check digit are `domain/gst/gstin.problem_with`'s — there is one
    implementation of that and this is not a second.
    """
    from domain.gst.gstin import problem_with
    from domain.gst.composition import COMPOSITION_CATEGORIES

    reasons: list[str] = []
    value = (gstin or "").strip().upper()
    if not value:
        reasons.append("A GSTIN is required.")
        return Refusal(reasons)

    shape = problem_with(value)
    if shape:
        reasons.append(shape)

    if registration_type not in REGISTRATION_TYPES:
        reasons.append(
            f"{registration_type!r} is not a registration type. One of: "
            f"{', '.join(REGISTRATION_TYPES)}.")
    if filing_frequency not in FILING_FREQUENCIES:
        reasons.append(
            f"{filing_frequency!r} is not a filing frequency — "
            f"{' or '.join(FILING_FREQUENCIES)}.")
    # Unrecorded is allowed — domain/gst/composition.py treats a missing
    # category as a named gap on the statement, not a reason to refuse the
    # registration itself. An UNRECOGNISED one is still refused, the same as
    # every other enum here.
    if (composition_category is not None
            and composition_category not in COMPOSITION_CATEGORIES):
        reasons.append(
            f"{composition_category!r} is not a composition category. One "
            f"of: {', '.join(COMPOSITION_CATEGORIES)}.")

    # THE STATE IS THE GSTIN'S OWN. A registration is state-wise (s.25(1)), so
    # a state code that disagrees with the number's first two characters is one
    # of them typed wrong, and guessing which would put the supply in the wrong
    # state on every document.
    prefix = state_code_of(value)
    stated = (state_code or "").strip()
    if stated and stated != prefix:
        reasons.append(
            f"The state code {stated} does not match the GSTIN, which begins "
            f"{prefix} — a GST registration is state-wise (CGST Act s.25(1)), "
            f"so one of the two is wrong.")

    held = {r.gstin for r in all_registrations(client, existing)}
    if value in held:
        primary = primary_of(client)
        where = ("the client's primary GSTIN"
                 if primary and primary.gstin == value
                 else "already recorded for this client")
        reasons.append(f"{value} is {where}.")

    return Refusal(reasons)
