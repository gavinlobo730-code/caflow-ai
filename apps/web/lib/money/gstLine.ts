/**
 * Canonical client-side mirror of the backend's per-line GST arithmetic.
 *
 * This module is the ONLY place the frontend is allowed to compute line
 * taxable/GST amounts. Every preview (sales invoice, sales credit/debit note,
 * purchase bill and its notes) goes through it, so a preview can never show a
 * figure the server will not save.
 *
 * It mirrors, operation for operation, what the API does with the payload the
 * frontend sends (apps/api/routers/sales_invoices.py — and identically in
 * credit_notes.py, debit_notes.py, purchase_bills.py):
 *
 *     gst_rate_bps = int(round(gst_rate_percent * 100))
 *     taxable      = int(Decimal(str(qty)) * rate_paise)
 *     cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)
 *
 * and _compute_line_gst itself:
 *
 *     full = (taxable * bps) // 10000       # FLOOR, not round
 *     intra: cgst = full // 2; sgst = full - cgst   # SGST carries the odd paise
 *     inter: igst = full
 *
 * Two divergences used to make the preview disagree with the saved invoice by
 * a paise, both fixed here:
 *
 *   1. GST was `Math.round(taxable * pct / 100)` against the backend's floor.
 *      ₹105.55 @ 18% → preview 1900 paise, server 1899.
 *   2. Taxable was `Math.round(qty * rate * 100)` in binary floating point,
 *      against the backend's exact decimal `int(Decimal(str(qty)) * rate_paise)`
 *      which TRUNCATES. qty 0.335 × ₹1.00 → preview 34 paise, server 33.
 *
 * Integer paise throughout — no float ever reaches a stored amount. Exact
 * decimal work is done in BigInt so it matches Python's Decimal rather than
 * approximating it.
 *
 * CGST Act §8: intra-state supply attracts CGST+SGST, inter-state attracts IGST.
 */

const B_ZERO = BigInt(0);
const B_ONE = BigInt(1);
const B_TEN = BigInt(10);

/** 10^n as a bigint. Written as a loop rather than `10n ** BigInt(n)` because
 *  the project's tsconfig sets no `target`, so TS defaults to ES5 and rejects
 *  bigint literals and bigint exponentiation. The runtime supports both. */
function pow10(n: number): bigint {
  let out = B_ONE;
  for (let i = 0; i < n; i++) out *= B_TEN;
  return out;
}

/**
 * Decompose a JS number into the exact (unscaled integer, decimal scale) pair
 * that Python's `Decimal(str(x))` would see.
 *
 * `String(x)` and Python's `repr(float)` both emit the shortest decimal string
 * that round-trips the same IEEE-754 double, so the two agree on every value a
 * quantity field can realistically hold. Exponent form is expanded rather than
 * trusted to parse, so very small/large quantities behave too.
 */
function decimalParts(value: number): { unscaled: bigint; scale: number } {
  if (!Number.isFinite(value)) return { unscaled: B_ZERO, scale: 0 };

  let s = String(value);
  let exponent = 0;
  const eIdx = s.search(/[eE]/);
  if (eIdx !== -1) {
    exponent = parseInt(s.slice(eIdx + 1), 10);
    s = s.slice(0, eIdx);
  }

  let sign = B_ONE;
  if (s.startsWith("-")) {
    sign = -B_ONE;
    s = s.slice(1);
  } else if (s.startsWith("+")) {
    s = s.slice(1);
  }

  let scale = 0;
  const dot = s.indexOf(".");
  if (dot !== -1) {
    scale = s.length - dot - 1;
    s = s.slice(0, dot) + s.slice(dot + 1);
  }
  scale -= exponent;

  let unscaled = BigInt(s === "" ? "0" : s) * sign;
  if (scale < 0) {
    unscaled *= pow10(-scale);
    scale = 0;
  }
  return { unscaled, scale };
}

/** Floor division on BigInt (Python's `//`). BigInt `/` truncates toward zero,
 *  which differs for negative operands — amounts are non-negative in practice,
 *  but matching the operator exactly keeps this a true mirror. */
function floorDiv(a: bigint, b: bigint): bigint {
  const q = a / b;
  return a % b !== B_ZERO && a < B_ZERO !== b < B_ZERO ? q - B_ONE : q;
}

/**
 * Rupees (as typed in the form) → integer paise, exactly as the API payload
 * builder does it. `toInvoiceLinePayload` delegates here so the number the
 * preview reasons about and the number actually sent can never drift apart.
 */
export function ratePaiseFromRupees(rate: string | number): number {
  const parsed = typeof rate === "number" ? rate : parseFloat(rate);
  if (!Number.isFinite(parsed)) return 0;
  return Math.round(parsed * 100);
}

/** Quantity string → the `quantity` number the payload carries. */
export function quantityFromInput(qty: string | number): number {
  const parsed = typeof qty === "number" ? qty : parseFloat(qty);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * GST percentage (18) → basis points (1800), as the backend derives it.
 *
 * Backend uses Python's `round`, which is banker's rounding, where JS rounds
 * half away from zero. No slab in GST_RATES lands on a .5 tie once multiplied
 * by 100, so the two agree on every rate the UI can produce — and the parity
 * fixture pins that for the full slab list.
 */
export function gstRateBpsFromPercent(gstRatePercent: number): number {
  if (!Number.isFinite(gstRatePercent)) return 0;
  return Math.round(gstRatePercent * 100);
}

/**
 * Line taxable value in paise: `int(Decimal(str(qty)) * rate_paise)`.
 * Exact decimal multiplication, then TRUNCATION toward zero — not rounding.
 */
export function taxablePaise(quantity: number, ratePaise: number): number {
  const { unscaled, scale } = decimalParts(quantity);
  const product = unscaled * BigInt(Math.trunc(ratePaise));
  // Python's int() truncates toward zero; BigInt division does the same.
  return Number(product / pow10(scale));
}

export interface LineGstAmounts {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  /** taxable + all GST heads — the line's own total. */
  line_total_paise: number;
}

/**
 * Split a line's tax across heads — the mirror of `_compute_line_gst`.
 *
 * The FULL tax is floored first and only then halved, so CGST+SGST always
 * equals the IGST the same supply would attract inter-state. Halving the rate
 * first and flooring each leg loses up to a paise (understating the liability)
 * for any odd tax amount. SGST carries the odd paise.
 */
export function splitLineGst(
  taxable: number,
  gstRateBps: number,
  isInterstate: boolean,
): LineGstAmounts {
  const full = Number(floorDiv(BigInt(taxable) * BigInt(gstRateBps), BigInt(10000)));
  if (isInterstate) {
    return {
      taxable_paise: taxable,
      cgst_paise: 0,
      sgst_paise: 0,
      igst_paise: full,
      line_total_paise: taxable + full,
    };
  }
  const cgst = Math.floor(full / 2);
  return {
    taxable_paise: taxable,
    cgst_paise: cgst,
    sgst_paise: full - cgst,
    igst_paise: 0,
    line_total_paise: taxable + full,
  };
}

/**
 * One line, from the raw form strings all the way to stored-shape paise —
 * the whole pipeline the server will repeat on save.
 */
export function computeLineGst(
  line: { qty: string | number; rate: string | number; gst_rate: number },
  isInterstate: boolean,
): LineGstAmounts {
  const taxable = taxablePaise(
    quantityFromInput(line.qty),
    ratePaiseFromRupees(line.rate),
  );
  return splitLineGst(taxable, gstRateBpsFromPercent(line.gst_rate), isInterstate);
}
