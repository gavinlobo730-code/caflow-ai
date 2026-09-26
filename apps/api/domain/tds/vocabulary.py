"""
Which Act names a TDS form and section, for a given period — both, for ever.

WHY THIS EXISTS

The Income-tax Act 2025, with the Income-tax Rules 2026 (CBDT Notification
22/2026 of 20-03-2026, G.S.R. 198(E), plus a corrigendum), took effect on
1 April 2026 and renumbered every TDS statement, every certificate and every
charging section. Rates and thresholds are substantively UNCHANGED — what moved
is the LABEL a payment is reported under.

That makes the failure quiet and expensive. `domain/tds/section_rates.py` holds
entirely correct numbers under keys that are now obsolete for current periods;
`domain/payroll/form24q.py` emitted `section="192"` on a statement that, for a
2026-27 event, must say 392 and must be Form 138. A return filed under the old
form number is REJECTED at validation, and an old section code draws a
processing error and a correction statement.

THIS IS NOT A MIGRATION, AND THAT IS THE WHOLE DESIGN

The transition is by EVENT — the credit or the payment, WHICHEVER IS EARLIER —
not by filing date. Commencement does not disturb obligations that arose under
the 1961 Act. So a belated or revised Q4 FY 2025-26 statement filed today is
still Form 24Q, citing s. 192, and will be for as long as anyone can file it.

Both vocabularies are therefore permanent. Nothing here replaces anything; the
module answers "which set of names applies to THIS period" and carries both.
Rekeying section_rates.py would destroy the older half and is explicitly not the
fix.

THE FY BOUNDARY AND THE EVENT RULE AGREE, AND THAT IS WORTH SAYING

Commencement falls on 1 April 2026, which is exactly a financial-year boundary.
So every event in FY 2025-26 is before it and every event in FY 2026-27 is after
it: a whole return is always on one side. `act_for_fy` is therefore sound rather
than an approximation, and `act_for_date` is the definition it is derived from.
A bill credited 25-03-2026 and paid 10-04-2026 has its event on 25 March — the
earlier of the two — which is FY 2025-26, which is the 1961 Act, and the two
rules return the same answer for the same reason.

WHAT THIS MODULE REFUSES, AND WHAT IT NOW PARTLY DOES NOT (25-09-2026)

The 2025 Act's statements carry NUMERIC PAYMENT CODES 1001-1067, corresponding
to entries in the s. 393 table. Guessing any of them would be a wrong label on
a filed return, and a wrong code is a correction statement rather than a
rejection — it gets accepted and is wrong. That refusal still stands for most
of the table.

A CONFIRMED SUBSET IS NOW HELD, from a primary source: the file-format
specification Protean (formerly NSDL) publishes for the renumbered statements
themselves, whose own Annexure 2 tables state "Nature of Payment | Section |
Section code to be used in the return" — a [P]-graded read of the government's
own document, not the Act's text and not a search-engine summary of either.
`payment_code_for()` answers fourteen of the sections `section_rates.py`
already holds (s.192 by a stated default, s.193, s.194, s.194B, s.194C by
rate, s.194D, s.194G, s.194H, s.194I(a)/(b), s.194J(a), s.194LA, s.194Q,
s.194T) and refuses the rest — several of which turned out to split FURTHER
under the new table on a fact no rate difference had exposed (s.194A by the
payee's age, s.194J(b) between a professional fee and a director's fee). See
the comment on `_PAYMENT_CODES_CONFIRMED` for the citations and the ones that
still refuse. `payment_code_gap()` still names the whole table's incompleteness
at the return level; `payment_code_for()` is the per-line answer where one
exists.

The old-to-new SECTION mapping is also ONE-WAY, deliberately. The whole
194-series collapsed into a single s. 393(1) with a table, so 194C, 194J, 194H
and their neighbours all map forward to 393(1) and NOTHING maps back. A reverse
lookup would have to invent which of them was meant, so `section_1961_for` exists
only for the codes that are genuinely one-to-one and refuses 393(1) outright.

WHAT IS NOT RENUMBERED

ITR-1 to ITR-7 are unaffected this season. CBDT notified them for AY 2026-27 on
30-03-2026 under the 1961 Act, because AY 2026-27 covers FY 2025-26. The 2025
Act reaches income-tax RETURNS in 2027, for tax year 2026-27, so nothing in
domain/income_tax/ changes here.

Due dates are unchanged — 31 Jul / 31 Oct / 31 Jan / 31 May.
services/compliance_engine.py remains the single source for them.

Verified 2026-09-04; see docs/compliance/03-income-tax-and-tds.md.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here transmits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

#: The day the Income-tax Act 2025 and the Income-tax Rules 2026 took effect.
#: Deliberately a date and not an FY label: the statute commences on a day, and
#: the transition rule is about an EVENT falling on one side of it.
COMMENCEMENT = date(2026, 4, 1)

ACT_1961 = "1961"
ACT_2025 = "2025"

#: What a statement is ABOUT. Stable across both Acts — the return kinds did not
#: change, only their numbers — so this is what callers key on rather than a
#: form number that is only right for half of history.
SALARY = "salary"
RESIDENT_NON_SALARY = "resident_non_salary"
NON_RESIDENT = "non_resident"
TCS = "tcs"

STATEMENT_KINDS = (SALARY, RESIDENT_NON_SALARY, NON_RESIDENT, TCS)

_STATEMENT_FORMS: dict[str, dict[str, str]] = {
    ACT_1961: {SALARY: "24Q", RESIDENT_NON_SALARY: "26Q",
               NON_RESIDENT: "27Q", TCS: "27EQ"},
    # Rule 219 prescribes 138 under ss. 392 and 393(1); 140 under s. 397;
    # 144 under s. 397(3)(b).
    ACT_2025: {SALARY: "138", RESIDENT_NON_SALARY: "140",
               NON_RESIDENT: "144", TCS: "143"},
}

#: What a certificate is FOR, same reasoning as the statement kinds.
SALARY_CERTIFICATE = "salary_certificate"
NON_SALARY_CERTIFICATE = "non_salary_certificate"
TAX_CREDIT_STATEMENT = "tax_credit_statement"
NO_DEDUCTION_DECLARATION = "no_deduction_declaration"

CERTIFICATE_KINDS = (SALARY_CERTIFICATE, NON_SALARY_CERTIFICATE,
                     TAX_CREDIT_STATEMENT, NO_DEDUCTION_DECLARATION)

_CERTIFICATE_FORMS: dict[str, dict[str, str]] = {
    ACT_1961: {SALARY_CERTIFICATE: "16", NON_SALARY_CERTIFICATE: "16A",
               TAX_CREDIT_STATEMENT: "26AS",
               # Two separate forms under the 1961 Act: 15G for the general
               # case, 15H for senior citizens. The 2025 Act merges them.
               NO_DEDUCTION_DECLARATION: "15G/15H"},
    ACT_2025: {SALARY_CERTIFICATE: "130", NON_SALARY_CERTIFICATE: "131",
               TAX_CREDIT_STATEMENT: "168", NO_DEDUCTION_DECLARATION: "121"},
}

#: THE PART A CALLER MUST NOT MISS. Two certificates did not merely change
#: number, they changed SHAPE — so a caller that swaps the label and keeps the
#: old cadence produces a wrong document with a right name.
_CERTIFICATE_NOTES: dict[str, dict[str, str]] = {
    ACT_2025: {
        SALARY_CERTIFICATE:
            "Form 130 has THREE parts (A/B/C), where Form 16 had two. Still "
            "TRACES-generated and cannot be issued manually.",
        NON_SALARY_CERTIFICATE:
            "Form 131 is issued QUARTERLY, where Form 16A was annual. Changing "
            "only the number would issue one certificate where four are due.",
        NO_DEDUCTION_DECLARATION:
            "Form 121 MERGES 15G and 15H. There is no longer a separate "
            "senior-citizen form.",
    },
}

#: One-to-one section moves. The 194-series is deliberately absent: it collapsed
#: into a single s. 393(1) with a table, so it is handled by rule below and has
#: no reverse.
_SECTION_2025_ONE_TO_ONE: dict[str, str] = {
    "192": "392",     # salary
    "195": "393(2)",  # payments to non-residents. NOT s. 400 — see the module
                      # docstring in domain/tds/section_195.py and the
                      # correction recorded in the compliance doc.
    "206C": "394",    # TCS
    "139": "263",     # return of income (not a TDS section; carried because the
                      # obligation engine names it and the same rule governs)
}

SECTION_194_SERIES_2025 = "393(1)"

#: The numeric payment codes the 2025 Act's statements carry. The RANGE is
#: known; the FULL mapping is not held. See payment_code_gap().
PAYMENT_CODE_RANGE = (1001, 1067)

#: THE PART OF THE TABLE THAT IS NOW HELD (25-09-2026), read from a PRIMARY
#: SOURCE rather than the Act's own text — [P]-graded, not [S]: the file-format
#: specification NSDL/Protean publishes for the RENUMBERED statements (Form
#: 138/140/144, "Q1 to Q3/Q4 Version 1.1/1.2, for Tax Year 2026-27 onwards"),
#: whose own "Annexure 2" is titled "Nature of Payment | Section | Section code
#: to be used in the return" and states the s. 393 table entry beside each
#: payment code. Fetched by the owner and read directly, not a search-engine
#: summary of the Act — the same [P] grade GST-32's IRP validations carry.
#:
#: ONLY THE UNAMBIGUOUS ENTRIES ARE HERE. Several 1961-Act keys this registry
#: already holds turned out to split FURTHER under the 2025 Act's own table —
#: a fact no rate difference had exposed, because the split is about which
#: NUMBER goes on the line, not what is withheld:
#:
#:   * "192" resolves ONE of three codes (1001 government-Central, 1002
#:     non-government, 1003 government-Union) by who the DEDUCTOR is, a fact
#:     this codebase does not record (no client is modelled as a government
#:     department). 1002 is the confirmed default — every real client of this
#:     product is a private employer — and it is a STATED SIMPLIFICATION in the
#:     same shape section_rates.py already takes for s.194A's bank/senior-
#:     citizen thresholds, not a silent guess: a client that IS a government
#:     department needs 1001 or 1003 instead, and none is.
#:   * "194A" splits into THREE codes by the payee's age and the payer's kind
#:     (1020 senior citizen, 1021 other, 1022 residual) — none of which this
#:     registry's single 194A rate distinguishes. Left as a gap.
#:   * "194J(B)" — the professional-fee limb — is NOT confirmed, because the
#:     table's own Sl. No. 6(iii).D(b) row splits into TWO codes sharing that
#:     one citation: 1027 for professional fees (and s.26(2)(h) sums) and 1028
#:     for a DIRECTOR's remuneration or commission. s.194J(1)(ba) charges a
#:     director's fee under the same 10% rate as a professional fee, so the
#:     registry's "194J(B)" key cannot tell them apart — recording one would be
#:     the exact guess this module exists to refuse. "194J(A)" (technical
#:     services) has no such split and IS confirmed.
#:   * "194K" and "206C" are absent from every annexure read — 206C is TCS,
#:     reported on Form 143/27EQ, a different statement's own table this pass
#:     did not open.
#:
#: "194C" is the one confirmed entry that needs a SECOND fact — which rate
#: applied — because the table's own two rows (1023 individual/HUF contractor,
#: 1024 other) are exactly the individual_rate_bps / company_rate_bps split
#: section_rates.py's "194C" rule already carries. No new fact is needed: the
#: caller passes the rate the engine already resolved.
_PAYMENT_CODES_CONFIRMED: dict[str, str] = {
    "192": "1002",     # "Payments made to employees other than Govt. employees"
                        # — Form 138 Annexure 2. See the note above: a stated
                        # default, not the only code the section can carry.
    "193": "1019",      # "Any income by way of Interest on securities" —
                         # s.393(1) Table Sl. No. 5(i). Form 140 Annexure 2.
    "194": "1029",       # "Any dividends (including on preference shares)
                         # declared." — s.393(1) Table Sl. No. 7.
    "194B": "1058",      # "...winnings...from (a) any lottery; or (b) crossword
                         # puzzle; or (c) card game...; or (d) gambling or
                         # betting..." — s.393(3) Table Sl. No. 1.
    "194D": "1005",      # "Commission or brokerage - insurance" — s.393(1)
                         # Table Sl. No. 1(i). s.194D's own heading is
                         # "Insurance commission"; this is that limb, not
                         # s.194H's.
    "194G": "1063",      # "...credited or paid to a person, who is or has been
                         # stocking, distributing, purchasing or selling
                         # lottery tickets, by way of commission..." —
                         # s.393(3) Table Sl. No. 4.
    "194H": "1006",      # "Commission or Brokerage - others" — s.393(1) Table
                         # Sl. No. 1(ii); the non-insurance limb 194D's own
                         # code is not.
    "194I(A)": "1008",   # "Rent on machinery etc.- specified person" —
                         # s.393(1) Table Sl. No. 2(ii).D(a).
    "194I(B)": "1009",   # "Rent other than machinery etc.- specified person" —
                         # s.393(1) Table Sl. No. 2(ii).D(b).
    "194J(A)": "1026",   # "...(a) fees for technical services (not being a
                         # professional services); or (b) royalty [for
                         # cinematograph films]; or (c) [a call-centre
                         # operator]" — s.393(1) Table Sl. No. 6(iii).D(a).
    "194LA": "1012",     # "Payment of Compensation on Acquisition of Certain
                         # Immovable Property" — s.393(1) Table Sl. No. 3(iii).
    "194Q": "1031",      # "Any sum for purchase of any goods" — s.393(1)
                         # Table Sl. No. 8(ii).
    "194T": "1067",      # "Any sum in the nature of salary, remuneration,
                         # commission, bonus or interest paid to a partner of
                         # the firm..." — s.393(3) Table Sl. No. 7.
}

#: "194C" alone needs a second fact (see the module comment above): which of
#: TDSSectionRule's two rates applied. Keyed on the exact bps the engine
#: resolves with, so a caller passing anything else is a caller passing the
#: wrong number, not this table being incomplete.
_PAYMENT_CODE_194C_BY_RATE_BPS: dict[int, str] = {
    100: "1023",  # "...if contractor is individual or Hindu undivided family"
                  # — s.393(1) Table Sl. No. 6(i).D(a).
    200: "1024",  # "...if contractor is a person other than individual or
                  # Hindu undivided family" — s.393(1) Table Sl. No. 6(i).D(b).
}


class VocabularyError(ValueError):
    """A form or section that cannot be named for the period asked about."""


def act_for_date(event_date: date) -> str:
    """Which Act governs an event on this date.

    The event is the CREDIT OR THE PAYMENT, WHICHEVER IS EARLIER — the caller
    decides which that was; this only says which side of commencement it falls.
    """
    return ACT_2025 if event_date >= COMMENCEMENT else ACT_1961


def act_for_fy(fy_label: str) -> str:
    """Which Act governs a whole financial year.

    Sound rather than approximate: commencement is 1 April 2026, exactly an FY
    boundary, so no financial year straddles it. Derived from act_for_date on
    the year's first day so there is one rule and not two.
    """
    try:
        start_year = int(str(fy_label).split("-")[0])
    except (ValueError, AttributeError, IndexError):
        raise VocabularyError(
            f"{fy_label!r} is not a financial year label. Use YYYY-YY, the form "
            f"core.ist_clock.normalise_fy_label produces.")
    return act_for_date(date(start_year, 4, 1))


def statement_form(kind: str, *, fy_label: str | None = None,
                   event_date: date | None = None) -> str:
    """The form number for a statement of `kind` in that period.

    Exactly one of fy_label or event_date. Refusing both-or-neither rather than
    picking a default: a form number silently derived from today's date is the
    failure this module exists to end — it would file a 2025-26 belated return
    on Form 138.
    """
    act = _act_from(fy_label, event_date)
    try:
        return _STATEMENT_FORMS[act][kind]
    except KeyError:
        raise VocabularyError(
            f"{kind!r} is not a statement kind. It is one of "
            f"{', '.join(STATEMENT_KINDS)}.")


def certificate_form(kind: str, *, fy_label: str | None = None,
                     event_date: date | None = None) -> str:
    act = _act_from(fy_label, event_date)
    try:
        return _CERTIFICATE_FORMS[act][kind]
    except KeyError:
        raise VocabularyError(
            f"{kind!r} is not a certificate kind. It is one of "
            f"{', '.join(CERTIFICATE_KINDS)}.")


def certificate_note(kind: str, *, fy_label: str | None = None,
                     event_date: date | None = None) -> str | None:
    """What ELSE changed about this certificate, beyond its number.

    Returns None where nothing did. Read it: Form 131 is quarterly where 16A was
    annual, and a caller that renumbers without re-cadencing issues one
    certificate where four are due.
    """
    act = _act_from(fy_label, event_date)
    return _CERTIFICATE_NOTES.get(act, {}).get(kind)


def section_code(section_1961: str, *, fy_label: str | None = None,
                 event_date: date | None = None) -> str:
    """The section a payment is reported under, in that period's vocabulary.

    Takes the 1961-Act section because that is what the rest of the codebase
    holds — section_rates.py is keyed by it, and deliberately stays that way.
    For a 1961-Act period this is the identity; for a 2025-Act period it is the
    forward map, with the whole 194-series going to s. 393(1).
    """
    code = str(section_1961 or "").strip().upper()
    if not code:
        raise VocabularyError("No section code given.")
    if _act_from(fy_label, event_date) == ACT_1961:
        return code
    if code in _SECTION_2025_ONE_TO_ONE:
        return _SECTION_2025_ONE_TO_ONE[code]
    if code.startswith("194"):
        return SECTION_194_SERIES_2025
    raise VocabularyError(
        f"No 2025-Act section is recorded for {code!r}. The mapping here covers "
        f"s. 192, the whole 194-series, s. 195 and s. 206C; anything else has to "
        f"be read off the Act rather than guessed, because a wrong section code "
        f"on a filed statement is a correction statement, not a rejection.")


def section_1961_for(section_2025: str) -> str:
    """The reverse, where it EXISTS — and a refusal where it does not.

    s. 393(1) has no reverse. The 194-series collapsed into it, so asking which
    of 194C, 194J, 194H and their neighbours a 393(1) line was means inventing
    one. What distinguishes them under the 2025 Act is the numeric payment code,
    which this module does not hold.
    """
    code = str(section_2025 or "").strip()
    if code == SECTION_194_SERIES_2025:
        raise VocabularyError(
            "s. 393(1) has no single 1961-Act section: the whole 194-series "
            "collapsed into it. What distinguishes those payments under the "
            "2025 Act is the numeric payment code, which this module does not "
            "hold — see payment_code_gap().")
    for old, new in _SECTION_2025_ONE_TO_ONE.items():
        if new == code:
            return old
    raise VocabularyError(f"No 1961-Act section is recorded for {code!r}.")


@dataclass(frozen=True)
class Gap:
    """Statutory data a human has to supply, named rather than guessed."""
    field: str
    note: str


def payment_code_gap() -> Gap:
    """The s. 393 payment-code table, which is not FULLY held and is not
    invented for what is missing.

    Same judgement as the state professional-tax slabs, the DTAA treaty rates
    and the ESIC reason codes: where the truth has to come from a published
    table nobody here has read, refusing is the only safe answer. A guessed
    code would be a wrong label on a filed return — and a wrong payment code
    is ACCEPTED and then wrong, which is worse than a rejection, because
    nothing tells the CA.

    THIS IS STILL THE RIGHT BLANKET WARNING, even though `payment_code_for()`
    below now resolves a confirmed subset: most of the table remains unread,
    and a caller that only checks `gaps()` — the return-level list, not a
    per-line lookup — must still see that some lines may need one. Call
    `payment_code_for()` per line for the sections it actually answers.
    """
    lo, hi = PAYMENT_CODE_RANGE
    return Gap(
        field="tds_payment_code",
        note=(f"Statements under the Income-tax Act 2025 carry a numeric "
              f"payment code ({lo}-{hi}) for each line, corresponding to an "
              f"entry in the s. 393 table. PracticeSync holds a confirmed "
              f"subset (see payment_code_for()) and not the rest, so some "
              f"lines' codes are not filled in — read those off the current "
              f"Rules and enter them on the portal. The section and every "
              f"figure on this statement are computed either way."),
    )


def payment_code_for(section_1961: str, *, rate_bps: int | None = None,
                     ) -> tuple[str | None, Gap | None]:
    """The s. 393 payment code for one line, where the confirmed subset above
    answers it — `(code, None)` — or `(None, Gap)` naming why not.

    Takes the 1961-Act key this codebase already stores (the same argument
    `section_code()` takes), never the 2025-Act section: s. 393(1) has no
    reverse (`section_1961_for`'s own docstring), so a payment code keyed on
    "393(1)" could not tell 194C from 194J from 194H apart, and the whole
    point of this table is that IT is what does.

    `rate_bps` is required ONLY for "194C", whose two rows split on exactly
    the rate `TDSSectionRule` already resolved (see the module comment on
    `_PAYMENT_CODE_194C_BY_RATE_BPS`) — a caller passing neither the section's
    own individual nor company rate gets a gap naming the mismatch rather than
    a guess at which contractor type was meant.
    """
    code = str(section_1961 or "").strip().upper()
    if code == "194C":
        confirmed = (_PAYMENT_CODE_194C_BY_RATE_BPS.get(rate_bps)
                     if rate_bps is not None else None)
        if confirmed:
            return confirmed, None
        return None, Gap(
            field="tds_payment_code",
            note=(f"s.194C resolves to payment code 1023 (contractor is an "
                  f"individual or HUF) or 1024 (any other contractor) by "
                  f"WHICH RATE applied, and {rate_bps!r} is neither the 1% "
                  f"nor the 2% this section's own registry entry carries. "
                  f"Read the code off the current Rules."))
    confirmed = _PAYMENT_CODES_CONFIRMED.get(code)
    if confirmed:
        return confirmed, None
    return None, Gap(
        field="tds_payment_code",
        note=(f"No confirmed s.393 payment code is held for {code or '(blank)'!r}. "
              f"{payment_code_gap().note}"))


@dataclass(frozen=True)
class Vocabulary:
    """Every name that applies to one period, resolved once.

    A bundle rather than repeated lookups so a caller cannot accidentally mix
    halves — naming a statement Form 138 and then citing s. 192 on its lines is
    exactly the mistake this module exists to prevent, and it is only possible
    if the two are resolved separately.
    """
    act: str
    fy_label: str | None

    @property
    def is_2025_act(self) -> bool:
        return self.act == ACT_2025

    @property
    def act_name(self) -> str:
        return ("Income-tax Act, 2025" if self.is_2025_act
                else "Income-tax Act, 1961")

    def statement(self, kind: str) -> str:
        return _STATEMENT_FORMS[self.act][kind]

    def certificate(self, kind: str) -> str:
        return _CERTIFICATE_FORMS[self.act][kind]

    def note_for(self, kind: str) -> str | None:
        return _CERTIFICATE_NOTES.get(self.act, {}).get(kind)

    def section(self, section_1961: str) -> str:
        return section_code(section_1961, fy_label=self.fy_label) \
            if self.fy_label else _forward_section(self.act, section_1961)

    def payment_code(self, section_1961: str, *, rate_bps: int | None = None,
                     ) -> tuple[str | None, Gap | None]:
        """The s. 393 payment code for one deductee line, or None with why not.

        A 1961-Act period has no such code at all — the old forms cite the
        alphabetic section code `section()` already resolves, never a numeric
        one — so this always answers `(None, None)` there rather than a Gap:
        nothing is missing, because nothing is asked for.
        """
        if not self.is_2025_act:
            return None, None
        return payment_code_for(section_1961, rate_bps=rate_bps)

    def gaps(self) -> list[Gap]:
        """What this period needs that PracticeSync cannot supply."""
        return [payment_code_gap()] if self.is_2025_act else []


def vocabulary_for(fy_label: str) -> Vocabulary:
    return Vocabulary(act=act_for_fy(fy_label), fy_label=fy_label)


def _forward_section(act: str, section_1961: str) -> str:
    code = str(section_1961 or "").strip().upper()
    if act == ACT_1961:
        return code
    if code in _SECTION_2025_ONE_TO_ONE:
        return _SECTION_2025_ONE_TO_ONE[code]
    if code.startswith("194"):
        return SECTION_194_SERIES_2025
    raise VocabularyError(f"No 2025-Act section is recorded for {code!r}.")


def _act_from(fy_label: str | None, event_date: date | None) -> str:
    if (fy_label is None) == (event_date is None):
        raise VocabularyError(
            "Give exactly one of fy_label or event_date. Defaulting to today "
            "would file a belated FY 2025-26 statement on a 2025-Act form, "
            "which is the failure this module exists to prevent.")
    return act_for_fy(fy_label) if fy_label is not None else act_for_date(event_date)
