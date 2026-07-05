/**
 * Debit Note line-item GST preview (C3) — extracted from the Purchases page
 * so the math is testable independent of React/Supabase. Mirrors the
 * backend's own `_compute_line_gst` (apps/api/routers/debit_notes.py) —
 * intra-state splits the rate 50/50 CGST+SGST (CGST Act §8), inter-state
 * applies the full rate as IGST — including its floor-division order
 * (halve the bps first, then floor each GST leg) so this client-side
 * preview never drifts from what the server actually posts.
 */

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
  const taxable = Math.round(line.quantity * line.rate * 100); // paise
  let cgst = 0, sgst = 0, igst = 0;
  if (isInterstate) {
    igst = Math.floor((taxable * line.gst_rate_bps) / 10000);
  } else {
    const half = Math.floor(line.gst_rate_bps / 2);
    cgst = Math.floor((taxable * half) / 10000);
    sgst = Math.floor((taxable * half) / 10000);
  }
  return { taxable_paise: taxable, cgst_paise: cgst, sgst_paise: sgst, igst_paise: igst, line_total: taxable + cgst + sgst + igst };
}
