/**
 * Debit Note line-item GST preview (C3) — extracted from the Purchases page
 * so the math is testable independent of React/Supabase. Mirrors the
 * backend's own `_compute_line_gst` (apps/api/routers/debit_notes.py) —
 * intra-state splits CGST+SGST (CGST Act §8), inter-state applies the full
 * rate as IGST — including its floor-division order: full tax computed
 * first, THEN split (SGST carries any odd paise). The earlier version here
 * halved the bps first and floored each leg independently, which for
 * certain taxable/rate combinations understates the total GST by 1 paise
 * versus what the backend actually posts (same class of bug already fixed
 * on the sales-invoice side) — e.g. 28 paise taxable @ 18%: correct total
 * is 5 paise (2 CGST + 3 SGST), the old method computed 4 (2 + 2).
 */

import { computeLineGst } from "../money/gstLine.ts";

export interface DebitNoteLineInput {
  quantity: number;
  rate: number; // rupees
  gst_rate_bps: number;
}

export interface DebitNoteLineGst {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  line_total: number;
}

export function dnLineGst(line: DebitNoteLineInput, isInterstate: boolean): DebitNoteLineGst {
  // Delegates to the one canonical mirror of the backend's per-line math so
  // purchase notes cannot drift from sales invoices, or from the server. The
  // taxable base in particular is exact-decimal + truncated here, where this
  // used to do Math.round(qty * rate * 100) in binary floating point.
  const g = computeLineGst(
    { qty: line.quantity, rate: line.rate, gst_rate: line.gst_rate_bps / 100 },
    isInterstate,
  );
  return {
    taxable_paise: g.taxable_paise,
    cgst_paise: g.cgst_paise,
    sgst_paise: g.sgst_paise,
    igst_paise: g.igst_paise,
    line_total: g.line_total_paise,
  };
}
