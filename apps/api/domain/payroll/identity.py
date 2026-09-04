"""
A client's own statutory registrations, and what each finished return needs.

WHY THIS MODULE EXISTS

Three statutory outputs in this package are complete and correct and could not
be filed:

    ecr.py      the EPFO Electronic Challan cum Return
    esic.py     the ESIC monthly contribution return
    form24q.py  Form 24Q's Annexure I

Each is a return BY AN ESTABLISHMENT, and until migration 325 this database
held no column for the number that identifies it. routers/tds.py still shows
the shape of the hole: Compute24QRequest takes `tan`, `deductor_name`,
`deductor_pan` and `deductor_address` in the request BODY, because there was
nowhere to read them from — so a CA who has just produced a quarter's deductee
rows from the books retypes the deductor block by hand, every quarter, for
every client.

WHAT IT REFUSES, AND WHAT IT DOES NOT

TAN is validated: `^[A-Z]{4}[0-9]{5}[A-Z]$`, the format TRACES itself rejects
on, and the same well-settled shape as the PAN check clients.pan has carried
since migration 001.

The other four are normalised and stored, and nothing checks their shape. The
EPF establishment code, the ESIC employer code, the state PT numbers and the
Shram Suvidha LIN each have conventions that vary by region, by vintage and by
issuing office. A pattern written from memory would not catch a typo — it would
REFUSE A VALID REGISTRATION somebody is reading off a certificate, with no way
past it. That is the wrong direction of error, and it is the same judgement the
codebase already makes about the MSMED classification, the DTAA treaty rates
and the state PT slabs: where the truth has to come from a human, take what
they give and do not invent a rule that argues with it.

WHERE A MISSING ONE SURFACES IS NOT THE SAME EVERYWHERE

The three returns do not need their identifier in the same way, and treating
them alike would either withhold a file for no reason or emit one that is
unfilable.

    24Q   the TAN is IN the return. Without it there is nothing to file
          against, so it is a PROBLEM and the deductor block is incomplete.
    ECR   the establishment is chosen by the portal login at upload; the file
          itself is member lines only. A missing code does not make the file
          wrong, so it is reported BESIDE the file, never folded into
          ecr.problems — which would flip is_filable and withhold a correct
          return over a piece of reference data.
    ESIC  the same as the ECR, for the same reason.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here transmits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")

#: The four entity-level identifiers, in the order a Setup screen asks for them,
#: with the label a CA would recognise and what it is used for.
ENTITY_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("tan", "TAN",
     "quoted on Form 24Q, every TDS challan and every Form 16 (IT Act s.203A)"),
    ("epf_establishment_code", "EPF establishment code",
     "the establishment the ECR is uploaded under at unifiedportal-emp.epfindia.gov.in"),
    ("esic_employer_code", "ESIC employer code",
     "the employer the monthly contribution return is filed under at esic.gov.in"),
    ("lin", "LIN",
     "the Labour Identification Number used across the Shram Suvidha returns"),
)

_ENTITY_LABELS = {name: label for name, label, _ in ENTITY_FIELDS}


class IdentityError(ValueError):
    """A registration number that cannot be stored as given."""


def normalise_tan(raw: str | None) -> str | None:
    """Uppercase and validate a TAN, or refuse it.

    Returns None for a blank — clearing the field is a legitimate edit, and is
    NOT the same as recording an empty string. Raises IdentityError on anything
    that is not a TAN, because a ten-character string that is not a TAN files
    the quarter against no account, and letting it through to be discovered at
    TRACES is the failure this table exists to end.
    """
    cleaned = (raw or "").strip().upper().replace(" ", "")
    if not cleaned:
        return None
    if not TAN_RE.match(cleaned):
        raise IdentityError(
            f"{cleaned!r} is not a TAN. A TAN is four letters, five digits and "
            "one letter — for example DELM12345F. It is the client's OWN "
            "deduction account number as an employer, not the PAN and not a "
            "customer's TAN.")
    return cleaned


def normalise_code(raw: str | None) -> str | None:
    """Trim a registration number and collapse its whitespace, or None.

    Uppercased because every one of these is issued in upper case and a CA
    typing it in lower is not recording a different number. Punctuation is
    left exactly as given: PT registration numbers carry slashes and hyphens
    that are part of the number.
    """
    cleaned = " ".join((raw or "").strip().split()).upper()
    return cleaned or None


@dataclass(frozen=True)
class Gap:
    """One identifier a return needs and this client has not recorded."""
    field: str
    label: str
    note: str


def _gap(field: str, why: str) -> Gap:
    label = _ENTITY_LABELS.get(field, field)
    return Gap(field=field, label=label,
               note=f"No {label} is recorded for this client. {why} "
                    f"Record it under Payroll -> Statutory identity.")


def ecr_gaps(identity: dict | None) -> list[Gap]:
    """What the ECR is missing. NEVER merged into ECRFile.problems.

    The establishment code is not a field on the file — EPFO knows which
    establishment from the portal login. It is here so the CA can see which
    establishment this file is for before uploading it, and so a client set up
    with no EPF registration at all is visible. Folding it into problems would
    make is_filable false and withhold a correct return.
    """
    if (identity or {}).get("epf_establishment_code"):
        return []
    return [_gap("epf_establishment_code",
                 "The ECR file itself does not carry it — EPFO takes the "
                 "establishment from the portal login — but nothing here can "
                 "tell you which establishment this file belongs to without it.")]


def esic_gaps(identity: dict | None) -> list[Gap]:
    """What the ESIC return is missing. Also never merged into problems."""
    if (identity or {}).get("esic_employer_code"):
        return []
    return [_gap("esic_employer_code",
                 "The contribution file does not carry it — esic.gov.in takes "
                 "the employer from the portal login — but nothing here can "
                 "tell you which employer this file belongs to without it.")]


def deductor_block(identity: dict | None, client: dict | None) -> tuple[dict, list[str]]:
    """Form 24Q's deductor header, and what stops it being filed.

    Returns the four fields routers/tds.py's Compute24QRequest asks for —
    tan, deductor_name, deductor_pan, deductor_address — assembled from the
    statutory identity and the client record, so the CA no longer keys them.

    UNLIKE the ECR and ESIC gaps, a missing TAN here IS a problem: the TAN is
    in the return. A 24Q with a blank TAN is not a return with a small
    omission, it is a return filed against no account.
    """
    ident = identity or {}
    cl = client or {}
    problems: list[str] = []

    tan = ident.get("tan") or ""
    if not tan:
        problems.append(
            "No TAN is recorded for this client, and Form 24Q is filed against "
            "the deductor's TAN (IT Act s.203A). Record it under Payroll -> "
            "Statutory identity before filing this quarter.")

    # legal_name is the name on the registration where it is set; client_name
    # is the working name the firm calls them by. A return carries the former.
    name = (cl.get("legal_name") or cl.get("client_name") or "").strip()
    if not name:
        problems.append("This client has no name recorded, which Form 24Q's "
                        "deductor block requires.")

    pan = (cl.get("pan") or "").strip().upper()
    if not pan:
        problems.append("This client has no PAN recorded, which Form 24Q's "
                        "deductor block requires.")

    address = ", ".join(
        part for part in (
            (cl.get("address_line1") or "").strip(),
            (cl.get("address_line2") or "").strip(),
            (cl.get("city") or "").strip(),
            (cl.get("state") or "").strip(),
            (cl.get("pincode") or "").strip(),
        ) if part)
    if not address:
        problems.append("This client has no address recorded, which Form 24Q's "
                        "deductor block requires.")

    return ({"tan": tan, "deductor_name": name, "deductor_pan": pan,
             "deductor_address": address}, problems)


def pt_registration_gaps(states: set[str] | frozenset[str],
                         registrations: list[dict] | None) -> list[str]:
    """States this run deducts professional tax in with no PTRC recorded.

    Reported ONCE PER STATE, not once per employee: the registration is a fact
    about the employer in that state, so naming it forty times because forty
    people work there would bury the other gaps.

    PTRC specifically, not PTEC. The Registration Certificate is the employer's
    authority to deduct from employees and deposit; the Enrolment Certificate
    is the entity's own levy on itself, payable whether or not it employs
    anybody. Accepting a PTEC in place of a PTRC would report a registration
    that does not cover the deduction the payslip has already made.
    """
    have = {
        (r.get("state") or "").strip().upper()
        for r in (registrations or [])
        if (r.get("ptrc_number") or "").strip()
    }
    return [
        f"Professional tax is being deducted for employees in {state}, and no "
        f"PT registration certificate (PTRC) is recorded for that state. The "
        f"employer cannot deposit what it has deducted without one. Record it "
        f"under Payroll -> Statutory identity."
        for state in sorted(set(states) - have)
    ]
