"""
Regenerate shared/gst-parity-vectors.json — the golden fixture that pins the
frontend's GST preview to the backend's actual arithmetic.

The vectors are computed by calling the REAL backend functions, so the fixture
is authoritative by construction rather than hand-written. Two tests consume it:

  * apps/api/tests/test_gst_parity_vectors.py  — backend still matches the fixture
  * apps/web/lib/money/gstLine.parity.test.ts  — frontend still matches the fixture

If either side's math changes, its test fails. That is the drift guard: the two
implementations cannot diverge silently the way they did before (preview used
Math.round where the server floors, and float-multiplied the taxable base where
the server uses exact decimal + truncation).

Run:  python tests/generate_gst_parity_vectors.py     (from apps/api)
"""
import json
import math
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.sales_invoices import _compute_line_gst, _round_off_paise  # noqa: E402
from domain.gst import discount as gst_discount  # noqa: E402

# .../apps/api/tests/<this file> -> repo root
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
FIXTURE = os.path.join(_REPO_ROOT, "shared", "gst-parity-vectors.json")


def js_round(x: float) -> int:
    """JavaScript's Math.round — half away from zero, NOT Python's banker's
    rounding. The frontend builds rate_paise with it, so the fixture has to
    reproduce that exact number to describe the payload the server receives."""
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


# (label, qty-as-typed, rate-in-rupees-as-typed, gst %, inter-state?)
CASES = [
    # ── The two divergences this fixture exists to prevent ───────────────────
    ("floor-vs-round GST: full tax 1899.9 paise", "1", "105.55", 18, False),
    ("floor-vs-round GST, inter-state",           "1", "105.55", 18, True),
    ("truncate-vs-round taxable: 0.335 x Rs.1",   "0.335", "1.00", 18, False),
    ("truncate-vs-round taxable, larger qty",     "2.675", "1.00", 18, False),
    # ── Binary-float traps in the rupee -> paise and qty x rate steps ────────
    ("float trap: 0.29 rupees",                   "3", "0.29", 18, False),
    ("float trap: 1.005 rupees",                  "1", "1.005", 18, False),
    ("float trap: 0.1 x 0.7",                     "0.1", "0.70", 18, False),
    ("float trap: 8.7 x 1.15",                    "8.7", "1.15", 12, False),
    # ── Odd full-tax amounts (the CGST/SGST split must not lose a paise) ─────
    ("odd tax at 0.25%",                          "1", "300.00", 0.25, False),
    ("odd tax at 0.10%",                          "1", "300.00", 0.1, False),
    ("28 paise @ 18% (full tax 5, splits 2+3)",   "1", "0.28", 18, False),
    ("odd tax at 1.5%",                           "1", "333.33", 1.5, False),
    # ── Every slab the UI offers, so a rate can never be mis-converted ───────
    *[(f"slab {r}% intra", "1", "1234.56", r, False)
      for r in (0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28)],
    *[(f"slab {r}% inter", "1", "1234.56", r, True)
      for r in (0, 0.25, 5, 12, 18, 28)],
    # ── Fractional quantities and scale ──────────────────────────────────────
    ("fractional qty 2.5",                        "2.5", "1234.56", 12, False),
    ("fractional qty 0.001",                      "0.001", "99999.99", 18, False),
    ("hourly billing 7.25 hrs",                   "7.25", "2500.00", 18, False),
    ("large: 1 crore rupees",                     "1", "10000000.00", 18, False),
    ("large qty x large rate",                    "9999", "99999.99", 28, True),
    # ── Degenerate inputs ────────────────────────────────────────────────────
    ("zero rate",                                 "1", "0.00", 18, False),
    ("zero quantity",                             "0", "1234.56", 18, False),
    ("zero GST (exempt supply)",                  "1", "1234.56", 0, False),
]


def build():
    vectors = []
    for label, qty_str, rate_str, gst_pct, inter in CASES:
        # Exactly what apps/web/lib/invoices/lineItemPayload.ts puts on the wire.
        quantity = float(qty_str)
        rate_paise = js_round(float(rate_str) * 100)

        # Exactly what the API then does with it (sales_invoices.py, and
        # identically credit_notes.py / debit_notes.py / purchase_bills.py).
        gst_rate_bps = int(round(float(gst_pct) * 100))
        taxable = int(Decimal(str(quantity)) * rate_paise)
        cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, inter)

        vectors.append({
            "label": label,
            "qty": qty_str,
            "rate": rate_str,
            "gst_rate_percent": gst_pct,
            "is_interstate": inter,
            "payload": {"quantity": quantity, "rate_paise": rate_paise,
                        "gst_rate_bps": gst_rate_bps},
            "expected": {
                "taxable_paise": taxable,
                "cgst_paise": cgst,
                "sgst_paise": sgst,
                "igst_paise": igst,
                "line_total_paise": taxable + cgst + sgst + igst,
            },
        })
    # Document-level cases: several lines summed, then the invoice-level
    # round-off applied the way _create_invoice_core does it (opt-in since
    # migration 247). Exercises the whole preview surface, not just one line.
    documents = []
    for label, idxs, inter, round_off in [
        ("two lines, exact total",        [0, 10], False, False),
        ("two lines, rounding opted in",  [0, 10], False, True),
        ("mixed slabs, exact",            [20, 24, 28], False, False),
        ("mixed slabs, rounding opted in",[20, 24, 28], False, True),
        ("inter-state doc, exact",        [1], True, False),
        ("fractional qty doc, opted in",  [2, 3], False, True),
    ]:
        lines = [CASES[i] for i in idxs]
        t = c = g = i_ = 0
        for _, qty_str, rate_str, gst_pct, _inter in lines:
            quantity = float(qty_str)
            rate_paise = js_round(float(rate_str) * 100)
            bps = int(round(float(gst_pct) * 100))
            tax = int(Decimal(str(quantity)) * rate_paise)
            lc, ls, li = _compute_line_gst(tax, bps, inter)
            t += tax; c += lc; g += ls; i_ += li
        base_total = t + c + g + i_
        ro = _round_off_paise(base_total) if round_off else 0
        documents.append({
            "label": label,
            "is_interstate": inter,
            "round_off_enabled": round_off,
            "lines": [{"qty": q, "rate": r, "gst_rate_percent": p_}
                      for _, q, r, p_, _x in lines],
            "expected": {
                "taxable_paise": t, "cgst_paise": c, "sgst_paise": g,
                "igst_paise": i_, "gst_paise": c + g + i_,
                "round_off_paise": ro,
                "grand_total_paise": base_total + ro,
            },
        })

    # ── §15(3)(a) discounts ─────────────────────────────────────────────────
    # The discount is resolved BEFORE the tax, so every one of these pins the
    # taxable value the server will charge on, not just the arithmetic of the
    # discount itself. The browser mirror is
    # apps/web/lib/money/gstLine.applyDiscountsToLines.
    #
    # Each case is (label, [(qty, rate, gst%, line_pct_bps, line_amt_paise)],
    #               doc_pct_bps, doc_amt_paise, inter-state?).
    DISCOUNT_CASES = [
        ("5% line discount, one line",
         [("1", "1000.00", 18, 500, None)], None, None, False),
        ("flat line discount in paise",
         [("1", "1000.00", 18, None, 2500)], None, None, False),
        ("percentage wins when both are sent",
         [("1", "1000.00", 18, 500, 9999)], None, None, False),
        ("100% discount — a free-of-charge line",
         [("1", "1000.00", 18, 10000, None)], None, None, False),
        ("no discount at all is the old arithmetic",
         [("1", "1000.00", 18, None, None)], None, None, False),
        # The floor: 1/3 of a paise-odd gross. 33333 x 333 // 10000 = 1109.98...
        ("discount floors, never rounds up",
         [("1", "333.33", 18, 333, None)], None, None, False),
        ("2% document discount over two lines, one already discounted",
         [("1", "1000.00", 18, 500, None), ("1", "500.00", 5, None, None)],
         200, None, False),
        # Three equal lines and a discount that does not divide by three: the
        # residue has to land somewhere, and it has to land the same way twice.
        ("document discount with a residue to allocate",
         [("1", "100.00", 18, None, None), ("1", "100.00", 18, None, None),
          ("1", "100.00", 18, None, None)], None, 10, False),
        ("document discount across different slabs",
         [("1", "1000.00", 28, None, None), ("2", "250.00", 5, None, None),
          ("0.5", "800.00", 12, None, None)], 750, None, False),
        ("document discount, inter-state",
         [("1", "1000.00", 18, None, None), ("1", "500.00", 18, None, None)],
         1000, None, True),
        ("a flat document amount that exactly clears the bill",
         [("1", "100.00", 18, None, None)], None, 10000, False),
        ("line and document discounts compound on the NET, not the gross",
         [("1", "1000.00", 18, 1000, None)], 1000, None, False),
    ]

    discounts = []
    for label, raw_lines, doc_pct, doc_amt, inter in DISCOUNT_CASES:
        payload_lines = []
        gross = []
        for qty_str, rate_str, gst_pct, line_pct, line_amt in raw_lines:
            quantity = float(qty_str)
            rate_paise = js_round(float(rate_str) * 100)
            payload_lines.append({
                "qty": qty_str, "rate": rate_str, "gst_rate_percent": gst_pct,
                "discount_percent_bps": line_pct, "discount_paise": line_amt,
                "quantity": quantity, "rate_paise": rate_paise,
            })
            gross.append(int(Decimal(str(quantity)) * rate_paise))

        resolved = gst_discount.apply_to_lines(
            [{"gross_paise": g,
              "discount_percent_bps": pl["discount_percent_bps"],
              "discount_paise": pl["discount_paise"]}
             for g, pl in zip(gross, payload_lines)],
            document_percent_bps=doc_pct, document_amount_paise=doc_amt)

        out_lines, t = [], 0
        c = g_ = i_ = 0
        for pl, gr, r in zip(payload_lines, gross, resolved):
            bps = int(round(float(pl["gst_rate_percent"]) * 100))
            taxable = int(r["taxable_paise"])
            lc, ls, li = _compute_line_gst(taxable, bps, inter)
            out_lines.append({
                "gross_paise": gr,
                "discount_paise": int(r["discount_paise"]),
                "taxable_paise": taxable,
                "cgst_paise": lc, "sgst_paise": ls, "igst_paise": li,
            })
            t += taxable; c += lc; g_ += ls; i_ += li

        discounts.append({
            "label": label,
            "is_interstate": inter,
            "document_discount_percent_bps": doc_pct,
            "document_discount_paise": doc_amt,
            "lines": [{k: pl[k] for k in
                       ("qty", "rate", "gst_rate_percent",
                        "discount_percent_bps", "discount_paise")}
                      for pl in payload_lines],
            "expected": {
                "lines": out_lines,
                "total_gross_paise": sum(gross),
                "total_discount_paise": sum(l["discount_paise"] for l in out_lines),
                "taxable_paise": t,
                "cgst_paise": c, "sgst_paise": g_, "igst_paise": i_,
                "gst_paise": c + g_ + i_,
                "grand_total_paise": t + c + g_ + i_,
            },
        })

    return {
        "discounts": discounts,
        "documents": documents,
        "_comment": (
            "GENERATED by apps/api/tests/generate_gst_parity_vectors.py from the "
            "real backend functions — do not hand-edit. Consumed by "
            "apps/api/tests/test_gst_parity_vectors.py and "
            "apps/web/lib/money/gstLine.parity.test.ts so the frontend preview "
            "and the server can never disagree by a paise."
        ),
        "vectors": vectors,
    }


if __name__ == "__main__":
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with open(FIXTURE, "w") as fh:
        json.dump(build(), fh, indent=2)
        fh.write("\n")
    d = build()
    print(f"wrote {len(d['vectors'])} vectors + {len(d['documents'])} documents "
          f"+ {len(d['discounts'])} discounts -> {FIXTURE}")
