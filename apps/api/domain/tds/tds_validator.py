"""
TDS Validation Rules.
IT Act Section 200A — processing of TDS returns.
IT Act Section 206AA — mandatory PAN requirement (20% default rate).
"""
import re

from domain.tds.section_rates import tds_rates_for

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
TAN_REGEX = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")


class TDSValidator:
    @staticmethod
    def validate_pan(pan: str) -> bool:
        if pan in ("PANNOTAVBL", "PANAPPLIED"):
            return True
        return bool(PAN_REGEX.match(pan))

    @staticmethod
    def validate_tan(tan: str) -> bool:
        return bool(TAN_REGEX.match(tan))

    @staticmethod
    def applicable_rate(section: str, has_pan: bool, base_rate: float, fy: str | None = None) -> float:
        """
        IT Act Section 206AA: if PAN not available, rate = max(base_rate, floor).
        R3.10: floor now reads from the FY-versioned registry
        (domain.tds.section_rates), the same source
        domain.tds.tds_computer.resolve_tds() enforces against real
        computed TDS — previously this and that were two independent
        hardcoded 20.0s that could silently drift apart.
        """
        if not has_pan:
            floor_rate_pct = tds_rates_for(fy).section_206aa_floor_rate_bps / 100
            return max(base_rate, floor_rate_pct)
        return base_rate

    #: The first financial year §206AB does not reach. The Finance Act 2025
    #: OMITTED §206AB and §206CCA with effect from 01-04-2025, so a payment on
    #: or after that date carries no higher rate for a non-filer.
    #:
    #: ⚠️ UNCONFIRMED FROM ANY SOURCE IN THIS REPOSITORY OR REACHABLE FROM IT.
    #: Direct egress is refused at this environment's proxy, so the omission
    #: rests on my own reading and not on a page anybody opened. It is written
    #: as a named constant rather than buried in a branch so that confirming or
    #: correcting it is a one-line change.
    SECTION_206AB_OMITTED_FROM_FY = "2025-26"

    @staticmethod
    def is_higher_rate_applicable(pan: str, is_non_filer: bool, base_rate: float,
                                  fy: str | None = None) -> float:
        """IT Act §206AB: a non-filer's rate is twice the section rate or 5%,
        whichever is higher — FOR A PERIOD UP TO 31-03-2025.

        THIS WAS FY-BLIND, AND IT IS DOCUMENTED AS CURRENT LAW (TDS-24).
        `applicable_rate` beside it already takes `fy`; this did not, so it
        answered the same for FY 2019-20 and FY 2026-27 while §206AB was
        omitted by the Finance Act 2025 with effect from 01-04-2025.

        THE FIX IS A PARAMETER, NOT A DELETION, and that is the same call the
        TDS vocabulary makes about the 2025 Act: §206AB governs periods up to
        31-03-2025 INDEFINITELY, including a belated or revised return filed
        today, and this codebase computes for arbitrary past years. Deleting it
        would make an earlier year answer at the ordinary rate, which is a
        wrong number rather than a missing feature.

        `fy` omitted means the CURRENT law, which is the post-omission answer —
        the safe default, because it under-claims a higher rate rather than
        applying one the statute no longer imposes. A caller working on an
        earlier period passes that period's FY.

        NO PRODUCTION CALLER TODAY. `grep 206AB` over apps/api and apps/web
        finds this function, the tests that pin it, and one line of
        `tds_computer.py`'s module header — nothing on the withholding path
        uses it, so the parameter changes no live figure. It is added because
        the docstring's claim to state current law was the defect.
        """
        if fy is not None and str(fy) >= TDSValidator.SECTION_206AB_OMITTED_FROM_FY:
            return base_rate
        if fy is None:
            # Current law: omitted. See the constant above.
            return base_rate
        if is_non_filer and pan not in ("PANNOTAVBL", "PANAPPLIED"):
            return max(base_rate * 2, 5.0)
        return base_rate
