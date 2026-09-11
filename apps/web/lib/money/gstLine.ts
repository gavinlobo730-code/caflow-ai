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

/**
 * A discount recorded in the invoice — CGST Act §15(3)(a).
 *
 * Mirrors `apps/api/domain/gst/discount.py` operation for operation, and is
 * pinned to it by shared/gst-parity-vectors.json. Integer arithmetic in BigInt,
 * because integer floor division is the one operation Python and JavaScript do
 * identically with no precision setting to agree on.
 *
 * §15(3): "The value of the supply shall not include any discount which is
 * given — (a) before or at the time of the supply if such discount has been
 * duly recorded in the invoice". So the tax is charged on the NET, and the
 * relief is conditional on the invoice showing the discount.
 *
 * §15(3)(b) — a discount given AFTER the supply — is the §34 credit-note path
 * and is deliberately not reachable from here.
 *
 * Every rounding goes DOWN: a larger discount is a smaller taxable value and
 * less tax, so flooring can only leave the taxable value a paise higher, which
 * is the direction that cannot under-declare.
 *
 * Returns null when the discount exceeds the line — the value of a supply
 * cannot be negative, and the server refuses it with a 422. The preview must
 * refuse it too rather than showing a figure that will not save.
 */
export function discountPaise(
  grossPaise: number,
  percentBps?: number | null,
  amountPaise?: number | null,
): number | null {
  if (!Number.isFinite(grossPaise) || grossPaise < 0) return null;
  let out: number;
  if (percentBps !== null && percentBps !== undefined) {
    if (!Number.isFinite(percentBps) || percentBps < 0 || percentBps > 10000) return null;
    out = Number(
      floorDiv(BigInt(Math.trunc(grossPaise)) * BigInt(Math.trunc(percentBps)), BigInt(10000)),
    );
  } else if (amountPaise !== null && amountPaise !== undefined) {
    if (!Number.isFinite(amountPaise)) return null;
    out = Math.trunc(amountPaise);
  } else {
    return 0;
  }
  if (out < 0 || out > grossPaise) return null;
  return out;
}

/**
 * Split a document-level discount across lines pro-rata by `weights` (each
 * line's value after its own discount), summing to EXACTLY `totalPaise`.
 *
 * Largest remainder, ties broken by position — the mirror of
 * `discount.allocate`. A pro-rata split that loses a paise makes the invoice
 * total differ from the figure the customer was quoted.
 *
 * Returns null where the server would refuse: a discount larger than the bill.
 */
export function allocateDiscount(totalPaise: number, weights: number[]): number[] | null {
  if (totalPaise < 0) return null;
  const n = weights.length;
  if (n === 0 || totalPaise === 0) return new Array(n).fill(0);

  const base = weights.reduce((a, b) => a + b, 0);
  if (base <= 0) return new Array(n).fill(0);
  if (totalPaise > base) return null;

  const bBase = BigInt(base);
  const bTotal = BigInt(Math.trunc(totalPaise));
  const out: number[] = [];
  const remainder: bigint[] = [];
  for (let i = 0; i < n; i++) {
    const num = bTotal * BigInt(Math.trunc(weights[i]));
    const q = floorDiv(num, bBase);
    out.push(Number(q));
    remainder.push(num - q * bBase);
  }

  // Each floor loses less than one whole paise, so the residue is strictly less
  // than the number of lines and every line gets at most one.
  const residue = totalPaise - out.reduce((a, b) => a + b, 0);
  const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => {
    if (remainder[a] > remainder[b]) return -1;
    if (remainder[a] < remainder[b]) return 1;
    return a - b;
  });
  for (let k = 0; k < residue; k++) out[order[k]] += 1;
  return out;
}

export interface LineDiscount {
  discount_paise: number;
  taxable_paise: number;
}

/**
 * Resolve every discount on one invoice — the mirror of
 * `discount.apply_to_lines`.
 *
 * LINE FIRST, THEN DOCUMENT. The document discount is a percentage OF THE BILL,
 * and the bill is what is left after the line discounts; taking both off the
 * gross would compound two reliefs the customer was quoted as one.
 *
 * Returns null if any part of it would be refused by the server.
 */
export function applyDiscountsToLines(
  lines: { gross_paise: number; discount_percent_bps?: number | null; discount_paise?: number | null }[],
  documentPercentBps?: number | null,
  documentAmountPaise?: number | null,
): LineDiscount[] | null {
  const lineDiscounts: number[] = [];
  const nets: number[] = [];
  for (const ln of lines) {
    const d = discountPaise(ln.gross_paise, ln.discount_percent_bps, ln.discount_paise);
    if (d === null) return null;
    lineDiscounts.push(d);
    nets.push(ln.gross_paise - d);
  }

  const billNet = nets.reduce((a, b) => a + b, 0);
  const docTotal = discountPaise(billNet, documentPercentBps, documentAmountPaise);
  if (docTotal === null) return null;
  const shares = allocateDiscount(docTotal, nets);
  if (shares === null) return null;

  return lines.map((_, i) => ({
    discount_paise: lineDiscounts[i] + shares[i],
    taxable_paise: nets[i] - shares[i],
  }));
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
