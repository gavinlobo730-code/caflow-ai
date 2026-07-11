/**
 * CSV/XLSX bulk-import mappers for the client workspace.
 *
 * One self-contained module per the project's import pattern: every mapper is a
 * PURE function (flat parsed rows → typed API payloads + per-row errors) that maps
 * onto the EXISTING create endpoints — no parallel write logic. Money is always
 * integer paise (rupees × 100) and tax rates are basis points (percent × 100), to
 * match the backend; never floating point.
 *
 * Covers: Customers, Vendors, Purchase Bills, Receipts, Payroll Employees.
 * (Sales invoices have their own mapper at lib/invoices/importMapping.ts.)
 */

// ── Shared helpers ───────────────────────────────────────────────────────────

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
/** GSTIN: 2-digit state + PAN(10) + entity# + Z + check (CGST Act §25). */
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
/** PAN: AAAAA9999A (IT Act §139A). */
const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/;

export interface ImportColumn { key: string; label: string; required: boolean; hint?: string; }

function str(v: string | undefined): string { return (v ?? "").trim(); }
function num(v: string | undefined): number { return parseFloat(str(v)); }
/** Rupees string → integer paise (never float). */
function toPaise(rupees: string | undefined): number { return Math.round(num(rupees) * 100); }
/** Percent string → basis points (e.g. "18" → 1800). */
function toBps(percent: string | undefined): number { return Math.round(num(percent) * 100); }
/** Permissive boolean parse for spreadsheet cells: yes/true/1/y → true. */
function toBool(v: string | undefined, fallback = false): boolean {
  const s = str(v).toLowerCase();
  if (!s) return fallback;
  return ["yes", "y", "true", "1", "t"].includes(s);
}

export interface NameRef { id: string; name: string; }

// ── Customers → POST /api/customers/ ─────────────────────────────────────────

export interface BuiltCustomer {
  client_id: string;
  name: string;
  gstin?: string;
  state_code?: string;
  pan?: string;
  email?: string;
  phone?: string;
  city?: string;
  state?: string;
  opening_balance_paise: number;
  credit_days: number;
}

export const CUSTOMER_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "name", label: "Name", required: true, hint: "Customer / party name" },
  { key: "gstin", label: "GSTIN", required: false, hint: "15-char GSTIN, e.g. 27AABCU9603R1ZX (optional)" },
  { key: "state_code", label: "State Code", required: false, hint: "2-digit GST state code (auto-derived from GSTIN if blank)" },
  { key: "pan", label: "PAN", required: false, hint: "10-char PAN, e.g. AABCU9603R (optional)" },
  { key: "email", label: "Email", required: false, hint: "Billing email (optional)" },
  { key: "phone", label: "Phone", required: false, hint: "Contact phone (optional)" },
  { key: "city", label: "City", required: false, hint: "City (optional)" },
  { key: "state", label: "State", required: false, hint: "State name (optional)" },
  { key: "opening_balance", label: "Opening Balance (₹)", required: false, hint: "Opening receivable in rupees, e.g. 0" },
  { key: "credit_days", label: "Credit Days", required: false, hint: "Defaults to 30 if blank" },
];

export function buildCustomers(rows: Record<string, string>[], clientId: string): { records: BuiltCustomer[]; errors: string[] } {
  const records: BuiltCustomer[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const name = str(r.name);
    if (!name) { errors.push(`Row ${rowNo}: name is required`); return; }
    if (seen.has(name.toLowerCase())) { errors.push(`Row ${rowNo}: duplicate name "${name}" in this file`); return; }

    const gstin = str(r.gstin).toUpperCase() || undefined;
    if (gstin && !GSTIN_RE.test(gstin)) { errors.push(`Row ${rowNo}: invalid GSTIN "${gstin}"`); return; }
    const pan = str(r.pan).toUpperCase() || undefined;
    if (pan && !PAN_RE.test(pan)) { errors.push(`Row ${rowNo}: invalid PAN "${pan}"`); return; }

    const stateCode = str(r.state_code) || (gstin ? gstin.slice(0, 2) : undefined);
    const creditDaysRaw = str(r.credit_days);
    const creditDays = creditDaysRaw ? parseInt(creditDaysRaw, 10) : 30;
    if (creditDaysRaw && (!Number.isFinite(creditDays) || creditDays < 0)) {
      errors.push(`Row ${rowNo}: credit_days must be a non-negative whole number`); return;
    }

    seen.add(name.toLowerCase());
    records.push({
      client_id: clientId,
      name,
      gstin,
      state_code: stateCode || undefined,
      pan,
      email: str(r.email) || undefined,
      phone: str(r.phone) || undefined,
      city: str(r.city) || undefined,
      state: str(r.state) || undefined,
      opening_balance_paise: toPaise(r.opening_balance),
      credit_days: creditDays,
    });
  });

  return { records, errors };
}

// ── Vendors → POST /api/vendors/ ─────────────────────────────────────────────

const TDS_SECTIONS = ["194C", "194I", "194J", "194H", "194A"];

export interface BuiltVendor {
  client_id: string;
  name: string;
  gstin?: string;
  state_code?: string;
  pan?: string;
  email?: string;
  phone?: string;
  tds_applicable: boolean;
  tds_section?: string;
  tds_rate_bps: number;
  opening_balance_paise: number;
}

export const VENDOR_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "name", label: "Name", required: true, hint: "Vendor / supplier name" },
  { key: "gstin", label: "GSTIN", required: false, hint: "15-char GSTIN (optional)" },
  { key: "pan", label: "PAN", required: false, hint: "10-char PAN (optional)" },
  { key: "email", label: "Email", required: false, hint: "Contact email (optional)" },
  { key: "phone", label: "Phone", required: false, hint: "Contact phone (optional)" },
  { key: "tds_applicable", label: "TDS Applicable", required: false, hint: "yes / no" },
  { key: "tds_section", label: "TDS Section", required: false, hint: "194C / 194I / 194J / 194H / 194A (if TDS applicable)" },
  { key: "tds_rate", label: "TDS Rate %", required: false, hint: "e.g. 2 (for 2%); required if TDS applicable" },
  { key: "opening_balance", label: "Opening Balance (₹)", required: false, hint: "Opening payable in rupees, e.g. 0" },
];

export function buildVendors(rows: Record<string, string>[], clientId: string): { records: BuiltVendor[]; errors: string[] } {
  const records: BuiltVendor[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const name = str(r.name);
    if (!name) { errors.push(`Row ${rowNo}: name is required`); return; }
    if (seen.has(name.toLowerCase())) { errors.push(`Row ${rowNo}: duplicate name "${name}" in this file`); return; }

    const gstin = str(r.gstin).toUpperCase() || undefined;
    if (gstin && !GSTIN_RE.test(gstin)) { errors.push(`Row ${rowNo}: invalid GSTIN "${gstin}"`); return; }
    const pan = str(r.pan).toUpperCase() || undefined;
    if (pan && !PAN_RE.test(pan)) { errors.push(`Row ${rowNo}: invalid PAN "${pan}"`); return; }

    const tdsApplicable = toBool(r.tds_applicable);
    let tdsSection: string | undefined;
    let tdsRateBps = 0;
    if (tdsApplicable) {
      tdsSection = str(r.tds_section).toUpperCase();
      if (!TDS_SECTIONS.includes(tdsSection)) {
        errors.push(`Row ${rowNo}: tds_section must be one of ${TDS_SECTIONS.join(", ")} when TDS applies`); return;
      }
      tdsRateBps = toBps(r.tds_rate);
      if (!Number.isFinite(tdsRateBps) || tdsRateBps <= 0) {
        errors.push(`Row ${rowNo}: tds_rate % must be a positive number when TDS applies`); return;
      }
    }

    seen.add(name.toLowerCase());
    records.push({
      client_id: clientId,
      name,
      gstin,
      state_code: gstin ? gstin.slice(0, 2) : undefined,
      pan,
      email: str(r.email) || undefined,
      phone: str(r.phone) || undefined,
      tds_applicable: tdsApplicable,
      tds_section: tdsSection,
      tds_rate_bps: tdsRateBps,
      opening_balance_paise: toPaise(r.opening_balance),
    });
  });

  return { records, errors };
}

// ── Products & Services → POST /api/service-catalogue/ ──────────────────────

export interface BuiltService {
  client_id: string;
  name: string;
  description?: string;
  kind: "good" | "service";
  category?: string;
  hsn_sac?: string;
  gst_rate_bps?: number;
  default_rate_paise: number;
  purchase_price_paise?: number;
  notes?: string;
  unit?: string;
  opening_qty_units?: number;
  opening_cost_paise?: number;
}

export const SERVICE_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "name", label: "Name", required: true, hint: "Product / service name" },
  { key: "description", label: "Description", required: false, hint: "Line description shown on the invoice (optional)" },
  { key: "kind", label: "Kind", required: false, hint: "product / service (defaults to service)" },
  { key: "category", label: "Category", required: false, hint: "e.g. Compliance (optional)" },
  { key: "hsn_sac", label: "HSN/SAC", required: false, hint: "Must already be in the firm's HSN/SAC library (optional)" },
  { key: "gst_rate", label: "GST %", required: false, hint: "e.g. 18 (defaults to 18%)" },
  { key: "selling_price", label: "Selling Price (₹)", required: false, hint: "Default selling price in rupees (optional)" },
  { key: "purchase_price", label: "Purchase Price (₹)", required: false, hint: "Default purchase price in rupees (optional)" },
  { key: "unit", label: "Unit", required: false, hint: "GST Unit Quantity Code, e.g. KGS, NOS, LTR — Product rows only (optional)" },
  { key: "opening_qty", label: "Opening Qty", required: false, hint: "Opening stock quantity — Product rows only (optional)" },
  { key: "opening_cost", label: "Opening Stock Value (₹)", required: false, hint: "Total cost of the opening quantity, not per-unit — Product rows only (optional)" },
  { key: "notes", label: "Notes", required: false, hint: "Internal note (optional)" },
];

export function buildServices(rows: Record<string, string>[], clientId: string): { records: BuiltService[]; errors: string[] } {
  const records: BuiltService[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const name = str(r.name);
    if (!name) { errors.push(`Row ${rowNo}: name is required`); return; }
    const nameKey = name.toLowerCase().replace(/\s+/g, " ");
    if (seen.has(nameKey)) { errors.push(`Row ${rowNo}: duplicate name "${name}" in this file`); return; }

    // "good" is the internal/API value (matches hsn_type and the backend
    // model); "product" is accepted as an alias since that's the label the
    // app itself now shows everywhere ("New Product/Service", the Kind
    // dropdown) — a CA typing what they see in the app must not be rejected.
    const kindRaw = str(r.kind).toLowerCase();
    const isGood = kindRaw === "good" || kindRaw === "product";
    const kind: "good" | "service" = isGood ? "good" : "service";
    if (kindRaw && !isGood && kindRaw !== "service") {
      errors.push(`Row ${rowNo}: kind must be "product" or "service"`); return;
    }

    const gstRaw = str(r.gst_rate);
    const gstRateBps = gstRaw ? toBps(r.gst_rate) : 1800;
    if (gstRaw && (!Number.isFinite(gstRateBps) || gstRateBps < 0 || gstRateBps > 10000)) {
      errors.push(`Row ${rowNo}: GST % must be between 0 and 100`); return;
    }

    const sellingRaw = str(r.selling_price);
    const sellingPaise = sellingRaw ? toPaise(r.selling_price) : 0;
    if (sellingRaw && (!Number.isFinite(sellingPaise) || sellingPaise < 0)) {
      errors.push(`Row ${rowNo}: selling price must be a non-negative number`); return;
    }
    const purchaseRaw = str(r.purchase_price);
    const purchasePaise = purchaseRaw ? toPaise(r.purchase_price) : undefined;
    if (purchaseRaw && (purchasePaise === undefined || !Number.isFinite(purchasePaise) || purchasePaise < 0)) {
      errors.push(`Row ${rowNo}: purchase price must be a non-negative number`); return;
    }

    // Unit + opening stock — goods only. A service row can't carry either
    // (CGST Rule 46(h): UQC applies to goods, not services); silently
    // dropping them for a service row (rather than erroring) matches how
    // the manual form only shows these fields for kind=good.
    const unit = isGood ? (str(r.unit).toUpperCase() || undefined) : undefined;
    let openingQty: number | undefined;
    let openingCostPaise: number | undefined;
    if (isGood) {
      const openingQtyRaw = str(r.opening_qty);
      if (openingQtyRaw) {
        openingQty = num(r.opening_qty);
        if (!Number.isFinite(openingQty) || openingQty < 0) {
          errors.push(`Row ${rowNo}: opening qty must be a non-negative number`); return;
        }
        if (openingQty === 0) openingQty = undefined;
      }
      const openingCostRaw = str(r.opening_cost);
      if (openingCostRaw) {
        openingCostPaise = toPaise(r.opening_cost);
        if (!Number.isFinite(openingCostPaise) || openingCostPaise < 0) {
          errors.push(`Row ${rowNo}: opening stock value must be a non-negative number`); return;
        }
      }
    }

    seen.add(nameKey);
    records.push({
      client_id: clientId,
      name,
      description: str(r.description) || undefined,
      kind,
      category: str(r.category) || undefined,
      hsn_sac: str(r.hsn_sac) || undefined,
      gst_rate_bps: gstRateBps,
      default_rate_paise: sellingPaise,
      purchase_price_paise: purchasePaise,
      notes: str(r.notes) || undefined,
      unit,
      opening_qty_units: openingQty,
      opening_cost_paise: openingCostPaise,
    });
  });

  return { records, errors };
}

// ── Purchase bills → POST /api/purchase-bills/ ──────────────────────────────

export interface BuiltBillLine {
  description: string;
  hsn_sac?: string;
  quantity: number;
  rate_paise: number;
  // PurchaseBillLineIn (apps/api/models/invoices.py) declares gst_rate_percent,
  // not gst_rate_bps — the latter used to be silently dropped by Pydantic,
  // defaulting every imported line to 18% GST (Beta-readiness Part 4).
  gst_rate_percent: number;
}

export interface BuiltBill {
  client_id: string;
  vendor_id: string;
  bill_date: string;
  due_date?: string;
  bill_no?: string;
  lines: BuiltBillLine[];
  ref: string;
}

export const PURCHASE_BILL_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "vendor", label: "Vendor", required: true, hint: "Existing vendor name (must already exist for this client)" },
  { key: "bill_no", label: "Bill No", required: false, hint: "Vendor's bill number (also groups multiple line rows into one bill)" },
  { key: "bill_date", label: "Bill Date", required: true, hint: "YYYY-MM-DD" },
  { key: "due_date", label: "Due Date", required: false, hint: "YYYY-MM-DD (optional)" },
  { key: "description", label: "Description", required: true, hint: "Line item description" },
  { key: "hsn_sac", label: "HSN/SAC", required: false, hint: "HSN or SAC code (optional)" },
  { key: "quantity", label: "Quantity", required: true, hint: "e.g. 1" },
  { key: "rate", label: "Rate (₹)", required: true, hint: "Per-unit rate in rupees" },
  { key: "gst_rate", label: "GST %", required: true, hint: "e.g. 18 (for 18%)" },
];

export function buildPurchaseBills(
  rows: Record<string, string>[],
  clientId: string,
  vendors: NameRef[],
): { bills: BuiltBill[]; errors: string[] } {
  const byName = new Map(vendors.map((v) => [v.name.trim().toLowerCase(), v.id]));
  const groups = new Map<string, BuiltBill>();
  const errors: string[] = [];

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const vendorName = str(r.vendor);
    const billDate = str(r.bill_date);
    const dueDate = str(r.due_date);
    const description = str(r.description);
    const billNo = str(r.bill_no);
    const vendorId = byName.get(vendorName.toLowerCase());

    if (!vendorId) { errors.push(`Row ${rowNo}: unknown vendor "${vendorName}" — create the vendor first`); return; }
    if (!DATE_RE.test(billDate)) { errors.push(`Row ${rowNo}: bill_date must be YYYY-MM-DD`); return; }
    if (dueDate && !DATE_RE.test(dueDate)) { errors.push(`Row ${rowNo}: due_date must be YYYY-MM-DD`); return; }
    if (!description) { errors.push(`Row ${rowNo}: description is required`); return; }

    const qty = num(r.quantity);
    const rate = num(r.rate);
    const gst = num(r.gst_rate);
    if (!Number.isFinite(qty) || qty <= 0) { errors.push(`Row ${rowNo}: quantity must be a positive number`); return; }
    if (!Number.isFinite(rate) || rate < 0) { errors.push(`Row ${rowNo}: rate (₹) must be a non-negative number`); return; }
    if (!Number.isFinite(gst) || gst < 0) { errors.push(`Row ${rowNo}: GST % must be a non-negative number`); return; }

    const ref = billNo || `${vendorName.toLowerCase()}|${billDate}`;
    const line: BuiltBillLine = {
      description,
      hsn_sac: str(r.hsn_sac) || undefined,
      quantity: qty,
      rate_paise: toPaise(r.rate),
      gst_rate_percent: gst,
    };

    const existing = groups.get(ref);
    if (existing) {
      if (existing.vendor_id !== vendorId) {
        errors.push(`Row ${rowNo}: bill_no "${ref}" is used with a different vendor`); return;
      }
      existing.lines.push(line);
    } else {
      groups.set(ref, {
        client_id: clientId,
        vendor_id: vendorId,
        bill_date: billDate,
        due_date: dueDate || undefined,
        bill_no: billNo || undefined,
        lines: [line],
        ref,
      });
    }
  });

  return { bills: Array.from(groups.values()), errors };
}

// ── Receipts → POST /api/receipts/ ──────────────────────────────────────────

const PAYMENT_MODES = ["bank", "cash", "cheque", "upi", "neft", "rtgs"];

export interface BuiltReceipt {
  client_id: string;
  customer_id: string;
  receipt_date: string;
  amount_paise: number;
  payment_mode: string;
  reference_no?: string;
}

export const RECEIPT_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "customer", label: "Customer", required: true, hint: "Existing customer name (must already exist for this client)" },
  { key: "receipt_date", label: "Receipt Date", required: true, hint: "YYYY-MM-DD" },
  { key: "amount", label: "Amount (₹)", required: true, hint: "Amount received in rupees" },
  { key: "payment_mode", label: "Payment Mode", required: true, hint: "bank / cash / cheque / upi / neft / rtgs" },
  { key: "reference_no", label: "Reference No", required: false, hint: "UTR / cheque no (optional)" },
];

export function buildReceipts(
  rows: Record<string, string>[],
  clientId: string,
  customers: NameRef[],
): { records: BuiltReceipt[]; errors: string[] } {
  const byName = new Map(customers.map((c) => [c.name.trim().toLowerCase(), c.id]));
  const records: BuiltReceipt[] = [];
  const errors: string[] = [];

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const customerName = str(r.customer);
    const receiptDate = str(r.receipt_date);
    const customerId = byName.get(customerName.toLowerCase());
    const mode = str(r.payment_mode).toLowerCase();
    const amountPaise = toPaise(r.amount);

    if (!customerId) { errors.push(`Row ${rowNo}: unknown customer "${customerName}" — create the customer first`); return; }
    if (!DATE_RE.test(receiptDate)) { errors.push(`Row ${rowNo}: receipt_date must be YYYY-MM-DD`); return; }
    if (!Number.isFinite(num(r.amount)) || amountPaise <= 0) { errors.push(`Row ${rowNo}: amount (₹) must be greater than zero`); return; }
    if (!PAYMENT_MODES.includes(mode)) { errors.push(`Row ${rowNo}: payment_mode must be one of ${PAYMENT_MODES.join(", ")}`); return; }

    records.push({
      client_id: clientId,
      customer_id: customerId,
      receipt_date: receiptDate,
      amount_paise: amountPaise,
      payment_mode: mode,
      reference_no: str(r.reference_no) || undefined,
    });
  });

  return { records, errors };
}

// ── Payroll employees → POST /api/payroll/employees ─────────────────────────

export interface BuiltEmployee {
  client_id: string;
  firm_id: string;
  name: string;
  pan?: string;
  // Privacy-by-design: only the last 4 digits of Aadhaar are ever stored/sent.
  aadhaar_last4?: string;
  designation?: string;
  department?: string;
  basic_paise: number;
  hra_percent: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
  pt_applicable: boolean;
}

export const EMPLOYEE_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "name", label: "Name", required: true, hint: "Employee full name" },
  { key: "pan", label: "PAN", required: false, hint: "10-char PAN (optional)" },
  { key: "aadhaar", label: "Aadhaar", required: false, hint: "12-digit Aadhaar (optional) — only the last 4 digits are stored" },
  { key: "designation", label: "Designation", required: false, hint: "e.g. Manager (optional)" },
  { key: "department", label: "Department", required: false, hint: "e.g. Accounts (optional)" },
  { key: "basic", label: "Basic Salary (₹/month)", required: true, hint: "Monthly basic in rupees, e.g. 25000" },
  { key: "hra_percent", label: "HRA %", required: false, hint: "Defaults to 40 if blank" },
  { key: "pf_applicable", label: "PF Applicable", required: false, hint: "yes / no (default yes)" },
  { key: "esi_applicable", label: "ESI Applicable", required: false, hint: "yes / no (default yes)" },
  { key: "pt_applicable", label: "PT Applicable", required: false, hint: "yes / no (default no)" },
];

export function buildEmployees(
  rows: Record<string, string>[],
  clientId: string,
  firmId: string,
): { records: BuiltEmployee[]; errors: string[] } {
  const records: BuiltEmployee[] = [];
  const errors: string[] = [];

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const name = str(r.name);
    if (!name) { errors.push(`Row ${rowNo}: name is required`); return; }

    const basicPaise = toPaise(r.basic);
    if (!Number.isFinite(num(r.basic)) || basicPaise <= 0) {
      errors.push(`Row ${rowNo}: basic salary (₹) must be greater than zero`); return;
    }

    const pan = str(r.pan).toUpperCase() || undefined;
    if (pan && !PAN_RE.test(pan)) { errors.push(`Row ${rowNo}: invalid PAN "${pan}"`); return; }

    // Aadhaar: accept the full 12 digits the firm has, but keep ONLY the last 4.
    // The full number is never placed on the built record (so it is never sent/stored).
    let aadhaarLast4: string | undefined;
    const aadhaarDigits = str(r.aadhaar).replace(/\D/g, "");
    if (aadhaarDigits) {
      if (aadhaarDigits.length !== 12) { errors.push(`Row ${rowNo}: Aadhaar must be 12 digits`); return; }
      aadhaarLast4 = aadhaarDigits.slice(-4);
    }

    const hraRaw = str(r.hra_percent);
    const hraPercent = hraRaw ? num(r.hra_percent) : 40;
    if (hraRaw && (!Number.isFinite(hraPercent) || hraPercent < 0)) {
      errors.push(`Row ${rowNo}: HRA % must be a non-negative number`); return;
    }

    records.push({
      client_id: clientId,
      firm_id: firmId,
      name,
      pan,
      aadhaar_last4: aadhaarLast4,
      designation: str(r.designation) || undefined,
      department: str(r.department) || undefined,
      basic_paise: basicPaise,
      hra_percent: hraPercent,
      pf_applicable: toBool(r.pf_applicable, true),
      esi_applicable: toBool(r.esi_applicable, true),
      pt_applicable: toBool(r.pt_applicable, false),
    });
  });

  return { records, errors };
}
