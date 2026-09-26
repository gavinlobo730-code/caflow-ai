"""Form 3CD — the statement of particulars annexed to a tax audit report.

WHY THIS EXISTS

Every §44AB audit ends in three documents: Form 3CA or 3CB (the auditor's own
report, picking one on whether the accounts are audited under some other law)
and Form 3CD, the forty-four-clause statement of particulars both point at.
The Tax Audit tracker (`/income-tax/tax-audit`) already records which of 3CA
or 3CB applies and tracks the engagement to filing — but nothing in this
product ever assembled 3CD's own particulars, although a majority of them are
figures this codebase already computes somewhere else: the MSME disallowance
under §43B(h), the §16 interest that goes with it, the TDS/TCS compliance
table, brought-forward losses, the client's own stock valuation method, and
the GST-registered/unregistered expenditure split.

A CA preparing a real 3CD today re-keys every one of those from five different
screens. This module puts them in ONE clause-numbered register instead, ANSWERS
what this product can honestly answer, and NAMES every clause it cannot — the
same discipline the ITR keying sheet (IT-17) and the bonus register (PAY-23)
apply: every clause appears, including the ones this product does not reach,
each with its own reason.

WHAT THIS MODULE DOES NOT DO

It computes NOTHING NEW. Every derived clause below reads the answer of a
module that already exists and is already tested — `section_43b_h.py`,
`msmed_interest.py`, the TDS deduction register, `loss_carry_forward.py`,
`clients.inventory_costing_method`, the tax-audit tracker's own stored
`form_type`, and vendor GST registration status. Re-deriving any of them here
would be a second implementation of a rule this codebase already has one of —
the posting-kernel lesson applied to a disclosure rather than a journal.

It writes NOTHING. This is a read-only register assembled at request time,
the same posture as the ITR keying sheet: a document that changes every time
a bill is entered or a payment posted must never be cached, because a cached
answer is wrong the moment the books move under it.

THE CLAUSE TEXT IS TRANSCRIBED FROM THE FORM ITSELF

`CLAUSES` below is transcribed clause-for-clause from the Income-tax Rules
1962, Form 3CD (as reproduced in Taxmann's Income-tax Rules, the copy fetched
for this work on 25-09-2026), including the numbering the 2018, 2021, 2024 and
2025 amendment rules left it in — clauses 28 and 29 are OMITTED rather than
renumbered (the Eighth Amendment Rules, 2025 dropped the §56(2)(viib)/(vii)
share-premium clauses outright), and 36A/36B are letter-suffixed insertions
rather than renumbers of the clauses around them. A CA reading this register
against a printed 3CD form must see the same clause numbers in the same order,
or the register is worse than useless — it looks authoritative and points the
CA at the wrong box.

⚠️ VERIFIED is True for the clause vocabulary (numbers, headings, and which
clauses this product answers) because it was transcribed from the primary
document rather than written from memory or a search-engine summary. It is
NOT a claim that every DERIVATION below is complete — each derived clause's
own `note` says which module it reads and what that module itself still
refuses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ClauseDefinition:
    """One row of the form. `code` is the clause number exactly as printed,
    including a letter suffix (`"22"`, `"26"`, `"36A"`) — never re-numbered."""
    code: str
    heading: str
    #: Whether THIS module can honestly answer it from figures already held.
    derivable: bool
    #: Why not, for a clause this module does not attempt. None where derivable.
    manual_reason: Optional[str] = None


#: Every clause Form 3CD carries, in the form's own order. Clauses 28 and 29
#: are entries with derivable=False and a manual_reason saying they no longer
#: exist on the form, so a caller iterating CLAUSES sees the full numbering
#: and is told why two numbers are missing rather than finding a silent gap.
CLAUSES: tuple[ClauseDefinition, ...] = (
    ClauseDefinition("1", "Name of the assessee", False,
                     "The client's own legal name — read off the client record, "
                     "not derived."),
    ClauseDefinition("2", "Address", False,
                     "The client's registered address — read off the client "
                     "record, not derived."),
    ClauseDefinition("3", "Permanent Account Number or Aadhaar Number", False,
                     "The client's own PAN — read off the client record, not "
                     "derived."),
    ClauseDefinition("4", "Whether the assessee is liable to pay indirect tax "
                          "(GST/excise/service tax/customs), and registration "
                          "number(s)", False,
                     "A fact about which indirect-tax laws reach this client, "
                     "beyond GST — not tracked here."),
    ClauseDefinition("5", "Status (individual, firm, company, etc.)", False,
                     "The client's own legal form — read off the client "
                     "record, not derived."),
    ClauseDefinition("6", "Previous year", False,
                     "The financial year the register is being prepared for — "
                     "a selection, not a derivation."),
    ClauseDefinition("7", "Assessment year", False,
                     "Derived trivially from the previous year (IT Act §2(9) "
                     "with §3) but not worth a clause of its own machinery."),
    ClauseDefinition("8", "Indicate the relevant clause of section 44AB under "
                          "which the audit has been conducted", True),
    ClauseDefinition("8A", "Whether the assessee has opted for the taxation "
                           "under §115BA/115BAA/115BAB/115BAC/115BAD, and "
                           "whether the option was exercised in an earlier "
                           "year", False,
                     "A regime election is recorded on the ITR computation "
                     "workspace, not on this register — see "
                     "domain/income_tax/regime_election.py."),
    ClauseDefinition("9", "If firm or AOP, names of partners/members and "
                          "profit-sharing ratios; changes during the year",
                     False, "Partner/member records are not held by this "
                            "product."),
    ClauseDefinition("10", "Nature of business or profession, and any change "
                           "during the year", False,
                      "The client's own declared business nature — a fact "
                      "recorded on the client profile, not derived."),
    ClauseDefinition("11", "Books of account prescribed under §44AA, books "
                           "maintained, and where kept", False,
                      "This product is itself a book of account for clients "
                      "who use it, but §44AA's prescribed-books question is "
                      "the CA's to answer."),
    ClauseDefinition("12", "Whether the P&L includes profits assessable on a "
                           "presumptive basis (§44AD/44AE/44ADA/44B/44BB/"
                           "44BBA/44BBB/etc.), and the relevant amounts",
                     False,
                     "Whether a presumptive scheme applies is recorded on the "
                     "ITR computation, not tracked as a fact about the books."),
    ClauseDefinition("13", "Method of accounting, any change from the "
                           "preceding year, effect of the change, and "
                           "ICDS-wise adjustment to profit or loss", False,
                      "Method of accounting is a client attribute this "
                      "product does not record distinctly, and no ICDS "
                      "module exists here."),
    ClauseDefinition("14", "Method of valuation of closing stock, and any "
                           "deviation from §145A", True),
    ClauseDefinition("15", "Particulars of a capital asset converted into "
                           "stock-in-trade", False,
                      "Such a conversion is not tracked as its own event — a "
                      "fact the CA records, if it happened."),
    ClauseDefinition("16", "Amounts not credited to the P&L (§28 receipts, "
                           "escalation claims, subsidy/grant, export "
                           "incentives, etc.)", False,
                      "These are, by definition, amounts NOT in the books this "
                      "product holds, and so cannot be derived from them."),
    ClauseDefinition("17", "Land or building transferred for a consideration "
                           "less than the stamp-duty value (§43CA/50C)", False,
                      "Stamp-duty value is an external fact this product does "
                      "not hold against any disposal."),
    ClauseDefinition("18", "Depreciation allowable as per the Income-tax Act, "
                           "block-of-assets particulars", True),
    ClauseDefinition("19", "Amounts admissible under §§32AC, 32AD, 33AB, "
                           "33ABA, 35(1)(i)-(iii), 35(2AA), 35(2AB), 35ABA, "
                           "35ABB, 35AC, 35CCA, 35CCB, 35CCC, 35CCD, 35D, "
                           "35DD, 35DDA, 35E", False,
                      "These are specific investment/expenditure incentives "
                      "this product does not track by section."),
    ClauseDefinition("20", "Bonus/commission to employees not allowable under "
                           "§36(1)(ii), and employee contributions to PF/ESI "
                           "credited after the due date under the relevant Act "
                           "(§36(1)(va))", False,
                      "Employee contributions withheld from salary are "
                      "tracked in payroll, but whether the EMPLOYEE's share "
                      "was credited to the fund by the Act's own due date "
                      "(distinct from the employer's own §43B question, "
                      "clause 26) is not matched against a remittance date "
                      "here."),
    ClauseDefinition("21", "Amounts debited to the P&L that are inadmissible "
                           "— capital expenditure, personal expenditure, "
                           "§40(a) TDS shortfall, §40A(3) cash payments over "
                           "the limit, §40A(7) gratuity provision, §40A(9), "
                           "§269SS/269T contraventions, etc.", False,
                      "A comprehensive disallowance sweep across every one of "
                      "these limbs is not built. The TDS-shortfall limb "
                      "(§40(a)(ia)) is answerable from the TDS register on "
                      "request, but is not assembled into this clause "
                      "automatically."),
    ClauseDefinition("22", "Amount of interest inadmissible under §16 of the "
                           "MSMED Act, 2006", True),
    ClauseDefinition("23", "Payments to persons specified under §40A(2)(b) "
                           "(related-party payments)", False,
                      "§40A(2)(b)'s 'specified person' test (directors, "
                      "relatives, substantial-interest holders) is not what "
                      "the Relationships module tracks, and confusing the two "
                      "would mis-state related-party payments."),
    ClauseDefinition("24", "Amounts deemed to be profits under §32AC/32AD/"
                           "33AB/33ABA/33AC", False,
                      "A clawback of an earlier incentive claim — not "
                      "tracked."),
    ClauseDefinition("25", "Profit chargeable to tax under §41", False,
                      "A balancing charge on an allowance or loss already "
                      "written back — not tracked as its own fact."),
    ClauseDefinition("26", "Sums referred to in §43B (tax/duty/cess/fee, "
                           "employer PF/superannuation/gratuity/other welfare "
                           "fund contribution, bonus/commission, interest on "
                           "specified loans, leave encashment, MSME dues) — "
                           "incurred and paid, incurred and unpaid by the due "
                           "date of furnishing the return", True),
    ClauseDefinition("27", "CENVAT credits availed/utilised and treatment in "
                           "the P&L; prior-period income/expenditure", False,
                      "CENVAT does not exist post-GST for most assessees; "
                      "where a legacy transitional balance survives, it is "
                      "the CA's to state."),
    ClauseDefinition("28", "[Omitted — Eighth Amendment Rules, 2025, w.e.f. "
                           "1-4-2025]", False,
                      "Formerly §56(2)(viib) consideration for shares issued "
                      "above fair market value. Dropped from the form; kept "
                      "here only so the numbering is not silently missing a "
                      "clause."),
    ClauseDefinition("29", "[Omitted — Eighth Amendment Rules, 2025, w.e.f. "
                           "1-4-2025]", False,
                      "Formerly §56(2)(ix)/(x) — advance forfeited, or "
                      "property received without/for inadequate "
                      "consideration. Dropped from the form."),
    ClauseDefinition("30", "Amount borrowed on hundi, or repaid, otherwise "
                           "than through an account payee cheque (§69D)",
                     False, "Hundi transactions are not a document type this "
                            "product models."),
    ClauseDefinition("30A", "Primary adjustment to transfer price under "
                            "§92CE, and the resulting adjustment", False,
                      "No transfer-pricing module exists here."),
    ClauseDefinition("30B", "Interest expenditure exceeding the §94B limit "
                            "(thin capitalisation)", False,
                      "§94B is not modelled — it reaches a narrow class of "
                      "cross-border-associate borrowing this product does "
                      "not track as a distinct fact."),
    ClauseDefinition("30C", "Whether the assessee entered an impermissible "
                            "avoidance arrangement under Chapter X-A (GAAR)",
                     False, "A judgement call for the CA, not a derivable "
                            "fact."),
    ClauseDefinition("31", "Particulars of each loan/deposit/specified sum "
                           "taken, accepted or repaid otherwise than through "
                           "an account payee cheque/bank draft/ECS, ₹20,000 "
                           "or more (§269SS/269T/269ST)", False,
                      "This product does not classify a receipt or payment "
                      "by MODE (cash vs account-payee instrument) against "
                      "these three sections."),
    ClauseDefinition("32", "Brought-forward loss/depreciation allowable; "
                           "§79 shareholding-change bar; §73 speculation "
                           "loss; §73A specified-business loss", True),
    ClauseDefinition("33", "Chapter VIA / Chapter III (§10A, §10AA) "
                           "deductions claimed, section-wise", False,
                      "Chapter VI-A claims are the CA's own entries on the "
                      "ITR computation workspace — reading them into this "
                      "register would need a computation snapshot to exist "
                      "for the year, which this register does not assume. "
                      "See domain/income_tax/chapter_vi_a.py and the "
                      "computation workspace for the figures."),
    ClauseDefinition("34", "TDS/TCS compliance — TAN, section, nature of "
                           "payment, amounts, tax deducted/collected, "
                           "deposited, statements furnished, §201(1A)/"
                           "206C(7) interest", True),
    ClauseDefinition("35", "Quantitative details of principal items traded "
                           "(opening/purchases/sales/closing/shortage) or, "
                           "for a manufacturer, of raw materials and "
                           "finished/by-products", False,
                      "Opening and closing stock by item is available from "
                      "the stock-position report (INV-01/INV-04), but "
                      "assembling it into this clause's own row shape, and "
                      "manufacturing yield/consumption in particular, is not "
                      "built."),
    ClauseDefinition("36", "[Omitted from this position — deemed-dividend "
                           "particulars moved to clause 36A]", False,
                      "Superseded by 36A below."),
    ClauseDefinition("36A", "Deemed dividend received under §2(22)(e) — "
                            "amount and date", False,
                      "Not tracked as a distinct receipt type."),
    ClauseDefinition("36B", "Amount received for buyback of shares under "
                            "§2(22)(f), and cost of acquisition of the shares "
                            "bought back", False,
                      "Not tracked — a new clause from FY 2025-26."),
    ClauseDefinition("37", "Cost audit conducted; disqualification or "
                           "disagreement reported by the cost auditor", False,
                      "An external audit outcome; not tracked here."),
    ClauseDefinition("38", "Audit conducted under the Central Excise Act, "
                           "1944; disqualification or disagreement", False,
                      "Central Excise applies to a narrow surviving class of "
                      "goods post-GST and is not tracked here."),
    ClauseDefinition("39", "Audit under §72A of the Finance Act, 1994 "
                           "(service-tax valuation); disqualification or "
                           "disagreement", False,
                      "Service tax was subsumed into GST from 1 July 2017; "
                      "not tracked here."),
    ClauseDefinition("40", "Turnover, gross profit/turnover, net profit/"
                           "turnover, stock-in-trade/turnover, material "
                           "consumed/finished goods produced — this year and "
                           "the preceding year", False,
                      "Every figure is available from the Profit & Loss for "
                      "both years, but assembling the five named ratios into "
                      "this clause's own row is not built yet."),
    ClauseDefinition("41", "Demand raised or refund issued during the year "
                           "under any tax law other than the Income-tax Act "
                           "and the (repealed) Wealth-tax Act, with "
                           "particulars of the proceedings", False,
                      "Demands/refunds under other tax laws (GST included) "
                      "are not tracked as a distinct fact against a "
                      "proceeding."),
    ClauseDefinition("42", "Whether Form 61/61A/61B (statement of financial "
                           "transactions) is required, and furnishing "
                           "particulars", False,
                      "SFT reporting obligations are not tracked here."),
    ClauseDefinition("43", "Whether the assessee, its parent, or an alternate "
                           "reporting entity must furnish a country-by-"
                           "country report under §286(2), and particulars",
                     False, "CbCR reaches only very large multinational "
                            "groups and is not tracked here."),
    ClauseDefinition("44", "Break-up of total expenditure of entities "
                           "registered and not registered under GST", True),
)

#: The codes this module actually derives — the AST/vocabulary guard reads
#: this rather than re-deriving it from CLAUSES, so the two cannot drift
#: silently.
DERIVABLE_CODES: tuple[str, ...] = tuple(c.code for c in CLAUSES if c.derivable)


@dataclass(frozen=True)
class ClauseAnswer:
    """One clause's answer in the register."""
    code: str
    heading: str
    derived: bool
    #: Whatever the underlying module returned — a dict, a list, a scalar.
    #: None where nothing was derivable (a manual clause, or a derivable one
    #: for which the underlying figure could not be resolved).
    value: Optional[object]
    #: One sentence citing the source module/table, or the reason this
    #: register does not attempt the clause.
    note: str


@dataclass(frozen=True)
class Form3cdRegister:
    financial_year: str
    client_id: str
    clauses: tuple[ClauseAnswer, ...]

    @property
    def derived_count(self) -> int:
        return sum(1 for c in self.clauses if c.derived and c.value is not None)

    @property
    def manual_count(self) -> int:
        return len(self.clauses) - self.derived_count

    def to_dict(self) -> dict:
        return {
            "financial_year": self.financial_year,
            "client_id": self.client_id,
            "derived_count": self.derived_count,
            "manual_count": self.manual_count,
            "clauses": [
                {"code": c.code, "heading": c.heading, "derived": c.derived,
                 "value": c.value, "note": c.note}
                for c in self.clauses
            ],
        }


def build_register(*, client_id: str, financial_year: str,
                   derived: dict[str, tuple[Optional[object], str]],
                   manual: Optional[dict[str, object]] = None) -> Form3cdRegister:
    """Assemble the register from already-fetched figures.

    `derived` maps a clause CODE to (value, note) for every clause THIS
    PRODUCT computed — built by the SERVICE layer, which is where a database
    handle belongs (CLAUDE.md: a domain module holds the rule, a service
    fetches). `derived=True` on the resulting clause means exactly this: a
    live figure came out of an existing module, never a value a human typed.

    `manual` maps a clause CODE to whatever the CA has RECORDED for a clause
    absent from `derived` — read back so a screen can show it, but marked
    `derived=False` regardless of whether it holds a value. A CA's own note
    is not a computation, and conflating the two would make a saved note
    render as a read-only "derived" figure the next time the register opens,
    which is the one thing a manual-entry field must never do.

    A code absent from both, or present in `derived` with value=None, is
    rendered with the clause's own `manual_reason` where the clause is not
    derivable at all, or a generic "could not be resolved" note where it is
    derivable but this call's inputs did not answer it.
    """
    manual = manual or {}
    out: list[ClauseAnswer] = []
    for c in CLAUSES:
        if c.code in derived:
            value, note = derived[c.code]
            out.append(ClauseAnswer(code=c.code, heading=c.heading,
                                    derived=value is not None, value=value,
                                    note=note))
            continue
        if c.code in manual:
            out.append(ClauseAnswer(
                code=c.code, heading=c.heading, derived=False,
                value=manual[c.code],
                note="Recorded by the CA on this register."))
            continue
        if c.derivable:
            out.append(ClauseAnswer(
                code=c.code, heading=c.heading, derived=False, value=None,
                note="Could not be resolved for this client and year — see "
                     "the underlying module's own gaps."))
        else:
            out.append(ClauseAnswer(
                code=c.code, heading=c.heading, derived=False, value=None,
                note=c.manual_reason or "Not derived by this product; the "
                     "CA records this clause directly."))
    return Form3cdRegister(financial_year=financial_year, client_id=client_id,
                           clauses=tuple(out))
