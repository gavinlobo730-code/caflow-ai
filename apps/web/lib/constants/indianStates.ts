/**
 * Canonical GST state codes (2-digit) → state name. Per the GST state-code list
 * used in GSTIN (first two digits). Shared so pickers don't each redefine it.
 *
 * THE ONE LIST. There were four. lib/invoices/gst.ts carried a second array of
 * thirty entries that InvoiceEditor and CustomerFormModal passed EXPLICITLY to
 * StateLookup, overriding this one — so the place of supply and the customer's
 * state could not be set to Goa (30), Dadra & Nagar Haveli and Daman & Diu
 * (26), Puducherry (34) or Ladakh (38) at all, and settings/ and onboarding/
 * carried two more, name-only, for a firm's own address. A picker that cannot
 * name a state makes every invoice to it wrong: the place of supply decides
 * CGST+SGST against IGST (IGST Act s.7/s.8), and it is a Rule 46(n) particular.
 *
 * WHAT IS DELIBERATELY NOT HERE
 *   25 (Daman & Diu) and 28 (Andhra Pradesh, pre-2014) are DEAD codes — 25
 *   merged into 26 on 26-01-2020 and 28 was replaced by 37. The backend still
 *   accepts them (domain/gst/validator.py) so a historical document parses;
 *   offering them for a NEW document would let a CA pick a code the portal
 *   rejects.
 *
 *   96 (Other Country) and 97 (Other Territory) are not STATES, so INDIAN_STATES
 *   leaves them out; where a document's PLACE OF SUPPLY (or an export customer's
 *   state) is chosen, `PLACE_OF_SUPPLY_STATES` below adds them (POST-A-103). 96 is
 *   the place of supply GSTN requires on an EXPORT. The server accepts both on
 *   exactly those fields (`domain/gst/validator.VALID_STATE_CODES`, which
 *   `models/parties` also asks of a customer's state), and refuses them in a
 *   GSTIN, so a GSTIN-shaped picker must not offer them.
 */
export interface IndianState {
  code: string;
  name: string;
}

export const INDIAN_STATES: IndianState[] = [
  { code: "01", name: "Jammu & Kashmir" },
  { code: "02", name: "Himachal Pradesh" },
  { code: "03", name: "Punjab" },
  { code: "04", name: "Chandigarh" },
  { code: "05", name: "Uttarakhand" },
  { code: "06", name: "Haryana" },
  { code: "07", name: "Delhi" },
  { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" },
  { code: "10", name: "Bihar" },
  { code: "11", name: "Sikkim" },
  { code: "12", name: "Arunachal Pradesh" },
  { code: "13", name: "Nagaland" },
  { code: "14", name: "Manipur" },
  { code: "15", name: "Mizoram" },
  { code: "16", name: "Tripura" },
  { code: "17", name: "Meghalaya" },
  { code: "18", name: "Assam" },
  { code: "19", name: "West Bengal" },
  { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" },
  { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" },
  { code: "24", name: "Gujarat" },
  { code: "26", name: "Dadra & Nagar Haveli and Daman & Diu" },
  { code: "27", name: "Maharashtra" },
  { code: "29", name: "Karnataka" },
  { code: "30", name: "Goa" },
  { code: "31", name: "Lakshadweep" },
  { code: "32", name: "Kerala" },
  { code: "33", name: "Tamil Nadu" },
  { code: "34", name: "Puducherry" },
  { code: "35", name: "Andaman & Nicobar Islands" },
  { code: "36", name: "Telangana" },
  { code: "37", name: "Andhra Pradesh" },
  { code: "38", name: "Ladakh" },
];

/**
 * What a document's place of supply, a receipt or advance's place of supply and a customer's state may be: every state
 * and union territory, plus 96 (Other Country, the place of supply on an export) and 97 (Other Territory). Derived from
 * INDIAN_STATES so the two cannot drift; the dead codes 25 and 28 stay out of both.
 * `apps/api/tests/test_the_state_pickers_offer_what_the_server_accepts.py` holds this list to the server's.
 */
export const PLACE_OF_SUPPLY_STATES: IndianState[] = [
  ...INDIAN_STATES,
  { code: "96", name: "Other Country (outside India — exports)" },
  { code: "97", name: "Other Territory" },
];
