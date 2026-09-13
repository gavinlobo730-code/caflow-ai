/**
 * The two integer primitives every money mirror in this directory needs, in
 * one place.
 *
 * Both exist to reproduce Python EXACTLY rather than approximately, because
 * the browser's job here is to predict what the server will store:
 *
 *   floorDivBigInt   Python's `//`. BigInt `/` truncates toward zero, which
 *                    differs for negative operands. Amounts are non-negative
 *                    in practice; matching the operator keeps this a true
 *                    mirror rather than one that happens to agree.
 *   decimalTruncate  `int(Decimal(str(qty)) * unitPaise)`. Exact decimal
 *                    multiplication and then truncation toward zero — NOT
 *                    `Math.round(qty * unit)`, which is binary floating point
 *                    and rounds. qty 0.335 x Rs.1 is 33 paise on the server
 *                    and was 34 in the preview until this was written.
 *
 * Extracted from `gstLine.ts` unchanged so `cessLine.ts` can share them. Two
 * copies of a truncation rule is how a preview comes to disagree with a saved
 * document by a paise, which is the whole reason
 * `shared/gst-parity-vectors.json` exists.
 */

const B_ZERO = BigInt(0);
const B_ONE = BigInt(1);
const B_TEN = BigInt(10);

/** 10^n as a bigint. Written as a loop rather than `10n ** BigInt(n)` because
 *  the project's tsconfig sets no `target`, so TS defaults to ES5 and rejects
 *  bigint literals and bigint exponentiation. The runtime supports both. */
export function pow10(n: number): bigint {
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
export function decimalParts(value: number): { unscaled: bigint; scale: number } {
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

/** Floor division on BigInt (Python's `//`). */
export function floorDivBigInt(a: bigint, b: bigint): bigint {
  const q = a / b;
  return a % b !== B_ZERO && a < B_ZERO !== b < B_ZERO ? q - B_ONE : q;
}

/**
 * `int(Decimal(str(value)) * unitPaise)` — exact decimal multiplication then
 * truncation toward zero. Used for a line's taxable value (quantity x rate)
 * and for the compensation cess's per-unit limb, which are the same operation
 * on different rates.
 */
export function decimalTruncate(value: number, unitPaise: number): number {
  const { unscaled, scale } = decimalParts(value);
  const product = unscaled * BigInt(Math.trunc(unitPaise));
  // Python's int() truncates toward zero; BigInt division does the same.
  return Number(product / pow10(scale));
}
