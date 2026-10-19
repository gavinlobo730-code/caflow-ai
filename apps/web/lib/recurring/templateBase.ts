/**
 * What a recurring template's lines add up to BEFORE tax: the figure beside each template in the list, in its editor and
 * on the recurring-bills tab (POST-A-134).
 *
 * Each line is valued by the rule the document engine values it by when it raises the invoice or the bill:
 * `int(Decimal(str(quantity)) * rate_paise)`, exact decimal multiplication and then TRUNCATION. That rule is
 * `taxablePaise` (`domain/sales/line_tax` on the server, pinned to this mirror by `shared/gst-parity-vectors.json`).
 * These screens used `Math.round(rate_paise * quantity)`, which is binary floating point and rounds: a quantity of
 * 0.335 at Rs 1 is 33 paise on the server and showed as 34, so the base beside a template could be a few paise away
 * from the invoice it went on to raise. The module is the one place the sum is made, so the three screens cannot
 * disagree with each other either.
 */
import { taxablePaise } from "../money/gstLine.ts";

export interface TemplateLine {
  rate_paise?: number | null;
  quantity?: number | null;
}

/** The sum of the lines' taxable values, in paise. A missing rate or quantity counts as nil. */
export function templateBasePaise(lines: ReadonlyArray<TemplateLine>): number {
  return lines.reduce((sum, l) => sum + taxablePaise(l.quantity || 0, l.rate_paise || 0), 0);
}
