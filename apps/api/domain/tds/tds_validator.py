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

    @staticmethod
    def is_higher_rate_applicable(pan: str, is_non_filer: bool, base_rate: float) -> float:
        """
        IT Act Section 206AB: non-filers (ITR not filed for last 2 years) —
        double the rate or 5%, whichever is higher.
        """
        if is_non_filer and pan not in ("PANNOTAVBL", "PANAPPLIED"):
            return max(base_rate * 2, 5.0)
        return base_rate
