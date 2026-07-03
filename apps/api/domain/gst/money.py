"""Canonical GST money conversions: integer paise -> rupees.

Internal computation is always integer paise. Government JSON is in rupees — but
the two GST returns round differently, so there are two functions:

  * GSTR-1 permits paise, so amounts are 2-decimal rupees.
  * GSTR-3B is reported AND PAID in WHOLE rupees. CGST Act Section 170 rounds any
    tax/interest/penalty/other sum to the nearest rupee, with half a rupee or more
    rounded up; the GSTN 3B form rounds every figure this way. A 2-decimal
    declared liability could never be exactly paid from the whole-rupee cash
    ledger, so the 3B payload must emit whole-rupee integers.

Keeping both here (rather than importing one module's private helper into the
other) means each return uses the rounding its statute requires.
"""
from __future__ import annotations


def paise_to_rupees_2dp(paise: int) -> float:
    """Rupees to 2 decimals (GSTR-1). Exact for integer paise (no rounding needed
    since paise/100 already has at most two decimal places)."""
    return round(paise / 100, 2)


def paise_to_rupees_whole(paise: int) -> int:
    """Rupees rounded to the nearest whole rupee, half rounded UP (CGST Act §170).

    Used by GSTR-3B, which is declared and paid in whole rupees. For a
    non-negative paise amount, (paise + 50) // 100 implements §170 exactly:
    e.g. 45_000_67 -> 45001, 45_000_49 -> 45000, 45_000_50 -> 45001.
    """
    return (paise + 50) // 100
