"""PF contributed on ACTUAL wages above the ceiling, because the employer says it is.

WHAT THIS IS, AND THE ONE THING IT DOES NOT KNOW

    EPF Scheme 1952, para 26(6), lets an employee and the employer jointly
    contribute on wages ABOVE the statutory ceiling (Rs 15,000 today, from
    domain/payroll/statutory.py — never restated here). Many employers do: 12%
    of the whole of basic, not 12% of Rs 15,000. `_compute_pf` always capped,
    and so did the ECR builder, so such an employer had a payroll that
    under-deducted, a ledger that under-accrued and a return that declared the
    wrong EPF wage, with no way to say otherwise.

    [S] — EVERY STATEMENT OF LAW IN THIS MODULE IS SECONDARY-SOURCED. Egress is
    refused in the environment this was written in, so para 26(6), the EPS
    wage ceiling, the EDLI ceiling and the base of the administrative charge
    are written from knowledge and PINNED by tests so a later change is a
    deliberate act. `VERIFIED` is False and the screen says so. What nobody has
    read here is whether the joint request is REQUIRED in law in every case,
    what form it takes, whether EPFO accepts it for a particular member, and
    whether the Code on Social Security 2020 carries the paragraph forward in
    the same words.

    So the product records THE EMPLOYER'S ASSERTION and does nothing cleverer:
    a boolean, an optional date from which it applies, and an optional
    reference to wherever the request is kept. It never infers an election —
    not from wages above the ceiling, not from an earlier month's contribution,
    not from anything on the employee — because an election inferred is a
    deduction nobody agreed to made out of somebody's pay, and an election
    missed is a contribution on the ceiling, which is the position of the law
    until somebody says otherwise.

PER EMPLOYEE, NOT PER ESTABLISHMENT OR PER CLIENT

    The request is JOINT: it is the employee's as much as the employer's, and
    EPFO treats contribution above the ceiling as a fact about the MEMBER. An
    establishment-wide switch would silently decide for every employee,
    including the ones who never asked and the ones hired next year. So the
    columns are on `payroll_employees` and nothing generalises them.

THREE STATES, AND THE THIRD IS THE ABSENCE OF A VALUE

    `pf_on_actual_wages` is NULL (never recorded — the statutory default, the
    ceiling), TRUE (elected) or FALSE (an election was recorded and has been
    withdrawn). NULL and FALSE compute identically; they differ because "nobody
    said" and "somebody withdrew it" are different facts to read back, the
    `vendors.msme_status` and `fixed_assets.rule_43_use` discipline. There is no
    default on the column and no backfill, so every employee that exists today
    is NULL and computes exactly what it computed before.

WHAT CHANGES FOR AN ELECTED MEMBER, AND WHAT DELIBERATELY DOES NOT

    Moves, because they follow the EPF wage:
      * the employee's 12% and the employer's 12% — on the whole PF wage;
      * the employer's EPF half, which absorbs everything above the pension
        diversion;
      * the EPF administrative charge, whose base follows the EPF wage [S] —
        the ECR challan raises it on EPF wages;
      * the ECR's EPF wage column.

    Does NOT move:
      * EPS wages and the EPS contribution — the pension scheme keeps its own
        ceiling, so the diversion stays at 8.33% of Rs 15,000 (Rs 1,250);
      * EDLI wages and the EDLI contribution — EDLI Scheme 1976's ceiling;
      * the wage BASE itself. The uncapped figure is the SAME base the capped
        path takes — Basic + DA before 21-11-2025, the Code on Social Security
        s.2(88) aggregate after it (domain/payroll/wage_base.py) — so the
        pre-commencement branch keeps its own figure.
      * rounding. Contributions round exactly as `_compute_pf` always rounded
        them; this module touches no rounding.
      * ESI. Deliberately untouched, as CLAUDE.md records.

NOT MODELLED, AND NAMED RATHER THAN GUESSED  (see NOT_MODELLED)

    The higher-pension option under EPS para 11(3) and the Supreme Court's 2022
    judgment is a different thing — a joint option exercised with EPFO, with its
    own validation and its own contribution — and is REFUSED here. EPS wages
    stay at the ceiling for every member.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here transmits anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from domain.payroll import wage_base

#: A claim about PROVENANCE, not confidence. False: nothing below was read from
#: the Scheme, the Code or a notification; see the module docstring.
VERIFIED = False

PARA = "EPF Scheme 1952, para 26(6)"

# The three columns, named once. models/payroll.py, the router and the ECR guard
# all read these, so a rename is one edit and a typo is an import error.
ELECTION = "pf_on_actual_wages"
EFFECTIVE_FROM = "pf_on_actual_wages_from"
REFERENCE = "pf_on_actual_wages_reference"
DETAIL_KEYS = (EFFECTIVE_FROM, REFERENCE)
ALL_KEYS = (ELECTION, EFFECTIVE_FROM, REFERENCE)

REFERENCE_MAX_CHARS = 200

#: Before the Scheme itself (framed 1952) is not a date anybody elected anything.
#: It refuses the absurd year ("1926" for "2026") and nothing else: a past date
#: that is merely early reads as "applies to every month", which is what no date
#: means, so it cannot harm.
EARLIEST_EFFECTIVE_FROM = date(1952, 1, 1)

#: The sentence the employee form shows. It is held HERE and pinned into the
#: component from the Python side (tests/test_pf_on_actual_wages_...), because a
#: guard written in apps/web would assert the screen against a copy of itself.
#: No apostrophes and no markup, so the source can carry it character for
#: character.
SCREEN_NOTICE = (
    "This records a statement by the employer that the employee and the "
    "employer have jointly asked to contribute on wages above the statutory "
    "ceiling (EPF Scheme 1952, para 26(6)). This product does not check that "
    "the request exists, whether it is required here, or whether EPFO will "
    "accept it: that is for the employer to establish. The reading of the "
    "paragraph is unverified. Pension (EPS) wages, EDLI wages and the EDLI "
    "limit stay at the ceiling, and the higher-pension option under the "
    "Pension Scheme is not modelled."
)

#: What the product does not do about this, each a refusal with its reason.
NOT_MODELLED: tuple[str, ...] = (
    "The higher-pension option under the Employees' Pension Scheme 1995 "
    "(para 11(3), as the Supreme Court read it in 2022) is a different joint "
    "option exercised with EPFO, with its own validation. EPS wages stay at "
    "the ceiling for every member, elected or not.",
    "Contribution on an amount the employer picks between the ceiling and "
    "actual wages. The election here is all or nothing: the whole PF wage.",
    "Whether the Code on Social Security 2020 carries para 26(6) forward in "
    "the same words. It was not read.",
    "The joint request as a document. Only the employer's assertion, an "
    "optional date and an optional reference are held; nothing is uploaded, "
    "checked or sent to EPFO.",
    "Whether EPFO validates the administrative charge on the uncapped EPF wage "
    "for these members. The charge here follows the EPF wage [S].",
)

#: Beside the ECR, once per file that carries an elected member.
ECR_WARNING = (
    "{n} member(s) in this file are declared on actual wages above the ceiling "
    "because the employer recorded an election to contribute on them. Their EPS "
    "wages and EDLI wages stay at the ceiling. Whether EPFO accepts "
    "contribution above the ceiling for them is not checked here: the employer "
    "must hold the joint request (EPF Scheme para 26(6), unverified reading)."
)


# ── Reading a recorded election ──────────────────────────────────────────────

def state_of(election) -> str:
    """'unrecorded' (NULL), 'elected' (true) or 'withdrawn' (false).

    Strictly `is True` / `is False`: PostgREST returns a JSON boolean, and a
    truthy string or a 1 from a fixture is not an election. The two non-elected
    states compute identically — see the module docstring for why they stay two.
    """
    if election is True:
        return "elected"
    if election is False:
        return "withdrawn"
    return "unrecorded"


def _as_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def applies(emp: dict, *, fy_label: Optional[str], month: Optional[int]) -> bool:
    """Whether PF is contributed on ACTUAL wages for this employee in this month.

    All three must hold, and each is the safe direction when it fails — the
    ceiling, which is the position of the law until an election is made:

      * PF applies to the employee at all;
      * the election is recorded as TRUE (NULL and FALSE are both the ceiling);
      * the month is on or after the date the election takes effect. A month is
        paid as ONE thing, so it is tested on its END — a request dated the
        15th governs that month's whole wage, which is how
        `wage_base.rule_in_force` treats the month the Codes commenced in. A
        month ending before the date is capped, so a draft for an earlier month
        recomputed after the election was recorded does not reach back before
        the request.

    No date recorded means every month. That is the employer's own statement
    with nothing narrower in it, and the screen says so.

    A date that is recorded and cannot be read, or a month this cannot place,
    is NOT guessed into an election: it answers False (the ceiling).
    """
    if not emp.get("pf_applicable"):
        return False
    if emp.get(ELECTION) is not True:
        return False
    raw = emp.get(EFFECTIVE_FROM)
    if raw in (None, ""):
        return True
    start = _as_date(raw)
    if start is None:
        return False
    end = wage_base.month_end(fy_label, month)
    if end is None:
        return False
    return end >= start


# ── Cleaning what a person typed ─────────────────────────────────────────────

def clean_effective_from(raw) -> Optional[str]:
    """An ISO date, or None for blank. Raises ValueError with a sentence."""
    if raw is None:
        return None
    if isinstance(raw, (date, datetime)):
        value = _as_date(raw)
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            value = date.fromisoformat(text)
        except ValueError:
            raise ValueError(
                "The date the election takes effect must be a date written "
                "YYYY-MM-DD.") from None
    if value is None or value < EARLIEST_EFFECTIVE_FROM:
        raise ValueError(
            "The date the election takes effect is not a plausible date for "
            "an election under the EPF Scheme (1952). Check the year.")
    return value.isoformat()


def clean_reference(raw) -> Optional[str]:
    """The employer's own reference for the joint request, or None for blank.

    Free text kept as typed (collapsed whitespace, no control characters): it is
    the employer's words about a document that may only exist on paper — the
    `proof_reference` discipline. Not a URL, not an upload.
    """
    if raw is None:
        return None
    text = " ".join("".join(
        ch if ch.isprintable() else " " for ch in str(raw)).split())
    if not text:
        return None
    if len(text) > REFERENCE_MAX_CHARS:
        raise ValueError(
            f"The reference for the joint request may be at most "
            f"{REFERENCE_MAX_CHARS} characters.")
    return text


# ── Consistency: one rule, asked at every door ───────────────────────────────

def problems(*, pf_applicable: Optional[bool], election, effective_from,
             reference) -> list[str]:
    """What is wrong with this COMPLETE election state, in sentences.

    Asked of the whole state at create, and of the stored row merged with the
    request at PATCH, so a validator is never only at one door. The database
    holds the same two rules as CHECK constraints (migration 477) as the last
    line for a write that skipped the API.
    """
    out: list[str] = []
    if election is True and pf_applicable is False:
        out.append(
            "PF is not applicable to this employee, so an election to "
            "contribute on actual wages above the ceiling has nothing to apply "
            "to. Switch PF on, or withdraw the election.")
    if election is not True and (effective_from or reference):
        out.append(
            "A date or a reference was given for an election that is not "
            "recorded as made. Record the election, or leave both blank.")
    return out


@dataclass(frozen=True)
class UpdatePlan:
    """What a PATCH must also write, and what is wrong with it."""
    changes: dict
    problems: list[str]


def needs_stored_row(patch: dict) -> bool:
    """Whether a PATCH can conflict with what is stored, so the row is read.

    An election key always can; `pf_applicable` only when it is being switched
    OFF (switching it on cannot contradict an election, because the database
    refuses an election beside PF off). Asked so a PATCH that touches neither
    never reads, or names, the new columns.
    """
    if any(k in patch for k in ALL_KEYS):
        return True
    return patch.get("pf_applicable") is False


def plan_update(stored: dict, patch: dict) -> UpdatePlan:
    """Resolve a PATCH against the row it lands on.

    `patch` is the request with Nones dropped (`exclude_none`), which is why a
    blank date or reference arrives as "" and means CLEAR — PATCH cannot send a
    null. Withdrawing the election (false) clears the date and the reference
    with it, because the database holds them only beside an election that is
    true; the old values are in the edit log the router writes.
    """
    if not needs_stored_row(patch):
        return UpdatePlan({}, [])
    changes: dict = {}
    for key in DETAIL_KEYS:
        if key in patch:
            changes[key] = patch[key] or None
    if patch.get(ELECTION) is False:
        for key in DETAIL_KEYS:
            if not patch.get(key):
                changes[key] = None
    merged_from = changes[EFFECTIVE_FROM] if EFFECTIVE_FROM in changes \
        else stored.get(EFFECTIVE_FROM)
    merged_reference = changes[REFERENCE] if REFERENCE in changes \
        else stored.get(REFERENCE)
    return UpdatePlan(
        changes,
        problems(
            pf_applicable=patch.get("pf_applicable", stored.get("pf_applicable")),
            election=patch.get(ELECTION, stored.get(ELECTION)),
            effective_from=merged_from,
            reference=merged_reference,
        ),
    )
