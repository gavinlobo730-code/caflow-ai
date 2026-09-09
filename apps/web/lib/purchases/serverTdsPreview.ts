/**
 * The TDS on a purchase bill, computed by the code that will withhold it.
 *
 * WHY THIS IS NOT A BROWSER CALCULATION
 *     The bill editor used to show `rate x taxable` — the vendor's stored
 *     tds_rate_bps applied to the base value — and subtract it as "Net
 *     payable". The server does none of that. It branches on RESIDENCY first:
 *
 *       * a NON-RESIDENT payee is IT Act s.195. Rate by the NATURE of the
 *         income under Part II of the First Schedule and s.115A, plus
 *         surcharge and 4% cess, displaced by a DTAA under s.90(2) where a TRC
 *         is held — and a REFUSAL, not a guess, where chargeability or the
 *         treaty position is unknown. The resident sections do not reach a
 *         non-resident at all: s.194C and its neighbours charge, in their own
 *         words, sums paid "to a resident".
 *       * a RESIDENT payee is resolve_tds: the section's threshold, the year's
 *         AGGREGATE (most of the s.194 series charges on the whole aggregate
 *         once it is crossed, crediting what earlier bills already withheld
 *         under s.200), and the s.206AA 20% floor where no PAN is on file.
 *
 *     None of those inputs exists in the browser. A sub-threshold s.194J bill
 *     previewed tax and saved zero; a non-resident bill previewed a resident
 *     rate and saved base + surcharge + cess, or was refused outright. The CA
 *     approved one number and the ledger recorded another (TDS-14).
 *
 * WHY IT DEBOUNCES RATHER THAN FIRING PER KEYSTROKE
 *     The preview is a real computation against the client's purchase history
 *     — it reads the year's earlier bills to the same payee. One request per
 *     typed digit would be several round trips to Mumbai per amount. 400ms
 *     after the last edit is the whole of the cleverness here.
 *
 * WHAT IT DOES NOT DO
 *     Guess. When the request is in flight or has failed there is NO number:
 *     the caller renders "…" or the refusal. A stale figure beside a changed
 *     amount is exactly the divergence this replaced.
 */
import { useEffect, useRef, useState } from "react";
import { apiCall, getAuthToken } from "@/lib/invoices/shared";

export interface ServerTdsPreview {
  taxable_amount_paise: number;
  total_paise: number;
  total_gst_paise: number;
  tds_paise: number;
  tds_rate_bps: number;
  tds_section: string | null;
  tds_surcharge_paise: number;
  tds_cess_paise: number;
  tds_nature_of_income: string | null;
  tds_basis: string | null;
  tds_citation: string | null;
  tds_shortfall_paise: number;
  net_payable_paise: number;
  txn_currency: string;
  txn_total: number;
  txn_net_payable: number;
}

export interface TdsPreviewLine {
  description: string;
  hsn_sac?: string;
  quantity: number;
  unit?: string;
  rate_paise: number;
  gst_rate_percent: number;
  expense_account_id?: string;
  service_catalogue_id?: string;
}

export interface TdsPreviewInput {
  clientId: string;
  vendorId: string;
  billDate: string;
  lines: TdsPreviewLine[];
  isReverseCharge: boolean;
  currency?: string;
  exchangeRate?: string;
  /** On an EDIT the bill already exists carrying its own taxable amount, so it
   *  must not count itself in its own FY-prior aggregate. */
  excludeBillId?: string;
  enabled: boolean;
}

export interface TdsPreviewState {
  data: ServerTdsPreview | null;
  loading: boolean;
  error: string | null;
}

const DEBOUNCE_MS = 400;

export function useServerTdsPreview(input: TdsPreviewInput): TdsPreviewState {
  const [state, setState] = useState<TdsPreviewState>({ data: null, loading: false, error: null });
  // The request the answer must belong to. Without it a slow early request can
  // land after a fast later one and overwrite a correct figure with a stale
  // one — on a screen whose whole purpose is that the number shown is the
  // number that will be saved.
  const seq = useRef(0);

  const { clientId, vendorId, billDate, isReverseCharge, currency,
          exchangeRate, excludeBillId, enabled } = input;
  // THE SERIALISED LINES ARE THE DEPENDENCY, and the effect reads the lines
  // back out of it rather than closing over the array. The caller rebuilds the
  // array on every render, so depending on it directly would fire the effect
  // for ever; depending on the string while closing over the array is the
  // version that goes stale. Parsing it back is the only form that is both
  // correct and honest about what changed.
  const linesKey = JSON.stringify(input.lines);

  useEffect(() => {
    const lines: TdsPreviewLine[] = JSON.parse(linesKey);
    const ready = enabled && !!clientId && !!vendorId && !!billDate && lines.length > 0;
    if (!ready) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const mine = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    const timer = setTimeout(async () => {
      try {
        const token = await getAuthToken();
        const qs = excludeBillId ? `?exclude_bill_id=${encodeURIComponent(excludeBillId)}` : "";
        const res = await apiCall(
          `/api/purchase-bills/tds-preview${qs}`,
          "POST",
          {
            client_id: clientId,
            vendor_id: vendorId,
            bill_date: billDate,
            is_reverse_charge: isReverseCharge,
            lines,
            currency: currency || undefined,
            exchange_rate: exchangeRate || undefined,
          },
          token,
        );
        if (mine !== seq.current) return;
        if (!res.success) {
          setState({ data: null, loading: false,
                     error: res.error ?? "The TDS on this bill could not be computed." });
          return;
        }
        setState({ data: res.data as ServerTdsPreview, loading: false, error: null });
      } catch (e) {
        if (mine !== seq.current) return;
        // A REFUSAL IS THE USEFUL ANSWER, not a failure to hide. s.195 refuses
        // where chargeability or the treaty position is unknown, and the save
        // will refuse identically — better here, while the CA can still act.
        setState({ data: null, loading: false,
                   error: e instanceof Error ? e.message : "The TDS on this bill could not be computed." });
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [clientId, vendorId, billDate, linesKey, isReverseCharge, currency,
      exchangeRate, excludeBillId, enabled]);

  return state;
}
