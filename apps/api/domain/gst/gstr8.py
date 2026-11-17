"""GSTR-8 — the e-commerce operator's monthly TCS statement (GST-25, part 2).

CGST Act s.52(1) makes an "electronic commerce operator" collect tax on "the
net value of taxable supplies made through it by other suppliers" and file
GSTR-8 monthly (Rule 67(1)) declaring what it collected.
`domain/gst/registrations.py` has modelled `TCS_COLLECTOR` and refused it a
GSTR-1/GSTR-3B screen since migration 390; this is the return it owes instead.

WHY THIS ENGINE COMPUTES SO LITTLE, ON PURPOSE
    CMP-08 (the other half of GST-25) reuses a composition dealer's OWN posted
    sales and purchases — a composition dealer's books ARE the return. GSTR-8
    is the opposite kind of fact: Table 3 is what THIRD-PARTY SELLERS supplied
    THROUGH the operator's platform, which never touches this client's own
    ledger (the operator is a marketplace, not the seller). So a CA — reading
    the operator's own MIS or the sellers' reporting to it — RECORDS each
    seller's figures for the period (`ecommerce_operator_supplies`, migration
    421), including the TCS actually collected. This module does not derive
    that split; it CHECKS it, the same posture the GSTN offline utility itself
    takes (see below) — a validator, not a computer, because the figure it
    would otherwise compute is exactly the one the CA is recording.

THE SHAPE, TRANSCRIBED FROM THE OFFLINE UTILITY'S OWN VBA
    docs/compliance/sources/gst-offline-utilities/gstr8/ExportMod.bas.txt and
    ValidateMod.bas.txt. Table 3 carries, per registered supplier: `supR`/
    `retsupR` (gross/returned value of supplies to REGISTERED recipients),
    `supU`/`retsupU` (the same to UNREGISTERED recipients), `pos` (place of
    supply — the utility's own schema carries this ONLY from FY 2025-26
    onward), and `iamt`/`camt`/`samt` (IGST/CGST/SGST collected, typed by the
    filer, never derived by the utility). The "net amount liable" is
    `supR + supU - retsupR - retsupU` — the only figure the utility computes.
    Table 3.1 is the same shape for a seller holding only a Rule 12(1A)
    Enrolment ID (no GSTIN, and no TCS heads — that sheet carries no
    iamt/camt/samt at all).

WHAT THE OFFLINE UTILITY ITSELF VALIDATES, AND WHAT THIS MODULE CHECKS THE
SAME WAY
    - IGST+CGST+SGST must be nonzero whenever the net amount is positive, and
      exactly zero when it is nil or negative — tax is not owed on nothing.
    - CGST must equal SGST exactly (s.52's domestic collection always splits
      evenly; there is no other split the Act describes).
    - THE RATE CHECK FORKS ON THE PERIOD. Before July 2024 the utility
      requires the tax to equal EXACTLY 1% of the net amount; from July 2024
      it accepts a BAND between 0.5% and 1% rather than tightening to an exact
      0.5% — transcribed as read, not narrowed, because narrowing it here
      would refuse a figure the portal itself accepts. This is consistent with
      what is widely reported as Notification 15/2024-Central Tax halving the
      s.52 rate, but the workbook's own literal percentages live on an Excel
      cell value the VBA text does not carry — so ⚠️ EVERY RATE FIGURE BELOW
      IS `[S]`-GRADED and `VERIFIED` is False, the same posture
      `domain/gst/composition.py` takes for the s.10 rates. Confirm against
      the notification before this is relied on to compute money a client
      pays over.

TABLE 4 / 4.1 — AN AMENDMENT OF AN EARLIER MONTH'S ROW (POST-A-056)
    The same utility's `tcsa` (Table 4) and `urda` (Table 4.1) arrays carry a
    row that amends a row of an EARLIER month: `ofp` (the original month),
    `ostin` / `opos` (the original supplier and, from FY 2025-26, place of
    supply) or `oeid` (the original Enrolment ID), then the REVISED figures in
    Table 3's own shape (`stin`, `pos`, `supR`, `retsupR`, `supU`, `retsupU`,
    `iamt`, `camt`, `samt`; for 4.1 `eid`, `grsval`, `supret`), the derived
    `amt`, and a `flag` the filer chooses ("Add" is `A`, "Delete" is `D`).
    `AmendmentRow` / `UnregisteredAmendmentRow` hold one such row and
    `compute_gstr8` checks them with the utility's own rules for them, no more:

      * the original month is EARLIER than the statement's month (the utility
        refuses an amendment dated in or after the Home period);
      * the tax rules Table 3 has, applied to the ORIGINAL month (the utility
        reads the exact-1% / band fork and the place-of-supply boundary off the
        amended row's own year and month, not the statement's);
      * the place of supply, original and revised, is asked from FY 2025-26 on
        and is an error before it (the utility's own comment: "POS is not
        applicable for return periods prior to April 2025");
      * the duplicate key is the original month + original supplier (+ original
        place of supply from FY 2025-26), which migration 617's unique index is.

    WHAT TABLE 4 DOES NOT DO, and the statement says so beside the rows: it
    does NOT net an amendment against the row it amends. The utility carries
    only the revised figures and the original's identifiers, and the figures the
    original month filed live on the portal, not here, so the change in tax
    payable is the portal's to work out. It applies NO limit on how far back an
    amendment may go: the utility restricts the original year to a list read
    from a worksheet range its VBA text does not carry. It does not interpret
    "Add" or "Delete": the filer's choice is kept as chosen. And it checks no
    more of the utility's Table 4 rules than Table 3 checks of its own (the
    supplier-is-not-the-collector and same-State checks, the Enrolment ID shape
    and the 13-digit amount limit are applied to every table since POST-A-458:
    see THE ROW CHECKS ON WHO AND HOW MUCH below).

THE ROW CHECKS ON WHO AND HOW MUCH (POST-A-458)
    Each is the utility's own, read from ValidateMod.bas.txt and MainMod.bas.txt
    in docs/compliance/sources/gst-offline-utilities/gstr8/, and each is a
    FINDING beside the row, as the tax checks are, never a refusal:
      * a supplier GSTIN equal to the collector's own ("Supplier GSTIN can't be
        same as Tax collector GSTIN in Home sheet", `MainMod.DeductorCheck`),
        on Table 3 and on both the original and revised GSTIN of Table 4;
      * a supplier GSTIN whose first two characters differ from the
        collector's ("Supplier State Code should be same as Tax collector State
        Code", `MainMod.samestateCheck`, which compares `Left(..., 2)`), on the
        same three fields;
      * an Enrolment ID that does not match `MainMod.ES_ID_REGEX`
        (`^[0-9]{12}[E][S][0-9a-zA-Z]{1}$`, "Please enter a valid Enrolment
        no.") or whose first two characters differ from the collector's
        ("Please enter same State enrolment no.", the same `samestateCheck`),
        on Table 3.1 and on both Enrolment IDs of Table 4.1;
      * an amount whose rupee figure has more than 13 digits before the
        decimal point ("Amount should not be greater than 13 digits", `length1
        = 13` on `Len(Split(value1, ".", 2)(0))`), on the columns the utility
        loops over: Table 3's four values and its net (columns 5 to 9), Table
        4's four values (10 to 13), Table 3.1's two (4 and 5) and Table 4.1's
        two (8 and 9). The tax heads are not in those loops and are not checked.
    The identity checks need the collector's own GSTIN, which the caller passes;
    without one (`collector_gstin=None`) they are not asked and the statement
    says nothing about them, because a check that cannot be asked is not a pass.

WHAT IS DELIBERATELY NOT MODELLED
    A JSON file for the portal: this module checks what a CA recorded and the
    CA files on the portal, as for Table 3.

    Which HEAD (IGST vs CGST+SGST) a supply should carry is the CA's own
    entry, never derived here: unlike an ordinary sales invoice, the state
    that matters is the SELLER's, not the operator's, and this product holds
    no record of where each third-party seller is registered beyond the GSTIN
    string itself (which does carry it — `domain/gst/gstin.state_code` reads
    it — but deriving the split from it and then separately being handed the
    already-split iamt/camt/samt would be two sources of truth for one fact).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Sequence
from domain.money_sentence import rupee_text

VERIFIED = False

#: [S]-graded — see the module docstring. Notification 15/2024-Central Tax is
#: widely reported as halving the CGST Act s.52 TCS rate; the offline
#: utility's own validation logic proves a change occurred without carrying
#: its literal percentages in the VBA text this was read from.
TCS_RATE_BPS_BEFORE_CHANGE = 100   # 1% — 0.5% CGST + 0.5% SGST, or 1% IGST
TCS_RATE_BPS_FROM_CHANGE = 50      # 0.5% — 0.25% + 0.25%, or 0.5% IGST

#: The month the offline utility's own validation stops requiring an exact 1%
#: and starts accepting a band — read from ValidateMod.bas.txt as "FY < 2024,
#: or FY = 2024 and month in Apr-Jun" for the exact limb, so July 2024 is the
#: first month the band applies. (year, month) rather than a day-precise date,
#: because the utility's own check is coarse to the month — a return covers a
#: whole month and the utility does not ask which day within it a supply fell.
SECTION_52_TCS_RATE_BAND_FROM = (2024, 7)

#: The first financial year (by its own starting calendar year) whose Table 3
#: schema carries `pos` at all — see ExportMod.bas.txt's own FY >= 2025 guard.
POS_FIELD_FROM_FY_STARTING = 2025


def _fy_starting_year(period: str) -> int:
    """MMYYYY -> the calendar year the financial year STARTS in.

    April onward is the same calendar year; January-March belongs to the FY
    that started the previous April. Deliberately local rather than reusing
    `core.ist_clock.ist_fy_label` — that derives from IST wall-clock dates and
    this derives from a stored period key with no time-of-day at all.
    """
    mm, yyyy = int(period[:2]), int(period[2:])
    return yyyy if mm >= 4 else yyyy - 1


def financial_year_label(period: str) -> str:
    start = _fy_starting_year(period)
    return f"{start}-{str(start + 1)[-2:]}"


def _period_start_date(period: str) -> date:
    mm, yyyy = int(period[:2]), int(period[2:])
    return date(yyyy, mm, 1)


def pos_field_required(period: str) -> bool:
    """Whether Table 3's `pos` field applies to this period at all — see
    POS_FIELD_FROM_FY_STARTING. A period before this is not MISSING the
    field; the utility's own schema never carried it."""
    return _fy_starting_year(period) >= POS_FIELD_FROM_FY_STARTING


def _rate_band_bps(period: str) -> tuple[int, int]:
    """(low, high) acceptable TCS basis points on the net amount for `period`.

    Before the change month: exact (low == high == 1%). From it: a band
    between 0.5% and 1%, transcribed from the offline utility's own
    validation rather than tightened to a single figure.
    """
    mm, yyyy = int(period[:2]), int(period[2:])
    if (yyyy, mm) < SECTION_52_TCS_RATE_BAND_FROM:
        return (TCS_RATE_BPS_BEFORE_CHANGE, TCS_RATE_BPS_BEFORE_CHANGE)
    return (TCS_RATE_BPS_FROM_CHANGE, TCS_RATE_BPS_BEFORE_CHANGE)


@dataclass(frozen=True)
class SupplyRow:
    """One registered supplier's figures for the period — Table 3."""
    supplier_gstin: str
    place_of_supply: Optional[str]
    gross_registered_paise: int
    returns_registered_paise: int
    gross_unregistered_paise: int
    returns_unregistered_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int

    @property
    def net_liable_paise(self) -> int:
        """"amt" — the only figure the offline utility itself derives."""
        return (self.gross_registered_paise + self.gross_unregistered_paise
                - self.returns_registered_paise - self.returns_unregistered_paise)

    @property
    def tax_collected_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise


@dataclass(frozen=True)
class UnregisteredSupplyRow:
    """One Enrolment-ID seller's figures for the period — Table 3.1. No TCS
    heads: that sheet carries none."""
    enrolment_id: str
    gross_value_paise: int
    returns_paise: int

    @property
    def net_liable_paise(self) -> int:
        return self.gross_value_paise - self.returns_paise


#: MainMod.bas.txt: `Public Const ES_ID_REGEX = "^[0-9]{12}[E][S][0-9a-zA-Z]{1}$"`, the Enrolment ID the utility accepts (POST-A-458).
ES_ID_REGEX = re.compile(r"^[0-9]{12}[E][S][0-9a-zA-Z]{1}$")

#: ValidateMod.bas.txt: `length1 = 13` against `Len(Split(value1, ".", 2)(0))`, the digits of the rupee figure before the decimal point.
AMOUNT_MAX_INTEGER_DIGITS = 13


def _too_many_digits(paise: int) -> bool:
    """Whether the rupee figure has more than 13 digits before the decimal point (a minus sign is not a digit here: the utility counts the
    text before the point, and the one column that may be negative, the net, is never near the limit with one)."""
    return len(str(abs(int(paise)) // 100)) > AMOUNT_MAX_INTEGER_DIGITS


def _amount_problems(named: Sequence[tuple[str, int]]) -> list[str]:
    return [f"{label} ({rupee_text(v)}) has more than {AMOUNT_MAX_INTEGER_DIGITS} digits before the decimal point, which the offline "
            f"utility refuses." for label, v in named if _too_many_digits(v)]


def _gstin_problems(gstin: str, collector_gstin: Optional[str], which: str) -> list[str]:
    """MainMod.DeductorCheck and MainMod.samestateCheck on one supplier GSTIN field. Nothing when the collector's GSTIN is not known."""
    if not collector_gstin:
        return []
    out: list[str] = []
    g, c = (gstin or "").strip().upper(), collector_gstin.strip().upper()
    if g and g == c:
        out.append(f"The {which} GSTIN is this operator's own GSTIN; the offline utility refuses a supplier that is the tax collector.")
    if g and g[:2] != c[:2]:
        out.append(f"The {which} GSTIN is of State {g[:2]} and this operator's registration is of State {c[:2]}; the offline utility "
                   "refuses a supplier of another State.")
    return out


def _enrolment_problems(eid: str, collector_gstin: Optional[str], which: str) -> list[str]:
    """ES_ID_REGEX and MainMod.samestateCheck on one Enrolment ID field. The shape is asked whatever is known of the collector."""
    e = (eid or "").strip()
    if not ES_ID_REGEX.match(e):
        return [f"The {which} Enrolment ID ({e or 'blank'}) is not in the form the offline utility accepts: twelve digits, then ES, "
                "then one letter or digit."]
    if collector_gstin and e[:2] != collector_gstin.strip()[:2]:
        return [f"The {which} Enrolment ID is of State {e[:2]} and this operator's registration is of State "
                f"{collector_gstin.strip()[:2]}; the offline utility refuses an Enrolment ID of another State."]
    return []


#: The utility's own two answers for an amendment row ("Add" / "Delete" in the sheet, `A` / `D` in the file). Kept as the filer chose; what
#: the portal does with each is not recorded here.
ACTIONS = ("add", "delete")


def _month_key(period: str) -> tuple[int, int]:
    """MMYYYY -> (year, month), the order a return period sorts in (the raw string does not: '012026' < '062025')."""
    return int(period[2:]), int(period[:2])


def original_period_problem(original_period: str, period: str) -> Optional[str]:
    """The sentence for an amendment whose original month is not EARLIER than the statement's, or None.

    The offline utility refuses it ("Month and Year in Amend Sheet should be lesser than in Home Sheet"): an amendment declared in a
    month corrects a row some earlier month already declared, never its own month or a later one.
    """
    if _month_key(original_period) >= _month_key(period):
        return (f"The month being amended ({original_period[:2]}/{original_period[2:]}) is not earlier than this statement's month "
                f"({period[:2]}/{period[2:]}). An amendment corrects a row an earlier month declared.")
    return None


@dataclass(frozen=True)
class AmendmentRow:
    """One Table 4 row: the figures a registered seller's row of an EARLIER month is revised to, and which row that was.

    `original_*` identify the amended row (`ofp`, `ostin`, `opos`); the rest are the revised figures in Table 3's own shape.
    """
    original_period: str
    original_supplier_gstin: str
    original_place_of_supply: Optional[str]
    supplier_gstin: str
    place_of_supply: Optional[str]
    gross_registered_paise: int
    returns_registered_paise: int
    gross_unregistered_paise: int
    returns_unregistered_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    action: str

    @classmethod
    def from_record(cls, r: dict) -> "AmendmentRow":
        """A stored `ecommerce_operator_supply_amendments` row, an absent amount read as nil."""
        return cls(
            original_period=r["original_period"],
            original_supplier_gstin=r["original_supplier_gstin"],
            original_place_of_supply=r.get("original_place_of_supply"),
            supplier_gstin=r["supplier_gstin"],
            place_of_supply=r.get("place_of_supply"),
            gross_registered_paise=int(r.get("gross_registered_paise") or 0),
            returns_registered_paise=int(r.get("returns_registered_paise") or 0),
            gross_unregistered_paise=int(r.get("gross_unregistered_paise") or 0),
            returns_unregistered_paise=int(r.get("returns_unregistered_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            action=str(r.get("action") or ""))

    @property
    def net_liable_paise(self) -> int:
        """"amt" — the revised figures' net, derived as in Table 3 (the one figure the utility computes)."""
        return (self.gross_registered_paise + self.gross_unregistered_paise
                - self.returns_registered_paise - self.returns_unregistered_paise)

    @property
    def tax_collected_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise


@dataclass(frozen=True)
class UnregisteredAmendmentRow:
    """One Table 4.1 row: an Enrolment-ID seller's row of an EARLIER month, revised. No TCS heads, as in Table 3.1."""
    original_period: str
    original_enrolment_id: str
    enrolment_id: str
    gross_value_paise: int
    returns_paise: int
    action: str

    @classmethod
    def from_record(cls, r: dict) -> "UnregisteredAmendmentRow":
        """A stored `ecommerce_operator_unregistered_supply_amendments` row."""
        return cls(
            original_period=r["original_period"],
            original_enrolment_id=r["original_enrolment_id"],
            enrolment_id=r["enrolment_id"],
            gross_value_paise=int(r.get("gross_value_paise") or 0),
            returns_paise=int(r.get("returns_paise") or 0),
            action=str(r.get("action") or ""))

    @property
    def net_liable_paise(self) -> int:
        return self.gross_value_paise - self.returns_paise


@dataclass(frozen=True)
class RowFinding:
    """What is wrong with one supplier's row, named rather than silently
    accepted or silently refused — the CA typed this, and the return is not
    computed from it, so an inconsistency is reported beside the figures
    rather than blocking the whole statement."""
    supplier_gstin: str
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Gstr8Statement:
    period: str
    financial_year: str
    pos_required: bool
    total_net_liable_paise: int
    total_igst_paise: int
    total_cgst_paise: int
    total_sgst_paise: int
    total_unregistered_net_paise: int
    supplier_count: int
    unregistered_supplier_count: int
    findings: list[RowFinding]
    rate_band_bps: tuple[int, int]
    #: Table 4 / 4.1 (POST-A-056): how many amendment rows are recorded for the statement's month, what is wrong with each, and the
    #: sentence saying what this statement does not do with them. Counts only, never a total: a total of revised figures would read as
    #: an amount to add to Table 3's, and the net effect on tax payable is the portal's (see the module docstring).
    amendment_count: int = 0
    unregistered_amendment_count: int = 0
    amendment_findings: list[RowFinding] = field(default_factory=list)
    amendment_note: Optional[str] = None


def _row_problems(row: SupplyRow, period: str, pos_required: bool) -> list[str]:
    problems: list[str] = []
    net = row.net_liable_paise
    tax = row.tax_collected_paise

    if row.cgst_paise != row.sgst_paise:
        problems.append(
            f"CGST ({rupee_text(row.cgst_paise)}) does not equal SGST "
            f"({rupee_text(row.sgst_paise)}) — s.52's domestic collection always "
            f"splits evenly between the two.")

    if net <= 0:
        if tax != 0:
            problems.append(
                f"Net amount liable is {rupee_text(net)} (nil or negative) but "
                f"{rupee_text(tax)} of tax is recorded as collected.")
    else:
        if tax == 0:
            problems.append(
                f"Net amount liable is {rupee_text(net)} but no tax is recorded "
                f"as collected.")
        else:
            low_bps, high_bps = _rate_band_bps(period)
            low = (net * low_bps) // 10000
            high = -(-(net * high_bps) // 10000)  # ceil
            if not (low <= tax <= high):
                problems.append(
                    f"Tax collected ({rupee_text(tax)}) is outside the expected "
                    f"range for this period ({rupee_text(low)} to {rupee_text(high)} on a net "
                    f"amount of {rupee_text(net)}). The rate this checks against "
                    f"is [S]-graded — see domain/gst/gstr8.py.")

    if pos_required and not row.place_of_supply:
        problems.append(
            "Place of supply is not recorded, and this period's own return "
            "schema requires it (FY 2025-26 onward).")

    return problems


#: Said beside the amendment rows whenever there are any. The product records and checks them and does not net them against the rows
#: they amend: those figures are what the original month FILED, which lives on the portal.
AMENDMENT_NOT_NETTED_NOTE = (
    "This month's statement amends rows of earlier months (Table 4 / 4.1). The revised figures are recorded and checked as the "
    "offline utility checks them; they are NOT netted against what each earlier month filed, which is held on the portal and not "
    "here, so the change they make to the tax payable is not in the totals above.")


def _amendment_problems(row: AmendmentRow, statement_period: str, collector_gstin: Optional[str] = None) -> list[str]:
    problems: list[str] = []
    problems.extend(_gstin_problems(row.original_supplier_gstin, collector_gstin, "original supplier's"))
    problems.extend(_gstin_problems(row.supplier_gstin, collector_gstin, "revised supplier's"))
    problems.extend(_amount_problems((("The value of supplies to registered persons", row.gross_registered_paise),
                                      ("The value returned by registered persons", row.returns_registered_paise),
                                      ("The value of supplies to unregistered persons", row.gross_unregistered_paise),
                                      ("The value returned by unregistered persons", row.returns_unregistered_paise))))
    ordering = original_period_problem(row.original_period, statement_period)
    if ordering:
        problems.append(ordering)
    if row.action not in ACTIONS:
        problems.append("The action is neither Add nor Delete.")
    # Table 3's own tax checks, read against the ORIGINAL month (the utility keys the exact-1% / band fork on the amended row's year and
    # month). The place of supply is asked below, with this table's own wording: it concerns the original month, not the statement's.
    problems.extend(_row_problems(row, row.original_period, False))        # type: ignore[arg-type]  # same attributes as SupplyRow
    pos_required = pos_field_required(row.original_period)
    if pos_required:
        if not row.original_place_of_supply:
            problems.append("The original place of supply is not recorded, and the original month's return schema requires it "
                            "(FY 2025-26 onward).")
        if not row.place_of_supply:
            problems.append("The revised place of supply is not recorded, and the original month's return schema requires it "
                            "(FY 2025-26 onward).")
    elif row.original_place_of_supply or row.place_of_supply:
        problems.append("A place of supply is recorded, and the offline utility refuses one for a return period before April 2025.")
    return problems


def _unregistered_amendment_problems(row: UnregisteredAmendmentRow, statement_period: str,
                                     collector_gstin: Optional[str] = None) -> list[str]:
    problems: list[str] = []
    problems.extend(_enrolment_problems(row.original_enrolment_id, collector_gstin, "original"))
    problems.extend(_enrolment_problems(row.enrolment_id, collector_gstin, "revised"))
    problems.extend(_amount_problems((("The gross value", row.gross_value_paise), ("The value returned", row.returns_paise))))
    ordering = original_period_problem(row.original_period, statement_period)
    if ordering:
        problems.append(ordering)
    if row.action not in ACTIONS:
        problems.append("The action is neither Add nor Delete.")
    return problems


def compute_gstr8(*, period: str,
                  supply_rows: list[SupplyRow],
                  unregistered_rows: list[UnregisteredSupplyRow],
                  amendment_rows: Sequence[AmendmentRow] = (),
                  unregistered_amendment_rows: Sequence[UnregisteredAmendmentRow] = (),
                  collector_gstin: Optional[str] = None) -> Gstr8Statement:
    """The statement for one operator registration, one month.

    Reads what a CA has already recorded (`ecommerce_operator_supplies` /
    `..._unregistered_supplies`) and checks it the way the offline utility
    checks a filer's own entry — it does not compute the TCS split, because
    the split IS the fact being recorded.
    """
    pos_required = pos_field_required(period)
    rate_band = _rate_band_bps(period)

    findings: list[RowFinding] = []
    total_net = total_igst = total_cgst = total_sgst = 0
    for row in supply_rows:
        total_net += row.net_liable_paise
        total_igst += row.igst_paise
        total_cgst += row.cgst_paise
        total_sgst += row.sgst_paise
        problems = _row_problems(row, period, pos_required)
        # POST-A-458: the utility's checks on who the supplier is and on how long an amount may be (see the module docstring).
        problems += _gstin_problems(row.supplier_gstin, collector_gstin, "supplier's")
        problems += _amount_problems((("The value of supplies to registered persons", row.gross_registered_paise),
                                      ("The value returned by registered persons", row.returns_registered_paise),
                                      ("The value of supplies to unregistered persons", row.gross_unregistered_paise),
                                      ("The value returned by unregistered persons", row.returns_unregistered_paise),
                                      ("The net amount liable", row.net_liable_paise)))
        if problems:
            findings.append(RowFinding(supplier_gstin=row.supplier_gstin,
                                       problems=problems))

    total_unregistered_net = sum(r.net_liable_paise for r in unregistered_rows)
    for urow in unregistered_rows:
        problems = (_enrolment_problems(urow.enrolment_id, collector_gstin, "seller's")
                    + _amount_problems((("The gross value", urow.gross_value_paise), ("The value returned", urow.returns_paise))))
        if problems:
            findings.append(RowFinding(supplier_gstin=urow.enrolment_id, problems=problems))

    amendment_findings: list[RowFinding] = []
    for amend in amendment_rows:
        problems = _amendment_problems(amend, period, collector_gstin)
        if problems:
            amendment_findings.append(RowFinding(supplier_gstin=amend.original_supplier_gstin, problems=problems))
    for amend_u in unregistered_amendment_rows:
        problems = _unregistered_amendment_problems(amend_u, period, collector_gstin)
        if problems:
            amendment_findings.append(RowFinding(supplier_gstin=amend_u.original_enrolment_id, problems=problems))

    return Gstr8Statement(
        period=period,
        financial_year=financial_year_label(period),
        pos_required=pos_required,
        total_net_liable_paise=total_net,
        total_igst_paise=total_igst,
        total_cgst_paise=total_cgst,
        total_sgst_paise=total_sgst,
        total_unregistered_net_paise=total_unregistered_net,
        supplier_count=len(supply_rows),
        unregistered_supplier_count=len(unregistered_rows),
        findings=findings,
        rate_band_bps=rate_band,
        amendment_count=len(amendment_rows),
        unregistered_amendment_count=len(unregistered_amendment_rows),
        amendment_findings=amendment_findings,
        amendment_note=(AMENDMENT_NOT_NETTED_NOTE if (amendment_rows or unregistered_amendment_rows) else None),
    )
