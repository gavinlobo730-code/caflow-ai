"""
IT Act §197 — a certificate is a rate, a number, a period AND an amount.

WHY THIS EXISTS (PUR-07 ≡ TDS-13)

    A transport contractor produces a certificate allowing deduction at 0.5%
    instead of 2%. There was nowhere to record it: `vendors` had no certificate
    column of any kind and `resolve_tds` took no certificate parameter, so a
    certificate holder was always withheld at the full section rate. The CA's
    only options were to turn TDS off on the vendor — losing the register row,
    the 26Q deductee line and the challan — or to accept the over-deduction and
    leave the vendor to claim a refund.

WHAT THE STATUTE ACTUALLY GIVES

    §197(1) lets the Assessing Officer certify deduction "at any lower rates or
    no deduction of tax", on an application by the payee. Rule 28AA(4) requires
    the certificate to be issued for a SPECIFIED AMOUNT and to be valid for a
    SPECIFIED PERIOD not exceeding the financial year. §197(2) then obliges the
    payer to deduct at the certified rate "until such certificate is
    cancelled".

    So the certificate is four facts, and a bare percentage on the vendor
    master expresses none of them. That is why PUR-06 DELETED
    `vendors.tds_rate_bps` from the vendor form rather than honouring it.

THREE REFUSALS, EACH FOR A REASON

    * §197 REACHES A LISTED SET OF SECTIONS and no others. §194Q is not among
      them, and neither is §194B. A certificate recorded against a section the
      section does not reach is not a certificate, and applying it would
      under-deduct with nothing behind it.

    * TWO CERTIFICATES IN FORCE ON ONE DATE for one vendor and section is a
      real situation — a fresh certificate issued before the old one expires —
      and the software cannot know which the CA means. It refuses and says so
      rather than picking the lower one, which would be the flattering guess.

    * NO PAN, NO CERTIFICATE. Rule 28AA(2) requires the applicant's PAN, and
      §206AA(4) says no certificate under §197 shall be granted unless the
      application contains it. A certificate against a vendor with no PAN on
      file is a contradiction, and honouring it would defeat §206AA's 20% floor
      in exactly the case the floor exists for.

WHAT IS NOT HERE

    The certificate's CONSUMPTION. The ceiling is a limit on the sums credited
    or paid inside the window, and which documents those are is a question for
    the code that reads documents — services/vendor_tds.py, which already makes
    that pass for the §194C-style FY aggregate. A `consumed_paise` column would
    be a stored copy of a derived figure and would drift the first time a bill
    was edited, cancelled or soft-deleted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

#: The provisions §197(1) actually names. Transcribed from the sub-section, in
#: this codebase's own section vocabulary. NOT a rate table and nothing here
#: depends on a Finance Act — §197's list changes only when §197 itself is
#: amended, which is why it can be held as a literal where a rate could not.
#:
#: §194Q is deliberately absent and so is §194B: §197 does not reach either, so
#: a certificate against them is refused rather than applied. §195 IS reached —
#: a non-resident may hold one, and it displaces the Act rate the same way a
#: treaty does, though not the DTAA comparison itself.
SECTIONS_197 = frozenset({
    "193", "194", "194A", "194C", "194D", "194DA", "194G", "194H",
    "194I", "194J", "194K", "194LA", "194LBB", "194LBC", "194M", "194O",
    "195",
})

REFUSED_SECTION_NOT_COVERED = "section_197_does_not_reach_this_section"
REFUSED_TWO_IN_FORCE = "two_certificates_in_force"
REFUSED_NO_PAN = "certificate_without_a_pan"


@dataclass(frozen=True)
class Certificate:
    """One §197 certificate, as the Assessing Officer issued it."""
    certificate_no: str
    section: str
    rate_bps: int
    valid_from: date
    valid_to: date
    ceiling_paise: int

    def covers(self, on: date) -> bool:
        """Rule 28AA(4)'s period, inclusive of both ends."""
        return self.valid_from <= on <= self.valid_to


@dataclass(frozen=True)
class CertificatePosition:
    """Which certificate applies, or why none does."""
    certificate: Optional[Certificate] = None
    refusal: Optional[str] = None
    detail: str = ""

    @property
    def found(self) -> bool:
        return self.certificate is not None


def _as_date(v) -> Optional[date]:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def certificate_from_row(row: dict) -> Optional[Certificate]:
    """Build one from a `tds_lower_deduction_certificates` row, or None."""
    vf, vt = _as_date(row.get("valid_from")), _as_date(row.get("valid_to"))
    if vf is None or vt is None:
        return None
    return Certificate(
        certificate_no=str(row.get("certificate_no") or "").strip(),
        section=str(row.get("section") or "").upper().strip(),
        rate_bps=int(row.get("rate_bps") or 0),
        valid_from=vf, valid_to=vt,
        ceiling_paise=int(row.get("ceiling_paise") or 0),
    )


def position_for(
    rows: Sequence[dict], *, section: str, fy_start, fy_end, has_pan: bool,
) -> CertificatePosition:
    """The certificate that governs this section for this FINANCIAL YEAR.

    ASKED OF THE YEAR AND NOT OF THE DOCUMENT, which is not a detail. The §194
    series charges on the year's AGGREGATE, so a bill dated after the
    certificate expired still recomputes the whole year's tax — and a resolver
    that dropped the certificate because THIS document is outside the window
    would re-charge the earlier certified slice at the full section rate. On a
    ₹10,00,000 bill inside a 0.5% certificate followed by ₹10,00,000 outside it,
    that withheld ₹40,000 where ₹25,000 was due: the §200 credit does not undo
    it, because the cumulative it is subtracted from was already wrong.

    So the certificate is selected by OVERLAP with the financial year, and
    `Certificate.covers()` then answers the separate question of whether a
    particular document falls inside it. Rule 28AA(4) caps validity at the
    financial year, so at most one per section per year is the ordinary case
    and two is the refusal below.

    `rows` are `tds_lower_deduction_certificates` rows for ONE vendor, already
    firm- and client-scoped by the caller.
    """
    start, end = _as_date(fy_start), _as_date(fy_end)
    key = (section or "").upper().strip()
    if start is None or end is None or not key:
        return CertificatePosition()

    live = [c for c in (certificate_from_row(r) for r in rows)
            if c is not None and c.section == key
            and c.valid_from <= end and c.valid_to >= start]
    if not live:
        return CertificatePosition()

    if key not in SECTIONS_197:
        return CertificatePosition(
            refusal=REFUSED_SECTION_NOT_COVERED,
            detail=(f"A certificate is recorded against §{key}, and §197(1) does "
                    f"not reach that section — so it cannot lower the deduction. "
                    f"Withheld at the section rate."))

    if not has_pan:
        return CertificatePosition(
            refusal=REFUSED_NO_PAN,
            detail=("A §197 certificate is recorded but this payee has no PAN on "
                    "file. §206AA(4) bars a certificate where the application "
                    "does not contain the PAN, so it was not applied and §206AA's "
                    "20% floor stands."))

    if len(live) > 1:
        numbers = ", ".join(sorted(c.certificate_no for c in live))
        return CertificatePosition(
            refusal=REFUSED_TWO_IN_FORCE,
            detail=(f"Two §{key} certificates are in force this year "
                    f"({numbers}). Which one governs is not something this "
                    f"software can decide — end one of the validity periods. "
                    f"Withheld at the section rate meanwhile."))

    return CertificatePosition(certificate=live[0])


def certified_base(cert: Certificate, *, consumed_paise: int,
                   charge_base_paise: int) -> int:
    """How much of a charge base the certificate rate reaches.

    Rule 28AA(4)'s amount is a ceiling on the SUM CREDITED OR PAID, so what is
    left of it is `ceiling − already consumed inside the window`, and the
    charge above that resumes at the section rate. Clamped at both ends: an
    exhausted certificate reaches nothing, and it can never reach more than the
    base being charged.
    """
    headroom = max(0, int(cert.ceiling_paise) - max(0, int(consumed_paise)))
    return max(0, min(int(charge_base_paise), headroom))
