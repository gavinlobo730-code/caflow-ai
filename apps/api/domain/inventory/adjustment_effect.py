"""Does a stock adjustment reach a return? (POST-A-089)

A stock adjustment moves quantity, the stock account and the P&L. None of that is declared on a GST return. ONE thing it
can do is reverse input tax credit: a write-off the CA marks `reverse_itc` credits GST Input and registers the CGST Act
s.17(5)(h) reversal that GSTR-3B Table 4(B)(1) declares (`inventory_service.post_stock_writeoff_journal_entry`). Only
then is it a document that feeds a return, and only then does the client's filed-return lock apply to it.

The effect, not the flag: that function reverses credit only for a DECREASE, only when the CA said so, and only when the
item carries a non-zero GST rate (the amount is the item's rate on the value written off). A surplus, a write-off the CA
did not mark, and a write-off of an item at 0% or no rate declare nothing, so refusing them in a filed month would stop
routine stock-keeping for no protection. Two doors post an adjustment, the single-item route and the count sheet, and
both ask this one question so they cannot disagree about the same shortage.
"""
from __future__ import annotations

from typing import Optional


def reaches_a_return(*, direction: str, reverse_itc: Optional[bool], gst_rate_bps: Optional[int]) -> bool:
    return direction == "decrease" and bool(reverse_itc) and int(gst_rate_bps or 0) > 0
