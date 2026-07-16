/**
 * Party credit balances API client (task #102) — a customer/vendor's
 * non-GST cash credit (e.g. from a bank overpayment) and applying it to a
 * specific invoice/bill. Calls go through the shared request() helper in
 * lib/api/index.ts (cold-start timeout + one automatic retry).
 */

import { request } from "./index";

// ── Types ─────────────────────────────────────────────────────────────────

export type PartyType = "customer" | "vendor";
export type AppliedToType = "sales_invoice" | "purchase_bill";

export interface PartyCreditBalance {
  id: string;
  firm_id: string;
  client_id: string;
  party_type: PartyType;
  party_id: string;
  balance_paise: number;
  updated_at: string;
}

export interface PartyCreditLedgerEntry {
  id: string;
  party_type: PartyType;
  party_id: string;
  amount_paise: number; // +ve = grant, -ve = application
  kind: "grant" | "application";
  source_type: string | null;
  source_id: string | null;
  applied_to_type: AppliedToType | null;
  applied_to_id: string | null;
  notes: string | null;
  created_at: string;
}

export interface PartyCreditDetail {
  balance_paise: number;
  ledger: PartyCreditLedgerEntry[];
}

interface ApiResp<T> {
  success: boolean;
  data: T;
  error: string | null;
}

export const partyCreditsApi = {
  list: (clientId: string, partyType?: PartyType) => {
    const qs = new URLSearchParams({ client_id: clientId });
    if (partyType) qs.set("party_type", partyType);
    return request<ApiResp<PartyCreditBalance[]>>(`/api/party-credits?${qs.toString()}`);
  },

  get: (partyType: PartyType, partyId: string, clientId: string) =>
    request<ApiResp<PartyCreditDetail>>(
      `/api/party-credits/${partyType}/${partyId}?client_id=${encodeURIComponent(clientId)}`
    ),

  apply: (body: {
    client_id: string;
    party_type: PartyType;
    party_id: string;
    amount_paise: number;
    applied_to_type: AppliedToType;
    applied_to_id: string;
  }) =>
    request<ApiResp<PartyCreditLedgerEntry>>(`/api/party-credits/apply`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
