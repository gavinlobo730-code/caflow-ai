/**
 * The rows the drive's stub answers with, and the identity it signs in as.
 *
 * THE FOUR IDENTITY OBJECTS ARE THE WALK'S, VALUE FOR VALUE. `FAKE_USER`, `FAKE_SESSION`, `FAKE_USERS_ROW` and
 * `FAKE_FIRM_ROW` are what `smoke-walk.mjs` signs in as, and the reason they exist is written beside them there:
 * without a `users` row carrying a firm, AuthGuard bounces every protected route to the onboarding wizard, and
 * without a `firms.name` the dashboard does the same. The walk keeps them private (it runs on import, so nothing
 * can import it), which is why they are repeated here — and why
 * `the-money-editors-are-driven-in-a-browser.test.ts` reads both files and fails when one of the four drifts,
 * so the drive cannot end up signed in as somebody the walk would have refused.
 *
 * Everything below those four is the DRIVE'S OWN: one client, a chart of accounts, a customer and a vendor, a
 * catalogue item, and the invoices and bills the document drawers open. It is deliberately small. A stub that
 * grew a hundred rows would start to be a second product, and the point of the drive is what a CLICK does, not
 * what a list holds.
 *
 * Amounts are integer paise, as everywhere; a figure here is a fixture and not a rate anybody should copy.
 */

export const FAKE_USER = {
  id: "00000000-0000-4000-8000-000000000001",
  aud: "authenticated", role: "authenticated",
  email: "smoke@example.invalid", app_metadata: {}, user_metadata: {},
  created_at: "2026-01-01T00:00:00Z",
};

export const FAKE_SESSION = {
  access_token: "smoke.walk.token", token_type: "bearer", expires_in: 3600,
  expires_at: 4102444800, refresh_token: "smoke.refresh", user: FAKE_USER,
};

export const FAKE_USERS_ROW = {
  id: "00000000-0000-4000-8000-000000000002",
  auth_user_id: FAKE_USER.id,
  role: "Partner",
  firm_id: "00000000-0000-4000-8000-0000000000f1",
  full_name: "Smoke Walker",
};

export const FAKE_FIRM_ROW = {
  id: FAKE_USERS_ROW.firm_id,
  name: "Smoke & Co., Chartered Accountants",
};

/** A client workspace needs a `clients` row or ClientResolutionGate renders "no such client". */
export const CLIENT_ID = "00000000-0000-4000-8000-0000000000c1";

/** The instant every scenario runs at: 08:00 UTC on 8 October 2026. It is chosen so that "today" is the SAME
 *  calendar day, 8 October, in Los Angeles (01:00), Kolkata (13:30) and Kiritimati (22:00): the three zones the
 *  date scenarios run under, so a difference between them is a defect in the field and never a day the clock
 *  fell on. Inside FY 2026-27, mid-year, so a short date such as 15/1 has an unambiguous year (2027). */
export const NOW = "2026-10-08T08:00:00Z";

export const CLIENT_ROW = {
  id: CLIENT_ID, client_name: "Acme Traders Pvt Ltd", legal_name: "Acme Traders Pvt Ltd",
  entity_type: "Private Limited", gstin: null, pan: null, status: "active", state_code: "27",
  is_internal: false,
};

export const ACCOUNTS = [
  { id: "a1", account_code: "1001", account_name: "Cash in Hand", account_type: "Asset", is_active: true, client_id: null },
  { id: "a2", account_code: "4001", account_name: "Sales", account_type: "Revenue", is_active: true, client_id: null },
  { id: "a5", account_code: "5001", account_name: "Purchases", account_type: "Expense", is_active: true, client_id: null },
];

export const CUSTOMER = {
  id: "cu1", name: "Beta Stores", gstin: null, state_code: "27", pan: null, email: "b@example.invalid",
  phone: null, city: null, state: null, opening_balance_paise: 0, credit_days: 30, is_active: true,
};

export const VENDOR = {
  id: "v1", name: "Gamma Supplies", gstin: null, pan: null, email: null, phone: null, state_code: "27",
  tds_applicable: false, tds_section: null, tds_rate_bps: null, is_active: true,
};

export const ITEM = {
  id: "sc1", client_id: CLIENT_ID, name: "Consulting", description: "Consulting hours", hsn_sac: "998313",
  unit: "HRS", gst_rate_bps: 1800, default_rate_paise: 500000, purchase_price_paise: 400000,
  is_active: true, item_type: "service",
};

/** Journal rows for the list: three posted manual entries, so the list has rows to Tab to. */
export const JOURNAL_ENTRIES = [1, 2, 3].map((n) => ({
  id: `e${n}`, entry_date: `2026-10-0${n}`, reference_no: `JNL-00${n}`, narration: `Entry ${n}`,
  entry_type: "Journal", is_posted: true, source_type: "manual",
  lines: [
    { account_id: "a1", debit_paise: 100000 * n, credit_paise: 0 },
    { account_id: "a2", debit_paise: 0, credit_paise: 100000 * n },
  ],
}));

/** One sales invoice row (what the list reads) in the given status. */
export function invoiceRow(status = "issued", id = "inv-9") {
  const issued = status !== "draft";
  return {
    id, invoice_no: "INV-0009", invoice_date: "2026-10-01", due_date: "2026-10-31", customer_id: CUSTOMER.id,
    taxable_amount_paise: 1000000, total_gst_paise: 180000, total_paise: 1180000, paid_paise: 0,
    outstanding_paise: 1180000, status, supply_state_code: "27", is_interstate: false, is_overdue: false,
    days_overdue: 0, reminder_count: 0, last_reminded_at: null, customers: { name: CUSTOMER.name },
    client_id: CLIENT_ID, journal_entry_id: issued ? "j1" : null,
  };
}

/** The same invoice as the drawer's detail read returns it. */
export function invoiceDetail(status = "issued", id = "inv-9") {
  return {
    ...invoiceRow(status, id), notes: null, cgst_paise: 90000, sgst_paise: 90000, igst_paise: 0,
    issued_at: status === "draft" ? null : "2026-10-01T00:00:00Z", created_by_name: "Smoke Walker",
    customers: { id: CUSTOMER.id, name: CUSTOMER.name, email: CUSTOMER.email, gstin: null, phone: null },
    lines: [{
      id: "l1", description: "Consulting", hsn_sac: "998313", quantity: 1, unit: "HRS", rate_paise: 1000000,
      gst_rate_bps: 1800, taxable_amount_paise: 1000000, cgst_paise: 90000, sgst_paise: 90000, igst_paise: 0,
      line_total_paise: 1180000, service_catalogue_id: ITEM.id,
    }],
  };
}

/** One purchase bill, as the list and the drawer's detail read both return it. */
export function billRow(status = "draft", id = "b9") {
  return {
    id, bill_no: "GS/114", our_reference: null, vendor_id: VENDOR.id, bill_date: "2026-10-02",
    due_date: "2026-11-01", status, is_interstate: false, taxable_amount_paise: 1000000,
    total_gst_paise: 180000, total_paise: 1180000, tds_paise: 0, net_payable_paise: 1180000,
    paid_paise: 0, outstanding_paise: 1180000, vendors: { name: VENDOR.name }, client_id: CLIENT_ID,
    journal_entry_id: status === "draft" ? null : "j2",
    lines: [{
      id: "bl1", description: "Paper", hsn_sac: "4802", quantity: 1, unit: "NOS", rate_paise: 1000000,
      gst_rate_bps: 1800, taxable_amount_paise: 1000000, cgst_paise: 90000, sgst_paise: 90000, igst_paise: 0,
      line_total_paise: 1180000, service_catalogue_id: ITEM.id, itc_eligible: true,
    }],
  };
}

/** A payroll run the Release tab lists as finalised, so it offers Reverse. */
export const PAYROLL_RUN = {
  id: "run1", month: "2026-09", status: "finalized", headcount: 3, total_gross_paise: 9000000,
  total_net_paise: 8000000, total_pf_paise: 0, total_esi_paise: 0, total_tds_paise: 0,
  finalized_at: "2026-10-03T00:00:00Z",
};
