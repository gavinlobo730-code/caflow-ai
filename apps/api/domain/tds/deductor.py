"""
The deductor block a TDS statement is filed under, resolved from what the
platform holds — and refused, by name, when it holds nothing.

WHAT WAS WRONG (probe pass §2.2, 12 September; no finding)

    `apps/web/app/tds/returns/page.tsx` assembled the whole return in the
    browser, and it had nowhere to read the deductor's identity from, so it
    invented one:

        const tan = "MUMB00000A";  // placeholder — must be configured per client
        deductor_pan: "AAAAA0000A",
        deductor_address: "Address not configured",

    Both literals are the right SHAPE — four letters, five digits, one letter
    for the TAN; five letters, four digits, one letter for the PAN — so
    `tds_computer._validate_26q`, which checks only `len(...) != 10`, passed
    them, the payload validated clean, and the return was saved to
    `tds_returns` as `status: "prepared"` under a TAN belonging to nobody.

    That is worse than the CA re-typing it (TDS-28): a re-typed TAN is a
    number the CA saw. This one never appeared on screen. A quarter filed
    against a wrong TAN is filed against somebody else's account — the
    deductees get no credit, and §200/§201 exposure sits with the deductor
    who did deduct.

WHAT MIGRATION 325 ALREADY DECIDED, AND THIS FINALLY READS

    `client_statutory_identity` was created for exactly this, and its own
    header says so:

        "The visible consequence is routers/tds.py: Compute24QRequest takes
         `tan`, `deductor_name`, `deductor_pan` and `deductor_address` in the
         REQUEST BODY, because there was nowhere to read them from."

    There is now. The TAN is `client_statutory_identity.tan` (format-CHECKed
    by the migration), the PAN and the postal address are the client's own
    columns, and the deductor's name is the client's legal name where one is
    recorded and its display name otherwise.

ABSENT IS NOT BLANK, AND THAT IS THE WHOLE POINT

    Every identifier is nullable with no default, so `resolve` returns what it
    found and NAMES what it did not, and the caller refuses. Substituting a
    plausible string is the defect this module exists to end; substituting an
    empty one only moves it, because a statement with a blank TAN is not a
    return with a small omission — it is a return filed against no account.

    A value the CALLER supplies still wins. The per-client compliance tab has
    always taken the block on a form, and a client whose registrations are not
    yet recorded has no other way to compute a quarter. What the caller may
    not do is supply nothing and get something.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: IT Act s.203A. Four letters, five digits, one letter — the same shape
#: migration 325 CHECKs the stored column on, restated here because this
#: module also validates a value the CALLER supplied, which never went
#: through that CHECK.
TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")

#: IT Act s.139A. Five letters, four digits, one letter — `clients.pan` has
#: carried this CHECK since migration 001.
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

GAP_TAN_MISSING = "deductor_tan_missing"
GAP_TAN_MALFORMED = "deductor_tan_malformed"
GAP_PAN_MISSING = "deductor_pan_missing"
GAP_PAN_MALFORMED = "deductor_pan_malformed"
GAP_NAME_MISSING = "deductor_name_missing"
GAP_ADDRESS_MISSING = "deductor_address_missing"

GAP_MESSAGES: dict[str, str] = {
    GAP_TAN_MISSING:
        "This client has no TAN recorded, and a TDS statement is filed under "
        "one (IT Act s.203A). Record it in Payroll → Statutory Identity, or "
        "type it on the compute form. It is not defaulted: a quarter filed "
        "under the wrong TAN credits somebody else's deductees.",
    GAP_TAN_MALFORMED:
        "The TAN is not in the form TRACES accepts — four letters, five "
        "digits, one letter (e.g. MUMD12345E). Check it against the "
        "allotment letter.",
    GAP_PAN_MISSING:
        "This client has no PAN recorded, and the deductor's PAN is part of "
        "every TDS statement. Record it on the client before computing the "
        "quarter.",
    GAP_PAN_MALFORMED:
        "The deductor's PAN is not in the form the portal accepts — five "
        "letters, four digits, one letter (e.g. AABCT1332L).",
    GAP_NAME_MISSING:
        "This client has no name recorded, which cannot normally happen. The "
        "deductor's name appears on the statement and on every Form 16A "
        "issued from it.",
    GAP_ADDRESS_MISSING:
        "This client has no postal address recorded, and the deductor's "
        "address is part of the statement. Add it on the client — the "
        "address lines, city, state and PIN are all used.",
}


@dataclass(frozen=True)
class Deductor:
    """The four fields every TDS statement carries about who deducted."""
    tan: str
    name: str
    pan: str
    address: str


def gaps_with_messages(codes) -> list[dict]:
    """The same shape `residency.gaps_with_messages` returns, for the same
    reason: a code alone tells a CA nothing about what to do next."""
    return [{"code": c, "message": GAP_MESSAGES.get(c, "")} for c in (codes or [])]


def _clean(value) -> str:
    return str(value or "").strip()


def format_address(client: Optional[dict]) -> str:
    """The client's postal address as one line, or "" when nothing is recorded.

    Assembled from the five columns migration 001 gave `clients` rather than
    from a single free-text field, because there is no single field — and the
    parts are joined with ", " in the order an Indian postal address is written,
    with the PIN last and unseparated from the state by a comma, which is how
    it is printed on a letterhead.
    """
    c = client or {}
    parts = [_clean(c.get("address_line1")), _clean(c.get("address_line2")),
             _clean(c.get("city"))]
    tail = " ".join(p for p in (_clean(c.get("state")), _clean(c.get("pincode"))) if p)
    if tail:
        parts.append(tail)
    return ", ".join(p for p in parts if p)


def deductor_name(client: Optional[dict]) -> str:
    """The name the statement carries.

    `clients.legal_name` (migration 003) where one is recorded, and
    `client_name` otherwise. The legal name is what appears on the PAN card
    and therefore what TRACES matches on; `client_name` is the display name a
    firm uses in its own lists and is frequently a short form.
    """
    c = client or {}
    return _clean(c.get("legal_name")) or _clean(c.get("client_name"))


def resolve(
    identity: Optional[dict],
    client: Optional[dict],
    *,
    tan: Optional[str] = None,
    name: Optional[str] = None,
    pan: Optional[str] = None,
    address: Optional[str] = None,
) -> tuple[Optional[Deductor], list[str]]:
    """The deductor block, or None with the codes naming why not.

    `identity` is a `client_statutory_identity` row (or {}), `client` a
    `clients` row. The four keyword arguments are what the CALLER supplied;
    each wins over the store when it is non-blank, and is validated on the way
    through — a caller-supplied TAN has never been near migration 325's CHECK.

    Returns `(None, codes)` when anything is missing or malformed, never a
    partly-filled block: a statement is filed under all four or under none.
    """
    ident = identity or {}
    resolved_tan = (_clean(tan) or _clean(ident.get("tan"))).upper()
    resolved_pan = (_clean(pan) or _clean((client or {}).get("pan"))).upper()
    resolved_name = _clean(name) or deductor_name(client)
    resolved_address = _clean(address) or format_address(client)

    codes: list[str] = []
    if not resolved_tan:
        codes.append(GAP_TAN_MISSING)
    elif not TAN_RE.match(resolved_tan):
        codes.append(GAP_TAN_MALFORMED)
    if not resolved_pan:
        codes.append(GAP_PAN_MISSING)
    elif not PAN_RE.match(resolved_pan):
        codes.append(GAP_PAN_MALFORMED)
    if not resolved_name:
        codes.append(GAP_NAME_MISSING)
    if not resolved_address:
        codes.append(GAP_ADDRESS_MISSING)

    if codes:
        return (None, codes)
    return (Deductor(tan=resolved_tan, name=resolved_name,
                     pan=resolved_pan, address=resolved_address), [])


def refusal_detail(codes) -> str:
    """One sentence per gap, for the 422 body.

    The codes are joined rather than summarised because each names a
    DIFFERENT thing somebody has to go and record, and a CA who is told only
    "the deductor details are incomplete" has to guess which.
    """
    return " ".join(GAP_MESSAGES.get(c, c) for c in (codes or []))
