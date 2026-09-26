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

WHAT IS DELIBERATELY NOT MODELLED YET
    Table 4 / 4.1 (amending an EARLIER period's row) — the same staging
    GSTR-1's own amendment tables went through: the base builder first. A
    correction today is a fresh row for the CURRENT period, which is not an
    append-only violation because nothing here posts to the GL or feeds
    another return that would double-count it.

    Which HEAD (IGST vs CGST+SGST) a supply should carry is the CA's own
    entry, never derived here: unlike an ordinary sales invoice, the state
    that matters is the SELLER's, not the operator's, and this product holds
    no record of where each third-party seller is registered beyond the GSTIN
    string itself (which does carry it — `domain/gst/gstin.state_code` reads
    it — but deriving the split from it and then separately being handed the
    already-split iamt/camt/samt would be two sources of truth for one fact).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

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


def _row_problems(row: SupplyRow, period: str, pos_required: bool) -> list[str]:
    problems: list[str] = []
    net = row.net_liable_paise
    tax = row.tax_collected_paise

    if row.cgst_paise != row.sgst_paise:
        problems.append(
            f"CGST ({row.cgst_paise} paise) does not equal SGST "
            f"({row.sgst_paise} paise) — s.52's domestic collection always "
            f"splits evenly between the two.")

    if net <= 0:
        if tax != 0:
            problems.append(
                f"Net amount liable is {net} paise (nil or negative) but "
                f"{tax} paise of tax is recorded as collected.")
    else:
        if tax == 0:
            problems.append(
                f"Net amount liable is {net} paise but no tax is recorded "
                f"as collected.")
        else:
            low_bps, high_bps = _rate_band_bps(period)
            low = (net * low_bps) // 10000
            high = -(-(net * high_bps) // 10000)  # ceil
            if not (low <= tax <= high):
                problems.append(
                    f"Tax collected ({tax} paise) is outside the expected "
                    f"range for this period ({low}-{high} paise on a net "
                    f"amount of {net} paise). The rate this checks against "
                    f"is [S]-graded — see domain/gst/gstr8.py.")

    if pos_required and not row.place_of_supply:
        problems.append(
            "Place of supply is not recorded, and this period's own return "
            "schema requires it (FY 2025-26 onward).")

    return problems


def compute_gstr8(*, period: str,
                  supply_rows: list[SupplyRow],
                  unregistered_rows: list[UnregisteredSupplyRow]) -> Gstr8Statement:
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
        if problems:
            findings.append(RowFinding(supplier_gstin=row.supplier_gstin,
                                       problems=problems))

    total_unregistered_net = sum(r.net_liable_paise for r in unregistered_rows)

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
    )
