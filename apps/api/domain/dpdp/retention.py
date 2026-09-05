"""
The retention position: which law requires this data kept, whose duty it is,
and the date that duty lapses.

WHY THIS EXISTS

DPDP s. 8(7) obliges a Data Fiduciary to ERASE personal data once consent is
withdrawn or the purpose is served — "unless retention is necessary for
compliance with any law for the time being in force". Rule 8 of the DPDP Rules
2025 carries that into the detail. So every erasure request runs into a prior
question: does another statute require this record to be kept, and until when?

Nobody had written that down. Without it, "tag every row with its retention
expiry" (the Rules 8/14 work) has nothing to write into the column, and every
answer to a data principal is invented on the spot.

WHAT THE CODE DID BEFORE, AND WHY IT IS THE WRONG QUESTION

Every deletion guard in this codebase is REFERENTIAL: `delete_employee` refuses
when a payslip exists, `delete_customer` when an invoice does, `delete_client`
when any history does. Each says, in effect, "something points at this row".

That is a different question from the one DPDP asks, and it fails in a way that
gets worse with time: A REFERENTIAL REFUSAL NEVER LAPSES. A payslip from
FY 2018-19 refuses erasure in 2019 and refuses it identically in 2040, long
after every statute has released it. From 13 May 2027 that is a standing failure
to erase, and the refusal names no statute and no date, so nobody can tell
whether it is right.

A retention duty is the opposite shape: it has an END. The whole point of this
module is that the answer CHANGES on a date, and the date is computable.

THE ANCHOR IS THE PART THAT IS EASY TO GET WRONG

Every one of these periods is measured from a different event, and reading them
all as "N years from the end of the financial year" is wrong in the dangerous
direction — it lapses EARLY, and a record released early is destroyed.

For FY 2020-21, the same books are held under three duties that end on three
different days:

    Companies Act s. 128(5)   eight FYs preceding      31-03-2029
    Income-tax Rule 6F(5)     6 yrs from AY end        31-03-2028
    CGST s. 36                72 mths from GSTR-9 due  31-12-2027

The GST one is the trap: 72 months runs from the DUE DATE OF THE ANNUAL RETURN
(31 December following the FY), not from the FY end — 81 months from the FY end,
not 72. Anchoring it to the FY end would release the record nine months early.

So each rule carries its anchor, and the GST anchor calls
`compliance_engine.gstr9_due_date` rather than restating 31 December: that
module is the single source for every statutory date in this product, and a
second copy of the rule is a second thing to get wrong when a date is extended.

LONGEST DUTY WINS

A payroll record is simultaneously part of the employer's books, an income-tax
record and a provident-fund record. The category is erasable only when the LAST
of them lapses, so the decision takes the maximum. Taking the first, or the
shortest, would authorise destruction while another duty is still running.

WHAT THIS MODULE REFUSES, AND WHY THE REFUSAL POINTS THE OTHER WAY

Elsewhere in this codebase an unmodelled statutory figure means "do not compute"
— an unlisted professional-tax state deducts nothing rather than guessing. Here
the safe direction is REVERSED, because the action being authorised is
destruction and destruction is not reversible:

  * an UNKNOWN category refuses. The registry is closed; a category nobody has
    classified is not silently erasable.
  * a rule whose PERIOD is not established refuses, and names itself as a gap.
    EPF and ESI are both in that state: the duty plainly exists, the period is
    fixed by scheme and regulation rather than by a section anyone here has
    read, and writing "75 years" from a secondary HR source would put a number
    into a refusal sentence that a CA would then rely on. Adding one is a human
    step, like the state PT slabs and the s. 393 payment codes.

A category with NO rule is a different thing from a category with an unread one,
and only the first is erasable. Support correspondence and product telemetry are
there deliberately, to say that somebody looked and found no duty.

WHOSE DUTY IT IS

Almost none of this is PracticeSync's own duty. The books are the CLIENT's to
keep under s. 128; the GST records are the registered person's; the payroll
records are the employer's. The CA firm holds its own PMLA duty, and
PracticeSync holds the DPDP access-log floor. A refusal that does not say whose
duty it is tells an employee "we won't delete this" when the truthful answer is
"your employer must keep this until 2029" — so `duty_holder` is on every rule
and reaches the sentence.

SOURCING

Search results only; no primary source could be fetched (indiankanoon and
taxinformation.cbic.gov.in are both blocked by the network egress proxy from
this environment). Grades follow docs/compliance/00-how-to-read-this.md and are
carried per rule in `confidence`, so a reader can see which numbers are
corroborated and which are one source deep. Verified 2026-09-05; see
docs/compliance/06-data-protection-dpdp.md.

TODO(compliance): docs/compliance/06-data-protection-dpdp.md
    EPF and ESI hold payroll records under periods that are NOT established
    here, so every payroll erasure is refused on that ground whatever the dates
    say. Closing it needs somebody to read the EPF Scheme's record-keeping
    paragraph and the ESI regulation covering the register of employees, and add
    the periods to `_RULES`. Until then the refusal names the gap — which is the
    point, but it is a gap. See §5b.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from core.ist_clock import ist_fy_label, ist_today, normalise_fy_label
from services.compliance_engine import gstr9_due_date

# Whose duty the retention is. Not decoration: it decides what the refusal
# sentence can honestly say (see the module docstring).
DUTY_CLIENT = "client"      # the accounting entity whose books these are
DUTY_FIRM = "firm"          # the CA firm, in its own right
DUTY_PLATFORM = "platform"  # PracticeSync

#: Confidence in the period, on the docs/compliance/00 scale. Nothing here is
#: "primary": no source could be fetched directly from this environment.
CORROBORATED = "corroborated"   # several independent sources agree on the number
SECONDARY = "secondary"         # one commentary source, uncontradicted
NOT_ESTABLISHED = "not-established"  # the duty is real; the period is not written here


class Anchor(str, Enum):
    """What the period is measured FROM. See the module docstring — this is the
    part that reads as interchangeable and is not."""

    FY_END = "fy_end"
    ASSESSMENT_YEAR_END = "assessment_year_end"
    GST_ANNUAL_RETURN_DUE = "gst_annual_return_due"
    EVENT = "event"


class RetentionError(ValueError):
    """A retention question that cannot be answered as asked."""


def _plus_years(d: date, years: int) -> date:
    """`d` plus whole years, clamping 29 February to 28 February.

    Only the EVENT anchor can land on a leap day — the statutory anchors are all
    31 March or 31 December — but a PMLA business relationship can end on any
    date, and date(2025, 2, 29) raises."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def _fy_end_year(fy_label: str) -> int:
    """2021 for '2020-21' — the calendar year the financial year ends in.

    Normalised rather than prefix-parsed. `fy_bounds` is deliberately lenient
    because its callers already know the label is a label; here the label drives
    a date that AUTHORISES DELETION, and '2020-99' silently meaning 2020-21
    would compute a lapse date for a year nobody asked about."""
    return int(normalise_fy_label(fy_label, field="financial year").split("-")[0]) + 1


@dataclass(frozen=True)
class Rule:
    """One statutory retention duty."""

    key: str
    statute: str
    provision: str
    duty_holder: str
    anchor: Anchor
    years: int | None       # None => the period is not established here
    period_words: str       # how the statute itself puts it
    confidence: str
    note: str = ""

    @property
    def period_established(self) -> bool:
        return self.years is not None

    def retained_until(
        self, *, fy_label: str | None = None, event_date: date | None = None
    ) -> date | None:
        """The LAST day this duty requires the record to be held.

        None when the period is not established — which is not "no duty", and
        callers must not read it as permission. See `erasure_decision`.
        """
        if self.years is None:
            return None
        if self.anchor is Anchor.EVENT:
            if event_date is None:
                raise RetentionError(
                    f"{self.statute} {self.provision} runs from an event date "
                    f"({self.period_words}); none was given.")
            return _plus_years(event_date, self.years)

        if fy_label is None:
            raise RetentionError(
                f"{self.statute} {self.provision} runs from a financial year "
                f"({self.period_words}); none was given.")
        end_year = _fy_end_year(fy_label)

        if self.anchor is Anchor.FY_END:
            # s. 128(5) requires the eight financial years IMMEDIATELY PRECEDING
            # the current one, so FY 2020-21 (ending 2021) is still within reach
            # throughout FY 2028-29 and is released on 1 April 2029.
            return date(end_year + self.years, 3, 31)
        if self.anchor is Anchor.ASSESSMENT_YEAR_END:
            # The AY follows the FY, so its end is one year further out. Six
            # years from the END OF THE AY is seven from the end of the FY.
            return date(end_year + 1 + self.years, 3, 31)
        if self.anchor is Anchor.GST_ANNUAL_RETURN_DUE:
            # compliance_engine owns every statutory date in this product.
            return _plus_years(gstr9_due_date(end_year), self.years)
        raise RetentionError(f"unhandled anchor {self.anchor}")  # pragma: no cover


# ── The rules ────────────────────────────────────────────────────────────────

_RULES: tuple[Rule, ...] = (
    Rule(
        key="companies_act_books",
        statute="Companies Act 2013",
        provision="s. 128(5)",
        duty_holder=DUTY_CLIENT,
        anchor=Anchor.FY_END,
        years=8,
        period_words="the eight financial years immediately preceding a financial year",
        confidence=CORROBORATED,
        note=("Where an investigation has been ordered under Chapter XIV the "
              "Central Government may direct a longer period. Not modelled: it "
              "is a direction served on a particular company, not a rule."),
    ),
    Rule(
        key="income_tax_books",
        statute="Income-tax Rules 1962",
        provision="r. 6F(5)",
        duty_holder=DUTY_CLIENT,
        anchor=Anchor.ASSESSMENT_YEAR_END,
        years=6,
        period_words="six years from the end of the relevant assessment year",
        confidence=CORROBORATED,
        note=("Where an assessment is reopened under s. 147 within the s. 149 "
              "window, the books kept at the time of reopening must be held "
              "until that assessment is complete. Not modelled: it depends on a "
              "notice this product does not hold."),
    ),
    Rule(
        key="gst_records",
        statute="CGST Act 2017",
        provision="s. 36",
        duty_holder=DUTY_CLIENT,
        anchor=Anchor.GST_ANNUAL_RETURN_DUE,
        years=6,
        period_words=("seventy-two months from the due date of furnishing the "
                      "annual return for the year"),
        confidence=CORROBORATED,
        note=("Where an appeal, revision or investigation is pending, one year "
              "after its final disposal or the seventy-two months, WHICHEVER IS "
              "LATER. Not modelled: this product does not know about a pending "
              "appeal."),
    ),
    Rule(
        key="pmla_kyc",
        statute="Prevention of Money-Laundering Act 2002",
        provision="s. 12",
        duty_holder=DUTY_FIRM,
        anchor=Anchor.EVENT,
        years=5,
        period_words=("five years from the completion of the transaction or the "
                      "end of the business relationship, whichever is later"),
        confidence=SECONDARY,
        note=("Reaches a CA in practice only for the activities in the Ministry "
              "of Finance notification of 03-05-2023 — not every engagement. "
              "Whether a given client relationship is caught is a judgement for "
              "the firm, so this rule is never applied automatically."),
    ),
    Rule(
        key="epf_records",
        statute="EPF & MP Act 1952 (now the Code on Social Security 2020)",
        provision="the Scheme's record-keeping obligation",
        duty_holder=DUTY_CLIENT,
        anchor=Anchor.FY_END,
        years=None,
        period_words="not established here",
        confidence=NOT_ESTABLISHED,
        note=("The duty is certain and the period is not. The figure that comes "
              "back from search is 75 years from the date of entry, sourced to "
              "HR commentary rather than to a paragraph of the Scheme. A "
              "provident-fund entitlement is lifelong, so a very long period is "
              "plausible — which is exactly why guessing it is unsafe: it would "
              "put a specific date into a refusal a CA then relies on. Read the "
              "Scheme, add the paragraph and the period."),
    ),
    Rule(
        key="esi_records",
        statute="Employees' State Insurance Act 1948",
        provision="the General Regulations 1950",
        duty_holder=DUTY_CLIENT,
        anchor=Anchor.FY_END,
        years=None,
        period_words="not established here",
        confidence=NOT_ESTABLISHED,
        note=("Regulation 66 gives five years from the last entry for the "
              "ACCIDENT BOOK specifically. Whether the same period governs the "
              "register of employees is asserted by secondary sources and was "
              "not confirmed against the regulation that covers it. A period "
              "read off the wrong regulation is worse than none."),
    ),
    Rule(
        key="dpdp_access_logs",
        statute="DPDP Rules 2025",
        provision="r. 6",
        duty_holder=DUTY_PLATFORM,
        anchor=Anchor.EVENT,
        years=1,
        period_words="logs of personal-data access retained for at least one year",
        confidence=CORROBORATED,
        note=("A FLOOR, not a ceiling — the only rule here that sets a minimum "
              "rather than releasing anything. audit_log is append-only by "
              "trigger, so the floor is met by construction; the risk is "
              "somebody adding a purge later. In force 13-05-2027."),
    ),
)

RULES: dict[str, Rule] = {r.key: r for r in _RULES}


# ── The categories ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Category:
    key: str
    label: str
    holds: str
    tables: tuple[str, ...]
    rules: tuple[str, ...]

    @property
    def has_no_duty(self) -> bool:
        return not self.rules


_CATEGORIES: tuple[Category, ...] = (
    Category(
        key="books_of_account",
        label="books of account",
        holds=("a sole proprietor's or partner's name, PAN and bank details on "
               "the documents that make up the ledger"),
        tables=("journal_entries", "journal_lines", "client_sales_invoices",
                "purchase_bills", "receipts", "payments"),
        rules=("companies_act_books", "income_tax_books", "gst_records"),
    ),
    Category(
        key="gst_returns",
        label="GST returns and their working papers",
        holds="the supplier's and recipient's GSTIN, and a proprietor's PAN within it",
        tables=("gstr1_returns", "gstr3b_returns", "gst_filings"),
        rules=("gst_records", "companies_act_books"),
    ),
    Category(
        key="payroll",
        label="payroll records",
        holds=("an employee's PAN, UAN, ESIC number, date of birth, bank "
               "account, salary and Form 12BB declarations — the highest-"
               "exposure personal data in the product"),
        tables=("payroll_employees", "payroll_slips", "payroll_runs",
                "payroll_it_declarations", "payroll_perquisites"),
        rules=("income_tax_books", "companies_act_books", "epf_records", "esi_records"),
    ),
    Category(
        key="tds_records",
        label="TDS deductions, challans and statements",
        holds="the deductee's PAN and the amounts deducted against it",
        tables=("tds_deductions", "tds_returns", "tds_challans"),
        rules=("income_tax_books", "companies_act_books"),
    ),
    Category(
        key="income_tax_records",
        label="income-tax computations and returns",
        holds="an individual assessee's whole return",
        tables=("itr_computations", "capital_gains_records"),
        rules=("income_tax_books",),
    ),
    Category(
        key="client_onboarding",
        label="client onboarding and KYC documents",
        holds="PAN, GSTIN, identity documents and the engagement record",
        tables=("clients", "client_documents", "engagement_letters"),
        rules=("pmla_kyc",),
    ),
    Category(
        key="access_logs",
        label="access and audit logs",
        holds=("who read or changed what, and when — the actor's identity by "
               "construction"),
        tables=("audit_log", "login_events", "activity_logs"),
        rules=("dpdp_access_logs",),
    ),
    Category(
        key="support_correspondence",
        label="support correspondence",
        holds="whatever a person put in a message to the firm",
        tables=("notifications",),
        rules=(),
    ),
    Category(
        key="product_telemetry",
        label="product telemetry",
        holds="which screens an account opened, and when",
        tables=("activity_logs",),
        rules=(),
    ),
)

CATEGORIES: dict[str, Category] = {c.key: c for c in _CATEGORIES}


# ── The decision ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ErasureDecision:
    """Whether retention releases this category, and the sentence saying why."""

    category: str
    erasable: bool
    retained_until: date | None
    reason: str
    live_rules: tuple[str, ...] = ()
    gap_rules: tuple[str, ...] = ()

    @property
    def is_gap(self) -> bool:
        return bool(self.gap_rules)


def _fmt(d: date) -> str:
    return d.strftime("%d %B %Y").lstrip("0")


def retained_until(
    category_key: str,
    *,
    fy_label: str | None = None,
    event_date: date | None = None,
) -> date | None:
    """The latest date any established rule holds this category. None if every
    rule is unestablished or there are none — NOT a statement that it is
    erasable; ask `erasure_decision` for that."""
    category = CATEGORIES.get(category_key)
    if category is None:
        raise RetentionError(f"no retention position is written for {category_key!r}")
    dates = []
    for key in category.rules:
        rule = RULES[key]
        if not rule.period_established:
            continue
        if rule.anchor is Anchor.EVENT and event_date is None:
            continue
        if rule.anchor is not Anchor.EVENT and fy_label is None:
            continue
        got = rule.retained_until(fy_label=fy_label, event_date=event_date)
        if got is not None:
            dates.append(got)
    return max(dates) if dates else None


def erasure_decision(
    category_key: str,
    *,
    fy_label: str | None = None,
    event_date: date | None = None,
    today: date | None = None,
) -> ErasureDecision:
    """Does retention release this category, and if not, under what and until when.

    Every uncertain answer refuses. An unknown category refuses; a rule whose
    period is not established refuses and is named as a gap. The action being
    authorised is destruction, so "we are not sure" cannot mean "go ahead".
    """
    today = today or ist_today()
    category = CATEGORIES.get(category_key)
    if category is None:
        return ErasureDecision(
            category=category_key,
            erasable=False,
            retained_until=None,
            reason=(f"No retention position is written for {category_key!r}, so "
                    f"erasure is refused. An unclassified category is not an "
                    f"unregulated one — classify it in domain/dpdp/retention.py "
                    f"before erasing anything under it."),
        )

    if category.has_no_duty:
        return ErasureDecision(
            category=category_key,
            erasable=True,
            retained_until=None,
            reason=(f"No statutory retention duty was identified for "
                    f"{category.label}. DPDP s. 8(7) therefore applies "
                    f"unqualified: erase when the purpose is served or consent "
                    f"is withdrawn."),
        )

    live: list[tuple[date, Rule]] = []
    gaps: list[Rule] = []
    unanswerable: list[Rule] = []

    for key in category.rules:
        rule = RULES[key]
        if not rule.period_established:
            gaps.append(rule)
            continue
        try:
            until = rule.retained_until(fy_label=fy_label, event_date=event_date)
        except RetentionError:
            unanswerable.append(rule)
            continue
        if until is not None and until >= today:
            live.append((until, rule))

    # THREE KINDS OF REFUSAL, AND ALL OF THEM GET SAID.
    #
    # An early version returned on the first one it found, which hid the others:
    # a payslip whose month could not be read reported "tell me the period" and
    # never mentioned that EPF and ESI hold the record under periods nobody has
    # established — and those two do not depend on the period at all. A refusal
    # that names one of three reasons invites the reader to fix that one and
    # expect the record to be released.
    #
    # Order is by what the reader can act on: a date first, then a question they
    # can answer, then a duty that needs somebody to go and read a statute.
    parts: list[str] = []
    longest: date | None = None

    if live:
        longest, rule = max(live, key=lambda pair: pair[0])
        others = len(live) - 1
        also = (" 1 shorter duty also applies." if others == 1
                else f" {others} shorter duties also apply." if others > 1 else "")
        parts.append(
            f"Erasure refused: {rule.statute} ({rule.provision}) requires the "
            f"{rule.duty_holder} to keep {category.label} for "
            f"{rule.period_words} — until {_fmt(longest)}.{also}")

    if unanswerable:
        first = unanswerable[0]
        lead = "Erasure refused: " if not parts else "Separately, "
        parts.append(
            f"{lead}{first.statute} ({first.provision}) measures its period "
            f"from {first.period_words}, and the request did not say which. Ask "
            f"again naming the period the record belongs to.")

    if gaps:
        first = gaps[0]
        more = ("" if len(gaps) == 1
                else f" {len(gaps) - 1} further duty is in the same state."
                if len(gaps) == 2
                else f" {len(gaps) - 1} further duties are in the same state.")
        lead = "Erasure refused: " if not parts else "It is also the case that "
        parts.append(
            f"{lead}{first.statute} ({first.provision}) requires the "
            f"{first.duty_holder} to keep {category.label}, and that period is "
            f"NOT established in this product, so no release date can be given "
            f"for it.{more} Establishing it is a human step — read the "
            f"provision and add it to domain/dpdp/retention.py.")

    if parts:
        if live:
            parts.append("DPDP s. 8(7) does not displace a retention duty "
                         "imposed by another law.")
        return ErasureDecision(
            category=category_key,
            erasable=False,
            # Published only when every duty over this category is both
            # established and answerable. A date beside an unread or unanswered
            # duty reads as "free on this date", and it is not.
            retained_until=longest if not (gaps or unanswerable) else None,
            reason=" ".join(parts),
            live_rules=tuple(r.key for _, r in live),
            gap_rules=tuple(r.key for r in gaps),
        )

    return ErasureDecision(
        category=category_key,
        erasable=True,
        retained_until=None,
        reason=(f"Every statutory retention duty over {category.label} has "
                f"lapsed. Nothing in this position refuses erasure."),
    )


def decision_for_record_date(
    category_key: str,
    record_date: date | None,
    *,
    today: date | None = None,
) -> ErasureDecision:
    """`erasure_decision` for a category anchored to the financial year a RECORD
    belongs to.

    The LATEST record decides: retention runs from the financial year of the
    record, so the most recent one is held longest and is the only one that
    matters to whether the party may go. `None` asks without a period, which
    refuses and says what to ask again with — never silently permits.

    Shared by the customer and vendor deletes so the derivation exists once. The
    payroll delete has its own, because its input is a run month rather than a
    document date.
    """
    fy = ist_fy_label(record_date) if record_date is not None else None
    return erasure_decision(category_key, fy_label=fy, today=today)


def position() -> list[dict]:
    """The whole written position, for publication and for the DPA annexe.

    Rule 14 obliges the means of exercising rights to be published, and a
    retention position is what a notice and a data-processing agreement have to
    annexe. Emitting it from the same structure the refusals are computed from
    is the point: a published table maintained by hand drifts from the code that
    actually refuses."""
    out = []
    for category in _CATEGORIES:
        out.append({
            "category": category.key,
            "label": category.label,
            "holds": category.holds,
            "tables": list(category.tables),
            "rules": [
                {
                    "statute": RULES[k].statute,
                    "provision": RULES[k].provision,
                    "duty_holder": RULES[k].duty_holder,
                    "period": RULES[k].period_words,
                    "period_established": RULES[k].period_established,
                    "confidence": RULES[k].confidence,
                    "note": RULES[k].note,
                }
                for k in category.rules
            ],
        })
    return out
