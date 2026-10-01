"""The s. 393 payment code for ONE deductee line (TDS-31).

WHY THIS IS ITS OWN MODULE

    `domain/tds/vocabulary.payment_code_for` has answered fourteen sections from
    the Protean specification since 25-09-2026, and CLAUDE.md recorded it as
    "deliberately NOT yet wired into `tds_return_service.py`'s per-line deductee
    output" with the wiring named as the next step. So for a FY 2026-27
    statement the CA was told, in one return-level sentence, that "some lines'
    codes are not filled in" — and was shown no line that had one. From April
    2026 the portal wants a code on every row of Form 138, 140 and 144, and the
    product already knew most of them.

    `vocabulary.py` answers "which code does THIS section carry". It cannot
    answer "which code does THIS ROW carry", because for exactly one section
    the answer needs a fact about the deductee that the section key does not
    hold: s.194C's two rows (1023 individual or HUF contractor, 1024 any other)
    split on WHO THE CONTRACTOR IS. That is read off the deductee's own PAN, so
    it lives here beside the other per-row reads rather than inside a
    vocabulary module that takes no PAN.

THE ONE THAT NEEDS A SECOND FACT, AND WHY IT IS NOT READ OFF THE RATE

    `payment_code_for("194C", rate_bps=...)` was written to take the rate the
    engine resolved, and the module comment says so: the table's two rows are
    "exactly the individual_rate_bps / company_rate_bps split". That holds for
    the SECTION's rate and not for the rate a row was deducted at. A row
    deducted at 20% because the contractor gave no PAN (§206AA), or at a lower
    rate under a §197 certificate, carries a stored rate that is neither 1%
    nor 2% — so reading the stored rate would turn a perfectly knowable
    contractor class into a gap on the rows most likely to be questioned.

    The class is asked of the PAN instead, with the SAME rule the engine used to
    pick the rate (`tds_computer.is_company_pan`: the fourth character, P or H
    for an individual or HUF) — and the section's own rate for that class is
    then handed to `payment_code_for`, which keeps its refusal: if the registry
    ever carries a 194C rate that is not 1% or 2%, the row becomes a named gap
    rather than a wrong code.

    No PAN is a gap, not "other". `is_company_pan` answers True for a missing
    PAN because that is the safe direction for a RATE; for a LABEL on a filed
    statement it would be a guess — the contractor may well be an individual
    whose PAN simply has not been recorded.

WHAT IS HELD ON A STATED DEFAULT

    s.192 resolves one of three codes by who the DEDUCTOR is (1001 Central
    Government, 1002 anyone else, 1003 Union territory), and no client here is
    modelled as a government department. 1002 is returned with an
    `assumption` naming the other two — the same shape `section_rates.py` takes
    for the 194A bank/senior-citizen thresholds, a stated simplification and
    not a silent guess.

WHAT THIS DOES NOT DO

    It does not widen the table. A section the specification read does not
    answer, or splits on a fact nobody records, comes back as a NAMED gap with
    its own reason (`vocabulary._PAYMENT_CODE_SPLITS`), and `payment_code_gap()`
    still names the whole table's incompleteness at the statement level. A
    1961-Act period carries no payment code at all and is answered
    `(None, None, None)` — nothing is missing there, because nothing is asked.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here transmits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from domain.tds import vocabulary
from domain.tds.section_rates import tds_rates_for
from domain.tds.tds_computer import has_pan

#: The fourth character of a PAN names the holder. P and H are the two
#: that s.393(1) Table Sl. No. 6(i).D(a) means by "individual or Hindu
#: undivided family"; the rest are the other holder types a PAN can carry
#: (C company, F firm, A AOP, T trust, B BOI, L local authority, J artificial
#: juridical person, G government). A letter in neither set is not a holder
#: type at all, which is a malformed PAN and is refused rather than read as
#: "other". `[S]`-graded — the PAN structure is long settled and is the same
#: split `tds_computer.is_company_pan` already relies on.
_INDIVIDUAL_OR_HUF = frozenset("PH")
_OTHER_HOLDER_TYPES = frozenset("CFATBLJG")

#: 192's stated default, and the sentence that says it is one.
_SECTION_192_ASSUMPTION = (
    "Code 1002 assumes the deductor is not a government department. A "
    "Central Government deductor files under 1001 and a Union territory under "
    "1003, and nothing in this product records which a client is.")


@dataclass(frozen=True)
class LinePaymentCode:
    """The answer for one row. Exactly one of `code` and `gap` is set in a
    2025-Act period; both are None in a 1961-Act one."""
    code: Optional[str] = None
    gap: Optional[str] = None
    assumption: Optional[str] = None


def for_line(fy_label: str, section_1961: str, *,
             deductee_pan: Optional[str] = None) -> LinePaymentCode:
    """The payment code for one deductee row of a statement for `fy_label`.

    `section_1961` is the STORED routing key (`d.section`), never the label the
    row is printed under: s.393(1) has no reverse, so a code keyed on the label
    could not tell 194C from 194J.
    """
    vocab = vocabulary.vocabulary_for(fy_label)
    if not vocab.is_2025_act:
        return LinePaymentCode()

    section = str(section_1961 or "").strip().upper()

    if section == "194C":
        return _contractor_code(vocab, fy_label, deductee_pan)

    code, gap = vocab.payment_code(section)
    if code is None:
        return LinePaymentCode(gap=gap.note if gap else None)
    return LinePaymentCode(
        code=code,
        assumption=_SECTION_192_ASSUMPTION if section == "192" else None)


def _contractor_code(vocab: vocabulary.Vocabulary, fy_label: str,
                     pan: Optional[str]) -> LinePaymentCode:
    """s.194C: 1023 or 1024 by the contractor's class, read off the PAN."""
    if not has_pan(pan):
        return LinePaymentCode(gap=(
            "s.194C resolves to payment code 1023 (the contractor is an "
            "individual or HUF) or 1024 (any other contractor), and which one "
            "is read off the contractor's PAN. This deductee has no PAN "
            "recorded, so the class cannot be read and none is guessed. "
            "Record the PAN on the supplier, or read the code off the current "
            "Rules."))
    holder = str(pan).strip().upper()[3:4]
    if holder not in _INDIVIDUAL_OR_HUF and holder not in _OTHER_HOLDER_TYPES:
        return LinePaymentCode(gap=(
            f"s.194C resolves to payment code 1023 or 1024 by the contractor's "
            f"class, read off the fourth character of the PAN — and "
            f"{holder or '(none)'!r} is not a PAN holder type, so the PAN on "
            f"this deductee is not one. Correct the PAN on the supplier."))
    rule = tds_rates_for(fy_label).sections.get("194C")
    if rule is None:
        return LinePaymentCode(gap="s.194C is not in this year's rate registry.")
    rate_bps = (rule.individual_rate_bps if holder in _INDIVIDUAL_OR_HUF
                else rule.company_rate_bps)
    code, gap = vocab.payment_code("194C", rate_bps=rate_bps)
    if code is None:
        return LinePaymentCode(gap=gap.note if gap else None)
    return LinePaymentCode(code=code)


def statement_notes(rows: Iterable[tuple[str, LinePaymentCode]]) -> list[str]:
    """What a statement's own `statutory_gaps` must say about its rows.

    One sentence per distinct section that went unanswered — with how many
    lines it reaches — and one per distinct assumption. The statement already
    carries the blanket `payment_code_gap()` sentence; these are the PER-ROW
    half of it, so a CA reading the list learns which of their lines need
    keying by hand and which do not. Empty for a 1961-Act period, whose rows
    are all `LinePaymentCode()`.
    """
    unanswered: dict[str, list[str]] = {}
    assumptions: list[str] = []
    for section, answer in rows:
        if answer.gap:
            unanswered.setdefault(str(section or "").strip().upper(), []).append(answer.gap)
        if answer.assumption and answer.assumption not in assumptions:
            assumptions.append(answer.assumption)

    notes: list[str] = []
    for section in sorted(unanswered):
        gaps = unanswered[section]
        # One reason per section is the usual case; where a section's rows had
        # different reasons (194C with a PAN on some and not others) the
        # distinct ones are all kept.
        reasons = " ".join(dict.fromkeys(gaps))
        n = len(gaps)
        notes.append(
            f"{n} line{'s' if n != 1 else ''} under s.{section or '(blank)'} "
            f"carr{'ies' if n == 1 else 'y'} no payment code. {reasons}")
    notes.extend(assumptions)
    return notes
