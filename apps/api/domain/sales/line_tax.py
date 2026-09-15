"""One line's CGST, SGST and IGST — the only implementation on this side.

WHY THIS MOVED HERE
    It lived in `routers/sales_invoices.py` as `_compute_line_gst`, and that
    was fine while the sales invoice was the only document with taxed lines.
    SALES-21 added three more — the quotation, the proforma invoice and the
    delivery challan — and a service reaching into a router for a statutory
    calculation is the wrong direction and one refactor from an import cycle,
    which is the reason `domain/fixed_assets/` was carved out of
    `routers/fixed_assets.py`.

    MOVED, not copied. The router re-exports `_compute_line_gst` so every
    existing import still resolves — including
    `tests/generate_gst_parity_vectors.py`, which pins this function against
    `apps/web/lib/money/gstLine.ts` through `shared/gst-parity-vectors.json`.
    A second implementation here would have drifted from the browser mirror
    the fixture exists to hold it to.
"""
from __future__ import annotations


def compute_line_gst(taxable_paise: int, gst_rate_bps: int,
                     is_interstate: bool) -> tuple:
    """CGST, SGST and IGST for one line, in integer paise.

    CGST Act s.8: an intra-State supply attracts CGST + SGST; an inter-State
    supply attracts IGST. Rates in basis points — 1800 bps is 18%.

    THE FULL TAX IS COMPUTED FIRST AND THEN HALVED, never the rate. Splitting
    the rate and flooring each half independently loses up to a paisa whenever
    the full tax is odd (0.25% and 0.10% rates reach this constantly), which
    understates the liability and leaves CGST + SGST short of the IGST an
    identical inter-State supply would attract. SGST carries the odd paisa.
    """
    taxable_paise = int(taxable_paise)
    gst_rate_bps = int(gst_rate_bps)
    if is_interstate:
        return 0, 0, (taxable_paise * gst_rate_bps) // 10000
    full_gst_paise = (taxable_paise * gst_rate_bps) // 10000
    cgst_paise = full_gst_paise // 2
    return cgst_paise, full_gst_paise - cgst_paise, 0
