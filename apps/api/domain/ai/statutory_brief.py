"""The statutory facts the assistant is briefed with — generated from the registries
the engines compute with, for the year it is NOW, under both Acts (ai-19).

WHAT WAS WRONG
    Only the TDS block of the assistant's prompt was generated. The income-tax
    slabs, the §87A rebate, the surcharge ladder, the e-invoice threshold and the
    registration thresholds were typed text for FY 2025-26, and the prompt itself
    was a module-level string built ONCE at import — so on a Render process that
    stays up across 1 April it kept introducing a financial year that had ended.
    Meanwhile the Income-tax Act 2025 and the Income-tax Rules 2026 took effect on
    01-04-2026 and renumbered every TDS statement, certificate and charging
    section, and neither the assistant nor the copilot prompt knew. For a payment
    made on 15 May 2026 the chat cited the 1961 Act's section, which that Act's
    successor does not contain — while `domain/tds/vocabulary` held the whole
    mapping and the product's own TDS return already used it.

    A CA asking "what is the section for this payment" was therefore answered
    from last year's prose by a product whose own engine had moved on: the same
    shape as the wrong Q4 deadline and the Rs 30,000 §194J threshold that
    `tests/test_system_prompts_agree_with_the_code.py` was written for.

THE RULE
    Every number, label and date below is READ FROM A REGISTRY at call time, so a
    change to the registry changes the prompt with no other edit:

      * slabs, rebate, standard deduction, surcharge, cess  <- `statutory_rates`
      * the year's verification status                      <- `fy_rate_gap`
      * form and section labels under both Acts             <- `domain/tds/vocabulary`
      * the e-invoice threshold ladder and its status       <- `domain/gst/irn_scope`
      * which Act an event falls under                      <- `vocabulary.act_for_date`

    The financial year is read from the IST clock on every call, never held in a
    constant, and a year the registry does not hold SAYS so in the registry's own
    sentence instead of being answered from another year's figures.

WHAT IS DELIBERATELY NOT GENERATED, AND SAID SO IN THE PROMPT
    * **GST registration thresholds.** No registry holds them (they differ by
      supply type and by State and move by notification), and writing a table
      from memory is exactly the confident-wrong-number this module exists to
      stop. The old prompt typed "Rs 40L goods, Rs 20L services, Rs 10L special
      category states", the last of which is not even a single figure. The brief
      now says the application holds no such register and to give the section and
      send the CA to confirm. Adding a verified registry is a human step, like the
      PT slabs and the DTAA rates.
    * **2025-Act section numbers for anything but TDS/TCS.** The vocabulary maps
      TDS, TCS and the statements and certificates. It does not map §87A,
      §115BAC, §44AB or the rest, so the brief says the 2025 Act renumbers them
      and the application does not hold how, rather than letting the model guess.

Pure: no database, no model call. `today` is injectable for the tests.
"""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Optional

from core import ist_clock
from domain.money_text import whole_rupees

_CRORE_PAISE = 10_000_000 * 100
_LAKH_PAISE = 100_000 * 100


# ── amounts, written the way a CA writes them ────────────────────────────────

def lakh_label(paise: int) -> str:
    """4_00_000_00 -> '4L', 2_50_000_00 -> '2.5L', 1_00_00_000_00 -> '1Cr'.

    Integer arithmetic. An amount that is not a whole number of tenths of a lakh
    falls back to the full grouped rupee figure rather than a rounded one — a
    slab edge stated approximately is a slab edge stated wrongly.
    """
    if paise >= _CRORE_PAISE and paise % _CRORE_PAISE == 0:
        return f"{paise // _CRORE_PAISE}Cr"
    if paise % _LAKH_PAISE == 0:
        return f"{paise // _LAKH_PAISE}L"
    if paise % (_LAKH_PAISE // 10) == 0:
        tenths = paise // (_LAKH_PAISE // 10)
        return f"{tenths // 10}.{tenths % 10}L"
    return f"Rs {whole_rupees(paise)}"


def _slab_line(slabs) -> str:
    parts, lower = [], 0
    for b in slabs:
        if b.upto_paise is None:
            parts.append(f"above {lakh_label(lower)} {b.rate_percent}%")
        else:
            rate = "Nil" if b.rate_percent == 0 else f"{b.rate_percent}%"
            parts.append(f"{lakh_label(lower) if lower else '0'}-{lakh_label(b.upto_paise)} {rate}")
            lower = b.upto_paise
    return ", ".join(parts)


def _surcharge_line(brackets) -> str:
    ordered = sorted(brackets, key=lambda x: x.above_paise)
    parts = []
    for i, b in enumerate(ordered):
        if i + 1 < len(ordered):
            parts.append(f"{b.rate_percent}% ({lakh_label(b.above_paise)}-"
                         f"{lakh_label(ordered[i + 1].above_paise)})")
        else:
            parts.append(f"{b.rate_percent}% (above {lakh_label(b.above_paise)})")
    return ", ".join(parts)


def _rupees(paise: int) -> str:
    return f"Rs {whole_rupees(paise)}"


def _today(today: Optional[date]) -> date:
    return today or ist_clock.ist_today()


def _fy_of(today: Optional[date]) -> str:
    return ist_clock.ist_fy_label(_today(today))


# ── income tax ───────────────────────────────────────────────────────────────

def income_tax_block(today: Optional[date] = None) -> str:
    """The individual-rate block, from `statutory_rates`.

    Headed with the year the registry has VERIFIED, because that is the only year
    whose figures are known; the current year's own status follows as a separate
    paragraph in the registry's own words. So in FY 2026-27 the table is
    "verified for FY 2025-26" and the next paragraph says FY 2026-27 was carried
    forward and not yet read against its Finance Act — and when a human adds the
    verified 2026-27 entry and moves `LATEST_VERIFIED_FY`, the heading moves with
    it and the paragraph disappears, with no edit here.
    """
    from domain.income_tax import statutory_rates as sr

    verified_fy = sr.LATEST_VERIFIED_FY
    r = sr.RATES_BY_FY[verified_fy]
    ay = ist_clock.assessment_year_for(verified_fy)
    act_year = verified_fy[:4]
    current = _fy_of(today)

    lines = [
        f"INCOME TAX RATES (Finance Act {act_year}, verified for FY {verified_fy} / AY {ay}):",
        f"- New Tax Regime (default): {_slab_line(r.new_regime_slabs)}",
        (f"- Rebate u/s 87A, new regime: no tax payable if total income <= "
         f"{_rupees(r.new_regime_rebate.threshold_paise)}, capped at "
         f"{_rupees(r.new_regime_rebate.max_rebate_paise)}"
         + ("; marginal relief applies just above the limit"
            if r.new_regime_rebate.marginal_relief else "")),
        (f"- Rebate u/s 87A, old regime: up to {_rupees(r.old_regime_rebate.threshold_paise)} "
         f"of total income, capped at {_rupees(r.old_regime_rebate.max_rebate_paise)}"
         + ("" if r.old_regime_rebate.marginal_relief
            else "; no marginal relief — one rupee over the limit loses the whole rebate")),
        (f"- Standard deduction for salaried: {_rupees(r.new_regime_standard_deduction_paise)} "
         f"under the new regime, {_rupees(r.old_regime_standard_deduction_paise)} under the old"),
        f"- Old Tax Regime slabs (below 60): {_slab_line(r.old_regime_slabs_general)}",
        f"- Old Tax Regime slabs (60 to 79): {_slab_line(r.old_regime_slabs_senior)}",
        f"- Old Tax Regime slabs (80 and above): {_slab_line(r.old_regime_slabs_very_senior)}",
        (f"- Surcharge: {_surcharge_line(r.surcharge_brackets)} — old regime in full; "
         f"capped at {r.new_regime_surcharge_cap_percent}% under the new regime"),
        f"- Health & Education Cess: {r.cess_percent}% on tax plus surcharge",
        "",
        (f"These rates are as enacted by the Finance Act {act_year}. If the user asks "
         f"about a LATER financial year, say plainly that a subsequent Finance Act may "
         f"have amended them and that the figures must be confirmed against the Act "
         f"for that year. Do not restate them as current for a year you cannot verify."),
    ]
    gap = sr.fy_rate_gap(current)
    if gap:
        lines.append(f"STATUS OF THE CURRENT YEAR (FY {current}): {gap}")
    else:
        lines.append(f"STATUS OF THE CURRENT YEAR (FY {current}): the registry holds "
                     f"this year's rates and has verified them against its Finance Act.")
    lines.append(
        "These slab and rebate figures are cited under the Income-tax Act 1961's "
        "sections (s. 115BAC, s. 87A, s. 16(ia)). The Income-tax Act 2025 renumbers "
        "them for tax years from 2026-27 and this application does not hold how — "
        "say so rather than citing a 2025-Act section you have not been given.")
    return "\n".join(lines)


# ── the two Acts ─────────────────────────────────────────────────────────────

def _first_fy_under_2025_act() -> str:
    from domain.tds import vocabulary as v
    y = v.COMMENCEMENT.year
    return f"{y}-{str(y + 1)[2:]}"


def _dmy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def act_transition_block(today: Optional[date] = None) -> str:
    """Which Act's labels apply, and BOTH numberings for the period after
    commencement — generated from `domain/tds/vocabulary`.

    The event rule is stated because it is the whole design of the vocabulary:
    the transition is by the CREDIT or the PAYMENT, whichever is earlier, so a
    belated FY 2025-26 statement filed next year is still Form 24Q and still
    cites s. 192. Both vocabularies are permanent; neither replaces the other.
    """
    from domain.tds import vocabulary as v

    today = _today(today)
    old_fy = ist_clock.preceding_fy(_first_fy_under_2025_act())
    new_fy = _first_fy_under_2025_act()
    commence = _dmy(v.COMMENCEMENT)

    statements = "; ".join(
        f"Form {v.statement_form(k, fy_label=old_fy)} -> Form {v.statement_form(k, fy_label=new_fy)}"
        for k in v.STATEMENT_KINDS)
    certificates = "; ".join(
        f"Form {v.certificate_form(k, fy_label=old_fy)} -> Form {v.certificate_form(k, fy_label=new_fy)}"
        + (f" [{v.certificate_note(k, fy_label=new_fy)}]" if v.certificate_note(k, fy_label=new_fy) else "")
        for k in v.CERTIFICATE_KINDS)
    sections = "; ".join(
        f"s.{code} -> s.{v.section_code(code, fy_label=new_fy)}"
        for code in ("192", "194C", "194J", "195", "206C"))

    gap = v.payment_code_gap()
    event_act = v.vocabulary_for(ist_clock.ist_fy_label(today)).act_name
    return "\n".join([
        f"INCOME-TAX ACT 1961 AND INCOME-TAX ACT 2025 — the Income-tax Act 2025 with the "
        f"Income-tax Rules 2026 took effect on {commence} and renumbered the TDS and TCS "
        f"statements, certificates and sections. Rates and thresholds did NOT change with "
        f"the renumbering.",
        f"Which Act applies is decided by the EVENT — the credit or the payment, whichever "
        f"is EARLIER — never by the date of filing. An event before {commence} stays under "
        f"the 1961 Act's forms and sections for ever, belated and revised statements "
        f"included; an event on or after {commence} is under the 2025 Act. "
        f"Today ({_dmy(today)}) falls under the {event_act}.",
        f"For an event on or after {commence} give BOTH numberings, the 2025 label first "
        f"and the 1961 label it replaces beside it. For an earlier event give the 1961 label.",
        f"- Statements (1961 -> 2025): {statements}",
        f"- Certificates (1961 -> 2025): {certificates}",
        f"- Sections (1961 -> 2025): {sections}. The whole 194-series collapsed into "
        f"s.393(1), so s.393(1) has NO single 1961 equivalent — never say which 194-series "
        f"section a s.393(1) line was.",
        f"- {gap.note}",
        (f"A return of income is governed by the Act of the year the income was earned: "
         f"FY {old_fy} income is returned for AY {ist_clock.assessment_year_for(old_fy)} "
         f"under the {v.vocabulary_for(old_fy).act_name}; ITR-1 to ITR-7 were not renumbered."),
    ])


def event_brief(question: str) -> Optional[str]:
    """A per-question note when the question NAMES a date, or None.

    The standing brief tells the model both numberings and the event rule; this
    pins the rule to the date the CA actually typed, so "a payment to a
    contractor on 15 May 2026" is answered with the 2025-Act label beside the
    1961 one instead of depending on the model carrying a table into an
    arithmetic comparison. It is HEDGED: a date in a question is not always the
    credit or payment date, so it says "if that is".

    Dates are read as day-month-year (the Indian convention), by name or number.
    Only the EARLIEST date found is used, which is the event rule's own tiebreak.
    """
    from domain.tds import vocabulary as v

    found = _dates_in(question or "")
    if not found:
        return None
    event = min(found)
    act = v.act_for_date(event)
    commence = _dmy(v.COMMENCEMENT)
    named = event.strftime("%d %B %Y").lstrip("0")
    if act == v.ACT_2025:
        new_fy = _first_fy_under_2025_act()
        old_fy = ist_clock.preceding_fy(new_fy)
        sec = lambda c: v.section_code(c, fy_label=new_fy)          # noqa: E731
        form = lambda k: (f"Form {v.statement_form(k, fy_label=new_fy)} "          # noqa: E731
                          f"(1961: {v.statement_form(k, fy_label=old_fy)})")
        return (
            f"The question mentions {named}. If that is the date the sum was credited or "
            f"paid (whichever is earlier), the event falls on or after {commence} and the "
            f"Income-tax Act 2025 governs the TDS/TCS: cite BOTH labels — a s.194C, s.194J "
            f"or s.194H payment is s.{sec('194C')} (1961: s.194C, s.194J, s.194H); a "
            f"salary payment is s.{sec('192')} (1961: s.192); a payment to a non-resident "
            f"is s.{sec('195')} (1961: s.195); TCS is s.{sec('206C')} (1961: s.206C). "
            f"Name the statement as {form(v.RESIDENT_NON_SALARY)}, "
            f"{form(v.SALARY)}, {form(v.NON_RESIDENT)} or {form(v.TCS)}. State the "
            f"payment-code position as the standing brief gives it.")
    return (
        f"The question mentions {named}. If that is the date the sum was credited or "
        f"paid (whichever is earlier), the event falls BEFORE {commence}, so the Income-tax "
        f"Act 1961's labels govern for good: cite s.192/194-series/195 and Forms 24Q/26Q/"
        f"27Q/27EQ, and do not substitute the 2025-Act numbering.")


_FULL_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
_MONTHS: dict[str, int] = {}
for _i, _name in enumerate(_FULL_MONTHS, start=1):
    _MONTHS[_name.lower()] = _i
    _MONTHS[_name.lower()[:3]] = _i
_MONTHS["sept"] = 9

_NAMED = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/,.]*(" + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")[a-z]*\.?[\s\-/,.]*(\d{4})\b", re.I)
_NUMERIC = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _dates_in(text: str) -> list[date]:
    out: list[date] = []

    def add(y: int, m: int, d: int) -> None:
        try:
            out.append(date(y, m, d))
        except ValueError:
            pass

    for d_, m_, y_ in _NAMED.findall(text):
        add(int(y_), _MONTHS[m_.lower()], int(d_))
    for d_, m_, y_ in _NUMERIC.findall(text):
        add(int(y_), int(m_), int(d_))
    for y_, m_, d_ in _ISO.findall(text):
        add(int(y_), int(m_), int(d_))
    return out


# ── GST ──────────────────────────────────────────────────────────────────────

def einvoice_block() -> str:
    """The Rule 48(4) threshold, in force today and historically, from
    `domain/gst/irn_scope.THRESHOLDS` — with that module's own admission that its
    figures have not been read against the notifications."""
    from domain.gst import irn_scope as irn

    def crore(paise: int) -> str:
        c = paise // _CRORE_PAISE
        return f"Rs {c} crore" if paise % _CRORE_PAISE == 0 else _rupees(paise)

    latest_from, latest_paise, latest_cite = irn.THRESHOLDS[-1]
    ladder = "; ".join(
        f"from {_dmy(date.fromisoformat(frm))}: {crore(p)}" for frm, p, _ in irn.THRESHOLDS)
    lines = [
        (f"E-invoicing (CGST Rule 48(4)): required of a registered person whose aggregate "
         f"turnover in ANY preceding financial year from {irn.FIRST_QUALIFYING_FY} exceeds "
         f"the threshold in force on the invoice's own date — {crore(latest_paise)} today "
         f"({latest_cite}, from {_dmy(date.fromisoformat(latest_from))}). It is a ratchet: "
         f"a client who once crossed it stays inside it. The threshold by date: {ladder}."),
    ]
    if not irn.VERIFIED:
        lines.append(
            "These thresholds are recorded by this application but have NOT been read "
            "against the notifications themselves — say so if the CA is relying on one.")
    return "\n".join(lines)


def registration_threshold_block() -> str:
    """What the prompt says about GST registration limits: that none is held."""
    return (
        "- GST registration (CGST Act s.22 with the notification in force): the "
        "turnover limit depends on whether the supplier deals in goods or services and "
        "on the State, and it moves by notification. This application holds no register "
        "of those limits, so give the section, name the notification, do NOT state a "
        "figure as current, and tell the CA to confirm the limit for the client's State.")


def rates_status_line(today: Optional[date] = None) -> str:
    """One line on which year's income-tax and TDS rates the application has
    verified and what it holds for the current one — for a prompt that carries no
    rate table of its own (the copilot's), so it cannot imply it has one it has
    not read. The sentences are the registries' own."""
    from domain.income_tax import statutory_rates as sr
    from domain.tds import section_rates

    current = _fy_of(today)
    parts = [f"RATE YEARS: the application has verified its income-tax rates for "
             f"FY {sr.LATEST_VERIFIED_FY} and its TDS rates for FY "
             f"{section_rates.LATEST_VERIFIED_TDS_FY}."]
    for gap in (sr.fy_rate_gap(current), section_rates.fy_rate_gap(current)):
        if gap:
            parts.append(gap)
    return " ".join(parts)
