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
    const fullGst = Math.floor((taxable * line.gst_rate_bps) / 10000);
    cgst = Math.floor(fullGst / 2);
    sgst = fullGst - cgst;
  }
  return { taxable_paise: taxable, cgst_paise: cgst, sgst_paise: sgst, igst_paise: igst, line_total: taxable + cgst + sgst + igst };
}
