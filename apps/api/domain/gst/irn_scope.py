"""
Which supplies must carry an IRN — CGST Rule 48(4), and who has to say.

WHAT WAS WRONG (SALES-18)

    `apps/web/lib/invoices/compliance.ts::irnEligibility` was the ONLY
    implementation of Rule 48(4)'s scope test in this repository. A statutory
    rule living solely in the browser bundle breaks the house rule that
    computation, validation and statutory rules live in `apps/api`, and it is
    what let SALES-17 — the e-way threshold measured on the pre-GST taxable
    value — sit unnoticed: a wrong number in a TypeScript file has no Python
    twin to disagree with it and no parity vector to fail.

    The e-way half of the same finding was closed by MOVING the rule here and
    keeping the browser copy as a pinned mirror (`domain/gst/eway.py` with
    `shared/eway-parity-vectors.json`). This is the IRN half, in the same shape
    and for the same reason: the Compliance panel recomputes on every keystroke
    and a round trip per keystroke is not a panel.

    It also said, on every invoice and to every CA:

        "E-invoicing applies only above your firm's turnover threshold —
         confirm before generating."

    — which is the whole person-side limb of the rule, declined. Nothing held
    an aggregate turnover when that sentence was written. Migration 401 does
    now (GST-17), so the limb is answered here instead of delegated to the
    reader.

THE RULE HAS TWO INDEPENDENT LIMBS AND BOTH MUST HOLD

    Rule 48(4) requires an invoice to be prepared by uploading particulars to
    the Invoice Registration Portal and obtaining an Invoice Reference Number,
    for

        a registered person whose aggregate turnover exceeds the notified
        threshold                                          <- the PERSON limb

        in respect of a supply of goods or services or both to a REGISTERED
        PERSON, or for EXPORT                              <- the SUPPLY limb

    The two are about different things — one is a fact about the client for the
    year, the other a fact about this document — and conflating them is how a
    B2C invoice from a large client gets an IRN prepared for it, or a B2B
    invoice from a small one gets refused. They are computed separately below
    and ANDed once, so each can be reported on its own.

    Rule 48(5) is why the direction of error matters: an invoice that Rule
    48(4) reaches, issued "in any manner other than the manner specified in the
    said sub-rule, shall not be treated as an invoice". Not a penalty — the
    document is not an invoice, so the RECIPIENT's input tax credit goes with
    it. Under-reporting the requirement is therefore the expensive direction,
    and every unknown below is resolved the strict way and FLAGGED.

THE PERSON LIMB IS A RATCHET, NOT THE PRECEDING YEAR

    This is the one thing most likely to be got wrong by reusing the sibling
    rule, so it is stated before the table. Notification 78/2020 (the HSN digit
    rule, `domain/gst/hsn_digits.py`) reads on the turnover "in the preceding
    Financial Year" — one year, and a client who shrinks falls back down a
    band. Rule 48(4) reads on the turnover "in ANY PRECEDING FINANCIAL YEAR
    FROM 2017-18 ONWARDS".

    So e-invoicing LATCHES. A client who crossed ₹20 crore in FY 2022-23 and
    turned over ₹4 crore every year since is still within Rule 48(4), and
    `hsn_digits.governing_financial_year` — which hops to exactly one preceding
    year — is the wrong question here. `qualifying_financial_years` is the
    right one, and the caller takes the HIGHEST figure across them rather than
    the latest.

    It also never latches DOWN: the thresholds have only ever fallen, and a
    client who crossed ₹500 crore in 2019-20 is inside every later one anyway.

THE THRESHOLD FORKED SIX TIMES AND THE INVOICE'S OWN DATE DECIDES

    Rule 48(4) was inserted by Notification 68/2019-Central Tax and notifies
    its class of registered persons by a separate notification, which has been
    superseded downward six times:

        ₹500 crore   from 01-10-2020   Notification 61/2020-CT (amending 13/2020-CT)
        ₹100 crore   from 01-01-2021   Notification 88/2020-CT
        ₹50 crore    from 01-04-2021   Notification 05/2021-CT
        ₹20 crore    from 01-04-2022   Notification 01/2022-CT
        ₹10 crore    from 01-10-2022   Notification 17/2022-CT
        ₹5 crore     from 01-08-2023   Notification 10/2023-CT

    An invoice dated before a step keeps the threshold in force on ITS OWN
    date, indefinitely — the same "fork, not migration" shape as the TDS
    vocabulary, the 23-07-2024 capital-gains fork and the two HSN digit tables.
    A 2021 invoice being looked at today is governed by ₹50 crore, and reading
    today's ₹5 crore onto it would report an IRN was owed on a document for
    which none was.

    Before 01-10-2020 no class had been notified, so Rule 48(4) reached nobody:
    that is a real `not_required`, not an absence.

⚠️  EVERY THRESHOLD AND EVERY DATE ABOVE IS [S]-GRADED. Direct egress is
    refused at this environment's proxy — `.gov.in` included — so all twelve
    figures are written from knowledge rather than read off the notifications,
    `VERIFIED` is False, and
    `tests/test_which_supplies_must_carry_an_irn.py` pins each one exactly so a
    later correction is deliberate rather than a drift. The error direction is
    stated at each unknown below; none of them silently under-reports.

WHAT THIS MODULE REFUSES TO DECIDE

    The first proviso to Rule 48(4) EXEMPTS several classes of registered
    person from e-invoicing however large their turnover, and nothing in this
    product records which class a client is in. That list is named on every
    answer that says an IRN is required (`EXEMPTED_CLASSES`) rather than
    guessed in either direction — the `eway.assess` treatment of Rule 138(14),
    for the same reason: a silent "required" for an exempted class wastes an
    hour, and a silent "not required" for one that is not exempt costs the
    recipient their credit under Rule 48(5).

    An SEZ UNIT is the trap in that list and the two directions are opposite.
    An SEZ unit is exempt AS A SUPPLIER; a supply MADE TO an SEZ unit or
    developer is squarely within the supply limb. One is about who is issuing
    the invoice and the other about who is receiving it, and reading either for
    the other inverts the answer.

    This module decides ELIGIBILITY AND NOTHING ELSE. It mints no IRN, reaches
    no portal and writes nothing: an IRN comes from the IRP and is recorded
    here afterwards by a human (`routers/einvoice.py`).
"""
from __future__ import annotations

from domain.money_text import whole_rupees

from dataclasses import dataclass, field
from typing import Optional

from domain.gst import treatment as _treatment
from domain.gst.gstin import GSTIN_SHAPE

#: Rule 48(4) reads on the turnover in any preceding financial year "from
#: 2017-18 onwards" — GST's own first year. A figure recorded for an earlier
#: year is not a figure this rule can use.
FIRST_QUALIFYING_FY = "2017-18"

#: No class of registered person was notified under Rule 48(4) before this
#: date, so an invoice dated before it owes no IRN whatever the turnover.
COMMENCEMENT = "2020-10-01"

#: (in force from, threshold in paise, the notification that set it), oldest
#: first. Read only through `threshold_for`, which walks it in reverse.
#:
#: ⚠️ [S] — written from knowledge, pinned exactly by the test module named in
#: the header. Note that Notification 70/2019-CT's ₹100 crore from 01-04-2020
#: is deliberately ABSENT: it was superseded by 13/2020-CT before it ever took
#: effect, so no invoice was ever governed by it and putting it here would
#: govern a 2020 invoice by a threshold that never applied to it.
THRESHOLDS: tuple[tuple[str, int, str], ...] = (
    ("2020-10-01", 5_00_00_00_000_00, "Notification 61/2020-Central Tax"),
    ("2021-01-01", 1_00_00_00_000_00, "Notification 88/2020-Central Tax"),
    ("2021-04-01",   50_00_00_000_00, "Notification 05/2021-Central Tax"),
    ("2022-04-01",   20_00_00_000_00, "Notification 01/2022-Central Tax"),
    ("2022-10-01",   10_00_00_000_00, "Notification 17/2022-Central Tax"),
    ("2023-08-01",    5_00_00_000_00, "Notification 10/2023-Central Tax"),
)

#: Everything in this module is written from knowledge rather than read off the
#: notifications, because egress is refused here. A test pins each number.
VERIFIED = False

#: The treatments Rule 48(4)'s supply limb reaches whatever the recipient's
#: registration. DERIVED from the treatment vocabulary rather than listed, so a
#: treatment added to `domain/gst/treatment.py` cannot quietly default to B2C —
#: the same reason `gstr1_builder` derives its B2B set from the classifier.
#:
#: `regular` is the only treatment left out, and it is the only one whose scope
#: turns on the RECIPIENT rather than on the supply: an export or an SEZ supply
#: is in scope even though the buyer holds no GSTIN, which is exactly why the
#: two limbs of `supply_in_scope` cannot be collapsed into one GSTIN test.
SUPPLY_IN_SCOPE_TREATMENTS = frozenset(_treatment.TREATMENTS - {_treatment.REGULAR})

#: The first proviso to Rule 48(4). Named, never guessed — see the header.
EXEMPTED_CLASSES = (
    "a Special Economic Zone UNIT (as the supplier — a supply MADE TO an SEZ "
    "unit or developer is in scope)",
    "an insurer, a banking company or a financial institution including an NBFC",
    "a goods transport agency supplying services in relation to transportation "
    "of goods by road in a goods carriage",
    "a supplier of passenger transportation service",
    "a supplier of services by way of admission to the exhibition of "
    "cinematograph films in multiplex screens",
    "a government department or a local authority",
)

#: The one sentence to show where the client's aggregate turnover is not
#: recorded. Held here rather than written at each call site so the panel and
#: any later screen cannot say different things — `hsn_digits`'
#: TURNOVER_NOT_RECORDED, which this deliberately echoes because it is the same
#: missing figure and the CA fixes it in the same place.
TURNOVER_NOT_RECORDED = (
    "No aggregate turnover is recorded for this client, so the strictest "
    "reading of Rule 48(4) is shown. CGST §2(6) aggregate turnover is "
    "all-India on the PAN and includes exempt supplies, exports and "
    "inter-State supplies between distinct persons, so it cannot be derived "
    "from one client's books — record it on the client's GST settings."
)

#: What to say where the recipient's GSTIN is present but not a GSTIN. See
#: `registration_state`.
GSTIN_MALFORMED = (
    "The customer's GSTIN is recorded but is not a well-formed GSTIN, so "
    "whether this is a B2B supply cannot be read off the invoice. It is "
    "treated as B2B, which is the direction that cannot omit a required IRN — "
    "correct the customer's GSTIN."
)


#: What to say where the invoice carries no date at all. See `threshold_for`.
INVOICE_DATE_NOT_RECORDED = (
    "This invoice carries no date, so which of Rule 48(4)'s six notified "
    "thresholds governs it cannot be resolved. The STRICTEST (most recent) is "
    "shown, because an absent date is not a pre-2020 date and reading it as "
    "one would report that no IRN is owed — the direction Rule 48(5) makes "
    "expensive."
)


@dataclass(frozen=True)
class Threshold:
    """The Rule 48(4) threshold in force on a date, and where it comes from."""

    #: None before `COMMENCEMENT`, when no class had been notified at all.
    paise: Optional[int]
    citation: str
    #: True where there was no date to resolve against, in which case `paise`
    #: is the STRICTEST threshold rather than the one in force on any date.
    date_missing: bool = False


@dataclass
class IrnScope:
    """Whether Rule 48(4) reaches this supply, limb by limb."""

    #: "required" | "not_required". There is deliberately no third value: every
    #: unknown here resolves to the strict reading and is FLAGGED instead (see
    #: `turnover_unknown`), because Rule 48(5) makes the cost of the two errors
    #: wildly unequal. `eway.assess` does carry an "undetermined", and that is
    #: not an inconsistency — there the unknown is Rule 138(14), which can flip
    #: the answer either way, so neither reading is the safe one.
    verdict: str = "not_required"

    #: The SUPPLY limb — a fact about this document.
    supply_in_scope: bool = False
    supply_reason: str = ""

    #: The PERSON limb — a fact about the client for the year.
    threshold_paise: Optional[int] = None
    threshold_citation: str = ""
    #: The highest aggregate turnover recorded across the qualifying years.
    turnover_paise: Optional[int] = None
    #: None where nobody has recorded one; never False in that case, because
    #: "did not exceed" and "nobody said" are different facts.
    turnover_exceeds: Optional[bool] = None
    turnover_unknown: bool = False

    reason: str = ""
    gaps: list = field(default_factory=list)

    def as_dict(self) -> dict:
        """The wire shape the browser mirror reads back. Spelled in snake_case
        like `EwayAssessment.as_dict`, because the two travel on the same
        invoice payload and one vocabulary is the point."""
        return {
            "verdict": self.verdict,
            "supply_in_scope": self.supply_in_scope,
            "supply_reason": self.supply_reason,
            "threshold_paise": self.threshold_paise,
            "threshold_citation": self.threshold_citation,
            "turnover_paise": self.turnover_paise,
            "turnover_exceeds": self.turnover_exceeds,
            "turnover_unknown": self.turnover_unknown,
            "reason": self.reason,
            "gaps": list(self.gaps),
        }


def threshold_for(invoice_date: str) -> Threshold:
    """The Rule 48(4) turnover threshold in force on this invoice's own date.

    `invoice_date` is ISO YYYY-MM-DD. The fork is by the date of the DOCUMENT,
    not by when it is being looked at: Rule 48(4) governs the preparation of
    the invoice, so a 2021 invoice keeps 2021's threshold for ever.

    AN ABSENT DATE IS NOT A PRE-COMMENCEMENT DATE, and collapsing the two is
    the same class of error this whole module exists to stop. `no date` and
    `before 01-10-2020` would both answer "no threshold", so an invoice whose
    date nobody recorded would be reported as owing no IRN — and Rule 48(5)
    makes that the expensive direction. So a missing date takes the STRICTEST
    (most recent, lowest) threshold and flags itself; only a real date before
    commencement answers `None`.

    `client_sales_invoices.invoice_date` is NOT NULL, so this is defence
    rather than a live state — but the safe reading costs nothing and the
    unsafe one is invisible.
    """
    day = (invoice_date or "").strip()[:10]
    if not day:
        latest = THRESHOLDS[-1]
        return Threshold(paise=latest[1], citation=latest[2], date_missing=True)
    if day < COMMENCEMENT:
        return Threshold(
            paise=None,
            citation=("Rule 48(4) — no class of registered person was notified "
                      f"before {COMMENCEMENT}"),
        )
    chosen = THRESHOLDS[0]
    for step in THRESHOLDS:
        if day >= step[0]:
            chosen = step
        else:
            break
    return Threshold(paise=chosen[1], citation=chosen[2])


def qualifying_financial_years(invoice_date: str) -> list[str]:
    """Every financial year whose turnover can bring a client within Rule 48(4).

    "any preceding financial year from 2017-18 onwards" — so 2017-18 up to and
    INCLUDING the year before the invoice's own, and never the current one: a
    client crossing the threshold this year comes within the rule next year.

    Returned oldest first. The caller takes the HIGHEST recorded figure across
    them, not the latest — the rule latches, and see the header.
    """
    from datetime import date

    from core.ist_clock import ist_fy_label

    day = (invoice_date or "").strip()[:10]
    if not day:
        return []
    y, m, d = (int(x) for x in day.split("-"))
    current = ist_fy_label(date(y, m, d))
    first = int(FIRST_QUALIFYING_FY.split("-")[0])
    last = int(current.split("-")[0]) - 1      # the preceding financial year
    return [f"{yr}-{str(yr + 1)[-2:]}" for yr in range(first, last + 1)]


def registration_state(recipient_gstin: Optional[str]) -> str:
    """Is the recipient a registered person? "registered" | "unregistered" |
    "malformed".

    THREE STATES, AND THE THIRD IS NAMED RATHER THAN GUESSED — the shape
    `domain/gst/rcm_documents` takes for the same question, and for the same
    reason. Reading a malformed GSTIN as "unregistered" takes the invoice out
    of the supply limb altogether, and Rule 48(5) then makes a document that
    needed an IRN not an invoice at all. Fifteen mistyped characters are far
    more likely a real registered customer than a walk-in, so the third state
    is treated as B2B by `supply_scope` and reported.

    SHAPE ONLY, DELIBERATELY. This decides B2B-vs-B2C; it is not a human typing
    a GSTIN into a form, which is where `gstin.problem_with`'s check digit is
    enforced (onboarding, the customer and vendor create/import/PATCH paths).
    That split is the position this repo already records, and it is also what
    lets the browser mirror agree without importing a checksum: a divergence
    between the two on a bad check digit would be a parity break that says
    nothing about who the customer is.
    """
    clean = (recipient_gstin or "").strip().upper()
    if not clean:
        return "unregistered"
    return "registered" if GSTIN_SHAPE.match(clean) else "malformed"


def supply_scope(*, treatment: Optional[str],
                 recipient_gstin: Optional[str]) -> tuple[bool, str, list]:
    """The SUPPLY limb: does Rule 48(4) reach this document? -> (in, why, gaps).

    "in respect of supply of goods or services or both to a registered person,
    or for export". An export or an SEZ supply is in scope on the supply's own
    footing, whatever the buyer's registration — a foreign buyer holds no
    GSTIN and the rule still reaches the invoice — so the treatment is asked
    FIRST and the GSTIN only decides an ordinary domestic supply.

    The treatment is taken, never re-derived: `domain/gst/treatment` is the one
    authority for what kind of supply an invoice is (SALES-19), and a second
    derivation here would be the disagreement that finding exists to prevent.
    """
    gaps: list = []
    kind = (treatment or _treatment.REGULAR).strip().lower()

    if kind in SUPPLY_IN_SCOPE_TREATMENTS:
        return True, (
            f"Rule 48(4) reaches this supply on its own footing "
            f"({kind.replace('_', ' ')}): the sub-rule names exports, and a "
            "supply to a Special Economic Zone is a zero-rated supply under "
            "IGST §16(1)(b). The recipient's registration does not enter it."
        ), gaps

    state = registration_state(recipient_gstin)
    if state == "registered":
        return True, (
            "Rule 48(4) reaches a supply made to a REGISTERED person, and the "
            "customer's GSTIN is recorded on this invoice (B2B)."
        ), gaps
    if state == "malformed":
        gaps.append(GSTIN_MALFORMED)
        return True, (
            "The customer's GSTIN is not well-formed, so this is read as a "
            "B2B supply — the direction that cannot omit a required IRN."
        ), gaps
    return False, (
        "Rule 48(4) reaches a supply to a registered person, an export or a "
        "supply to an SEZ. This is an ordinary domestic supply to an "
        "unregistered recipient (B2C), which the sub-rule does not reach."
    ), gaps


def assess(*, treatment: Optional[str], recipient_gstin: Optional[str],
           invoice_date: str,
           highest_aato_paise: Optional[int]) -> IrnScope:
    """Does this invoice have to carry an IRN? — CGST Rule 48(4).

    `highest_aato_paise` is the HIGHEST CGST §2(6) aggregate turnover recorded
    across `qualifying_financial_years`, or None where the client has no
    recorded figure at all. None is a third state and is never 0: 0 is a client
    who turned over nothing, None is nobody having said, and the two must not
    produce the same answer — defaulting it to 0 is exactly the bug GST-17
    closed on the HSN side, where every client was silently told HSN was
    optional.

    Where it is None and the supply is in scope, the answer is REQUIRED and
    `turnover_unknown` is set: Rule 48(5) makes an omitted IRN cost the
    recipient their input tax credit, while a requirement reported to a client
    who does not owe it costs a glance.
    """
    out = IrnScope()

    in_scope, why, gaps = supply_scope(
        treatment=treatment, recipient_gstin=recipient_gstin)
    out.supply_in_scope = in_scope
    out.supply_reason = why
    out.gaps.extend(gaps)

    threshold = threshold_for(invoice_date)
    out.threshold_paise = threshold.paise
    out.threshold_citation = threshold.citation
    out.turnover_paise = highest_aato_paise

    # THE SUPPLY LIMB IS ASKED FIRST AND SHORT-CIRCUITS, which is not merely an
    # ordering. A B2C invoice is outside Rule 48(4) at ANY turnover, so
    # reporting "your client is above ₹5 crore" beside it would be true and
    # irrelevant, and naming the exempted classes there would invite a CA to go
    # and check a proviso that cannot change the answer.
    if not in_scope:
        out.verdict = "not_required"
        out.reason = why
        return out

    # Named only once the supply limb has passed, for the same reason the
    # exempted classes are: on a B2C invoice the threshold decides nothing, so
    # the missing date decides nothing either.
    if threshold.date_missing:
        out.gaps.append(INVOICE_DATE_NOT_RECORDED)

    if threshold.paise is None:
        out.verdict = "not_required"
        out.reason = (
            f"Rule 48(4) notified no class of registered person before "
            f"{COMMENCEMENT}, so an invoice dated {invoice_date} owes no IRN "
            "whatever the turnover.")
        return out

    if highest_aato_paise is None:
        out.turnover_unknown = True
        out.turnover_exceeds = None
        out.verdict = "required"
        out.reason = (
            f"{why} The threshold on this invoice's date is "
            f"{_rupees(threshold.paise)} ({threshold.citation}), and no "
            "aggregate turnover is recorded for this client — the strictest "
            "reading is shown.")
        out.gaps.append(TURNOVER_NOT_RECORDED)
        out.gaps.append(_exempted_classes_sentence())
        return out

    # "EXCEEDS" — a strict inequality, as in Rule 138(1)'s ₹50,000 and for the
    # same reason: a client exactly ON the threshold is not above it. Writing
    # `>=` here would bring a ₹5,00,00,000 client into e-invoicing a rupee
    # early, and the notification's own word is "exceeds".
    out.turnover_exceeds = highest_aato_paise > threshold.paise
    if not out.turnover_exceeds:
        out.verdict = "not_required"
        out.reason = (
            f"The highest aggregate turnover recorded for this client is "
            f"{_rupees(highest_aato_paise)}, which does not exceed the "
            f"{_rupees(threshold.paise)} threshold in force on this invoice's "
            f"date ({threshold.citation}).")
        return out

    out.verdict = "required"
    out.reason = (
        f"{why} The client's recorded aggregate turnover reaches "
        f"{_rupees(highest_aato_paise)}, above the "
        f"{_rupees(threshold.paise)} threshold in force on this invoice's date "
        f"({threshold.citation}). Rule 48(5): an invoice this sub-rule reaches, "
        "issued without an IRN, is not treated as an invoice — the recipient's "
        "input tax credit goes with it.")
    out.gaps.append(_exempted_classes_sentence())
    return out


def _exempted_classes_sentence() -> str:
    """Named on every "required" answer and on none of the others.

    An exemption can only REMOVE a requirement, so it cannot change an answer
    that is already "not required" — putting it there would be noise on the
    commonest case and would train a CA to skip it on the case that matters.
    """
    return (
        "The first proviso to Rule 48(4) exempts some classes of registered "
        "person from e-invoicing however large their turnover, and this "
        "product does not record which class a client is in: "
        + "; ".join(EXEMPTED_CLASSES)
        + ". Confirm the client is not one of them."
    )


def _rupees(paise: int) -> str:
    """₹ with Indian digit grouping, for a sentence a CA reads. Whole rupees —
    a threshold is a crore figure and the paise are noise at that scale.

    ⚠️ The pair-slicing loop that used to live here was a copy of
    `domain/money_text.group_indian`, which CLAUDE.md names as the one backend
    authority for this. It also dropped the SIGN — `abs()` before grouping —
    so a negative would have come back positive; harmless on a threshold,
    which is always positive, and the reason nothing caught it.
    `tests/test_one_module_groups_a_rupee_figure.py` is the rule now."""
    return "₹" + whole_rupees(paise)
