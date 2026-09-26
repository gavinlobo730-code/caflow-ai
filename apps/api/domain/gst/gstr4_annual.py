"""GSTR-4 Annual — a composition dealer's annual return (GST-25, part 3).

CGST Act s.44 with Rule 80(3): FORM GSTR-4 consolidates a composition
registration's YEAR — the one return this product builds that is annual
rather than monthly or quarterly by grain. `domain/gst/composition.py`
computes the QUARTERLY CMP-08 statement this return's own Table 5
reproduces by summing; this module is Tables 4A-4D, the dealer's own
INWARD supplies for the year, plus that same Table-5 summation.

WHY THIS ENGINE COMPUTES SO LITTLE, ON PURPOSE — THE SAME POSTURE AS GSTR-8
    Tables 4A-4D are what a CA RECORDS from the dealer's own purchase
    register and inward-supply documents. This codebase already has a
    purchase ledger, but a composition dealer's counterparty-and-rate-wise
    ANNUAL summary is not a shape that ledger holds, and building a second
    derivation from `purchase_bills` for one annual form risks drifting
    from what the CA actually declares. So — `domain/gst/gstr8.py`'s own
    posture for GSTR-8 Table 3 — this module VALIDATES what is recorded
    (`gstr4_annual_*` tables, migration 422) rather than deriving it from
    the books.

    Table 5 is the opposite: it is EXACTLY four already-computed
    `compute_cmp08` statements (one per quarter of the year), so summing
    them is a derivation with nothing left to validate — see
    `build_table_5`.

THE FOUR TABLES, AND WHICH FEED THE RETURN'S OWN LIABILITY
    4A "b2bor" — inward supplies from a REGISTERED supplier, other than
                 reverse charge. INFORMATIONAL ONLY: the supplier already
                 charged and remitted the tax, so 4A is reported and never
                 summed into this return's liability.
    4B "b2br"  — the same shape as 4A, but reverse charge: the dealer
                 self-assesses this tax under s.9(3)/(4), so it FEEDS the
                 liability.
    4C "b2bur" — inward supplies from an UNREGISTERED person. Reverse
                 charge is a PER-ROW fact here (`reverse_charge`), so only
                 the rows where it is true feed the liability.
    4D "imps"  — import of services (always inter-State, IGST Act s.7(4)),
                 wholly reverse-charged by definition and always feeds the
                 liability.
    See migration 422's own header for the fuller reasoning and the VBA
    citations behind this split.

VALIDATION RULES, TRANSCRIBED FROM THE OFFLINE UTILITY
    - CGST must equal SGST on any row that carries them — s.9's domestic
      levy always splits evenly, on this return exactly as on GSTR-8's
      Table 3 and CMP-08's own row 1.
    - No CGST/SGST on an INTER-STATE row, and no IGST on an INTRA-STATE
      one. For 4A/4B this is DERIVED — the supplier's own state (the first
      two characters of `supplier_gstin`) against the row's
      `place_of_supply` — because those two tables carry no separate
      "supply type" column at all (they are always registered-to-
      registered, so the two GSTINs already settle it). For 4C there is no
      supplier GSTIN to read a state off (the counterparty may hold only a
      PAN, which carries no state), so the recorded `supply_type` field is
      asked directly instead — the per-row fact the table carries for
      exactly this reason. 4D is never checked this way: IGST Act s.7(4)
      already fixes it inter-State by definition, so there is nothing to
      compare it against.
    - `place_of_supply` must equal the FILER'S OWN registration state.
      Confirmed from the VBA to apply identically across all four sheets.
      A row naming a different state is not silently accepted; it is
      named, because either the state was mistyped or the row belongs on
      a different registration's return.

WHAT IS DELIBERATELY NOT HERE — see migration 422's own header for why:
    Table 5 (below) and Table 7 (TDS/TCS credit) are both portal-populated;
    the "outward supply by rate" summary (rows 7-12, JSON key "outsupply")
    is CA-typed with no confirmed statutory shape to derive it from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

VERIFIED = False

TABLE_7_NOT_BUILT = (
    "Table 7 (TDS/TCS credit received) is populated by the portal itself "
    "from GSTR-7/GSTR-8 filed by others against this GSTIN — nothing here "
    "integrates with the portal to read it, and a figure typed from memory "
    "would be worse than the honest gap.")

TABLE_6_OUTWARD_SUMMARY_NOT_BUILT = (
    "The outward-supply-by-rate summary (rows 7-12) is typed directly on "
    "the offline utility's own worksheet and is not derived from anything "
    "else in it — its statutory meaning could not be confirmed from the "
    "VBA text, so it is not modelled here rather than guessed. Record it "
    "directly on the portal's own form.")


@dataclass(frozen=True)
class SupplyRow:
    """One counterparty/rate line — Table 4A or 4B (identical shape)."""
    supplier_gstin: str
    place_of_supply: str
    rate_bps: int
    taxable_value_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int

    @property
    def tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise + self.cess_paise


@dataclass(frozen=True)
class UnregisteredSupplyRow:
    """One counterparty/rate line — Table 4C. `counterparty_pan` and
    `supply_type`/`rate_bps` are nullable — see the module docstring and
    migration 422's CHECK constraints tying the last two to
    `reverse_charge`."""
    counterparty_pan: Optional[str]
    reverse_charge: bool
    place_of_supply: str
    supply_type: Optional[str]   # "Intra-State" | "Inter-State" | None
    rate_bps: Optional[int]
    taxable_value_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int

    @property
    def tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise + self.cess_paise


@dataclass(frozen=True)
class ImportOfServiceRow:
    """One rate line — Table 4D. No CGST/SGST column at all — see the
    module docstring and migration 422."""
    place_of_supply: str
    rate_bps: int
    taxable_value_paise: int
    igst_paise: int
    cess_paise: int

    @property
    def tax_paise(self) -> int:
        return self.igst_paise + self.cess_paise


@dataclass(frozen=True)
class RowFinding:
    """What is wrong with one recorded row, named rather than silently
    accepted or silently refused — the CA typed this, and the return is not
    computed from it, so an inconsistency is reported beside the figures
    rather than blocking the whole statement."""
    table: str            # "4A" | "4B" | "4C" | "4D"
    identifier: str       # the supplier GSTIN, the counterparty PAN, or "—"
    problems: list[str] = field(default_factory=list)


def _supplier_state(supplier_gstin: str) -> Optional[str]:
    """The first two characters of a GSTIN. Never called on a PAN — a PAN
    carries no state at all, which is exactly why the 4C branch below asks
    the recorded `supply_type` field instead rather than trying to derive
    one from `counterparty_pan`."""
    gstin = (supplier_gstin or "").strip()
    return gstin[:2] or None


def _check_split(*, igst: int, cgst: int, sgst: int, interstate: Optional[bool],
                 problems: list[str]) -> None:
    if cgst != sgst:
        problems.append(
            f"CGST ({cgst} paise) does not equal SGST ({sgst} paise) — a "
            f"domestic levy under s.9 always splits evenly between them.")
    if interstate is None:
        return
    if interstate and (cgst or sgst):
        problems.append(
            f"This is an inter-State supply but carries CGST/SGST "
            f"({cgst}/{sgst} paise) rather than IGST.")
    if not interstate and igst:
        problems.append(
            f"This is an intra-State supply but carries IGST ({igst} "
            f"paise) rather than CGST+SGST.")


def _check_filer_state(place_of_supply: str, filer_state_code: Optional[str],
                       problems: list[str]) -> None:
    if filer_state_code and place_of_supply and place_of_supply != filer_state_code:
        problems.append(
            f"Place of supply ({place_of_supply}) is not this registration's "
            f"own state ({filer_state_code}). A composition dealer's own "
            f"annual return reports what THIS registration received — check "
            f"whether this row belongs to a different registration.")


def _b2b_finding(table: str, row: SupplyRow,
                 filer_state_code: Optional[str]) -> Optional[RowFinding]:
    problems: list[str] = []
    supplier_state = _supplier_state(row.supplier_gstin)
    interstate = (supplier_state != row.place_of_supply) if supplier_state else None
    _check_split(igst=row.igst_paise, cgst=row.cgst_paise, sgst=row.sgst_paise,
                interstate=interstate, problems=problems)
    _check_filer_state(row.place_of_supply, filer_state_code, problems)
    if not problems:
        return None
    return RowFinding(table=table, identifier=row.supplier_gstin, problems=problems)


_SUPPLY_TYPE_IS_INTERSTATE = {"Intra-State": False, "Inter-State": True}


def _urp_finding(row: UnregisteredSupplyRow,
                 filer_state_code: Optional[str]) -> Optional[RowFinding]:
    problems: list[str] = []
    if row.reverse_charge:
        if row.supply_type is None:
            problems.append(
                "Reverse charge is recorded but the supply type "
                "(Intra-State or Inter-State) is not, so the CGST/SGST-"
                "versus-IGST split cannot be checked.")
        interstate = _SUPPLY_TYPE_IS_INTERSTATE.get(row.supply_type or "")
        _check_split(igst=row.igst_paise, cgst=row.cgst_paise, sgst=row.sgst_paise,
                    interstate=interstate, problems=problems)
    _check_filer_state(row.place_of_supply, filer_state_code, problems)
    if not problems:
        return None
    return RowFinding(table="4C", identifier=row.counterparty_pan or "—",
                      problems=problems)


def _imps_finding(row: ImportOfServiceRow,
                  filer_state_code: Optional[str]) -> Optional[RowFinding]:
    problems: list[str] = []
    _check_filer_state(row.place_of_supply, filer_state_code, problems)
    if not problems:
        return None
    return RowFinding(table="4D", identifier="—", problems=problems)


@dataclass(frozen=True)
class Gstr4AnnualStatement:
    financial_year: str
    b2b_supplies: list[SupplyRow]                 # 4A
    b2b_rc_supplies: list[SupplyRow]              # 4B
    urp_supplies: list[UnregisteredSupplyRow]     # 4C
    import_of_services: list[ImportOfServiceRow]  # 4D
    b2b_total_taxable_paise: int   # 4A total — informational, never in liability
    liability_taxable_paise: int   # 4B + 4C(reverse_charge) + 4D
    liability_tax_paise: int
    findings: list[RowFinding]
    gaps: list[str]


def compute_gstr4_annual(*, financial_year: str,
                         b2b_supplies: list[SupplyRow],
                         b2b_rc_supplies: list[SupplyRow],
                         urp_supplies: list[UnregisteredSupplyRow],
                         import_of_services: list[ImportOfServiceRow],
                         filer_state_code: Optional[str] = None,
                         ) -> Gstr4AnnualStatement:
    """Tables 4A-4D for one composition registration, one financial year.

    `filer_state_code` is the registration's own state (the first two
    characters of ITS gstin) — omit it to skip the place-of-supply-matches-
    the-filer cross-check; it is a check on already-recorded rows, not a
    figure the totals depend on.
    """
    findings: list[RowFinding] = []

    b2b_total = sum(r.taxable_value_paise for r in b2b_supplies)
    for row in b2b_supplies:
        finding = _b2b_finding("4A", row, filer_state_code)
        if finding:
            findings.append(finding)

    liability_taxable = 0
    liability_tax = 0
    for row in b2b_rc_supplies:
        liability_taxable += row.taxable_value_paise
        liability_tax += row.tax_paise
        finding = _b2b_finding("4B", row, filer_state_code)
        if finding:
            findings.append(finding)

    for row in urp_supplies:
        if row.reverse_charge:
            liability_taxable += row.taxable_value_paise
            liability_tax += row.tax_paise
        finding = _urp_finding(row, filer_state_code)
        if finding:
            findings.append(finding)

    for row in import_of_services:
        liability_taxable += row.taxable_value_paise
        liability_tax += row.tax_paise
        finding = _imps_finding(row, filer_state_code)
        if finding:
            findings.append(finding)

    return Gstr4AnnualStatement(
        financial_year=financial_year,
        b2b_supplies=b2b_supplies,
        b2b_rc_supplies=b2b_rc_supplies,
        urp_supplies=urp_supplies,
        import_of_services=import_of_services,
        b2b_total_taxable_paise=b2b_total,
        liability_taxable_paise=liability_taxable,
        liability_tax_paise=liability_tax,
        findings=findings,
        gaps=[TABLE_6_OUTWARD_SUMMARY_NOT_BUILT, TABLE_7_NOT_BUILT],
    )


@dataclass(frozen=True)
class Table5:
    """The annual return's Table 5 — four already-filed CMP-08 statements,
    summed. The portal auto-populates this from the filed quarterlies; this
    reproduces the SAME sum from the SAME four `compute_cmp08` calls this
    product already makes for CMP-08 itself, rather than a second,
    independent computation of one dealer's own quarterly tax that could
    drift from what CMP-08 itself declared.
    """
    financial_year: str
    quarters: list[dict]     # one compute_cmp08-shaped dict per quarter, Q1 first
    outward_taxable_paise: int
    outward_tax_paise: int
    inward_rcm_taxable_paise: int
    inward_rcm_tax_paise: int
    tax_paid_paise: int
    interest_paise: int
    gaps: list[str]


def build_table_5(financial_year: str, quarterly_statements: list[dict]) -> Table5:
    """`quarterly_statements` is four `cmp08_statement()`-shaped dicts, one
    per quarter of the year, Q1 first — see `services/gstr4_annual_service
    .py`, which fetches them via `core.ist_clock.fy_quarters`. Fewer than
    four (a quarter not yet computed) is not refused here — the total is
    simply partial, and the caller's own gap list says which quarters are
    missing (`services/gstr4_annual_service.py`, not this module, knows the
    four periods it asked for).

    INTEREST IS NOT SPLIT BY HEAD: the offline utility's own row 4 carries
    `iamt`/`camt`/`samt`/`csamt` for interest exactly as every other row
    does, but `compute_cmp08` returns interest as a single scalar the
    CALLER supplies (`domain/gst/composition.py`) — nothing in this product
    currently apportions a lump interest figure across the three tax
    heads, so the total is carried and the per-head split is named as a gap
    rather than guessed. An even split across whichever heads happen to
    carry tax that quarter would be exactly the kind of invented figure
    this return must not carry.
    """
    outward_taxable = outward_tax = 0
    inward_taxable = inward_tax = 0
    tax_paid = interest = 0
    for q in quarterly_statements:
        outward = q.get("outward_supplies") or {}
        inward = q.get("inward_rcm_supplies") or {}
        paid = q.get("tax_paid") or {}
        outward_taxable += int(outward.get("taxable_value_paise") or 0)
        outward_tax += int(outward.get("tax_paise") or 0)
        inward_taxable += int(inward.get("taxable_value_paise") or 0)
        inward_tax += int(inward.get("tax_paise") or 0)
        tax_paid += int(paid.get("tax_paise") or 0)
        interest += int(q.get("interest_paise") or 0)

    gaps: list[str] = []
    if interest:
        gaps.append(
            "Interest is a single total across the four quarters and is not "
            "split by tax head (IGST/CGST/SGST/CESS) — the offline "
            "utility's own row 4 wants a per-head figure and this product "
            "does not apportion a lump sum across heads. Split it manually "
            "before keying it in.")

    return Table5(
        financial_year=financial_year,
        quarters=quarterly_statements,
        outward_taxable_paise=outward_taxable,
        outward_tax_paise=outward_tax,
        inward_rcm_taxable_paise=inward_taxable,
        inward_rcm_tax_paise=inward_tax,
        tax_paid_paise=tax_paid,
        interest_paise=interest,
        gaps=gaps,
    )
