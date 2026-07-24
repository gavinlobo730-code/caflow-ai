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
    // A blank/absent opening_balance must map to 0, not NaN — toPaise("") is
    // NaN, which JSON.stringify turns into `null` on the wire, and the
    // backend's opening_balance_paise: int = 0 (non-Optional) rejects a
    // literal null with a validation error, failing every row that leaves
    // this optional column blank.
    const openingBalanceRaw = str(r.opening_balance);
    const openingBalancePaise = openingBalanceRaw ? toPaise(r.opening_balance) : 0;
    if (openingBalanceRaw && !Number.isFinite(openingBalancePaise)) {
      errors.push(`Row ${rowNo}: opening_balance must be a valid number`); return;
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
      opening_balance_paise: openingBalancePaise,
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

    // A blank/absent opening_balance must map to 0, not NaN — toPaise("") is
    // NaN, which JSON.stringify turns into `null` on the wire, and the
    // backend's opening_balance_paise: int = 0 (non-Optional) rejects a
    // literal null with a validation error, failing every row that leaves
    // this optional column blank.
    const openingBalanceRaw = str(r.opening_balance);
    const openingBalancePaise = openingBalanceRaw ? toPaise(r.opening_balance) : 0;
    if (openingBalanceRaw && !Number.isFinite(openingBalancePaise)) {
      errors.push(`Row ${rowNo}: opening_balance must be a valid number`); return;
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
      opening_balance_paise: openingBalancePaise,
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
  unit?: string;
  // Links this line to a Product/Service catalogue item so a RECEIVED bill
  // actually restocks inventory — domain/inventory_service.py's
  // apply_purchase_to_inventory only moves stock for lines carrying this
  // (see PurchaseBillLineIn.service_catalogue_id). Mirrors
  // lib/invoices/importMapping.ts's BuiltLine.service_catalogue_id, which
  // has the identical gap on the sales side.
  service_catalogue_id?: string;
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

/** The subset of ServiceCatalogueItem this mapper needs to pre-fill a line.
 * Mirrors lib/invoices/importMapping.ts's own ServiceRef, but prefills rate
 * from purchase_price_paise (not the selling default_rate_paise) — these
 * are PURCHASE lines. */
export interface PurchaseServiceRef {
  id: string;
  name: string;
  description?: string | null;
  hsn_sac?: string | null;
  gst_rate_bps?: number | null;
  purchase_price_paise?: number | null;
  unit?: string | null;
}

export const PURCHASE_BILL_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "vendor", label: "Vendor", required: true, hint: "Existing vendor name (must already exist for this client)" },
  { key: "bill_no", label: "Bill No", required: false, hint: "Vendor's bill number (also groups multiple line rows into one bill)" },
  { key: "bill_date", label: "Bill Date", required: true, hint: "YYYY-MM-DD" },
  { key: "due_date", label: "Due Date", required: false, hint: "YYYY-MM-DD (optional)" },
  { key: "product_service", label: "Product/Service", required: false, hint: "Existing catalogue item name (optional) — links this line so a received bill restocks inventory, and pre-fills HSN/rate/GST/unit" },
  { key: "description", label: "Description", required: false, hint: "Required unless Product/Service is given" },
  { key: "hsn_sac", label: "HSN/SAC", required: false, hint: "HSN or SAC code (optional; overrides the Product/Service's own)" },
  { key: "quantity", label: "Quantity", required: true, hint: "e.g. 1" },
  { key: "rate", label: "Rate (₹)", required: false, hint: "Per-unit rate in rupees — required unless Product/Service has a purchase price" },
  { key: "gst_rate", label: "GST %", required: false, hint: "e.g. 18 (for 18%) — required unless Product/Service is given" },
];

export function buildPurchaseBills(
  rows: Record<string, string>[],
  clientId: string,
  vendors: NameRef[],
  services: PurchaseServiceRef[] = [],
): { bills: BuiltBill[]; errors: string[] } {
  const byName = new Map(vendors.map((v) => [v.name.trim().toLowerCase(), v.id]));
  const servicesByName = new Map(services.map((s) => [s.name.trim().toLowerCase(), s]));
  const groups = new Map<string, BuiltBill>();
  const errors: string[] = [];

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const vendorName = str(r.vendor);
    const billDate = str(r.bill_date);
    const dueDate = str(r.due_date);
    const billNo = str(r.bill_no);
    const productName = str(r.product_service);
    const vendorId = byName.get(vendorName.toLowerCase());
    const service = productName ? servicesByName.get(productName.toLowerCase()) : undefined;

    if (!vendorId) { errors.push(`Row ${rowNo}: unknown vendor "${vendorName}" — create the vendor first`); return; }
    if (!DATE_RE.test(billDate)) { errors.push(`Row ${rowNo}: bill_date must be YYYY-MM-DD`); return; }
    if (dueDate && !DATE_RE.test(dueDate)) { errors.push(`Row ${rowNo}: due_date must be YYYY-MM-DD`); return; }
    if (productName && !service) { errors.push(`Row ${rowNo}: unknown product/service "${productName}" — create it first`); return; }

    const description = str(r.description) || (service?.description?.trim() ?? "");
    if (!description) { errors.push(`Row ${rowNo}: description is required (or use a Product/Service that has its own description set)`); return; }

    const qty = num(r.quantity);
    if (!Number.isFinite(qty) || qty <= 0) { errors.push(`Row ${rowNo}: quantity must be a positive number`); return; }

    const rateRaw = str(r.rate);
    const rate = rateRaw ? num(r.rate) : (service?.purchase_price_paise != null ? service.purchase_price_paise / 100 : NaN);
    if (!Number.isFinite(rate) || rate < 0) { errors.push(`Row ${rowNo}: rate (₹) must be a non-negative number (or give a Product/Service with a purchase price)`); return; }

    const gstRaw = str(r.gst_rate);
    const gst = gstRaw ? num(r.gst_rate) : (service?.gst_rate_bps != null ? service.gst_rate_bps / 100 : NaN);
    if (!Number.isFinite(gst) || gst < 0) { errors.push(`Row ${rowNo}: GST % must be a non-negative number (or give a Product/Service with a default rate)`); return; }

    const ref = billNo || `${vendorName.toLowerCase()}|${billDate}`;
    const line: BuiltBillLine = {
      description,
      hsn_sac: str(r.hsn_sac) || service?.hsn_sac?.trim() || undefined,
      quantity: qty,
      rate_paise: Math.round(rate * 100),
      gst_rate_percent: gst,
      unit: service?.unit?.trim() || undefined,
      service_catalogue_id: service?.id,
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

// ── Credit & Debit Notes ─────────────────────────────────────────────────────
// Four entities, one shared row-parsing core per side (sales / purchase) since
// within a side the party type, linked document and service pricing field are
// identical — only the note direction (credit vs debit) and target endpoint differ:
//   Sales Credit Note   → POST /api/credit-notes/            (decrease AR)
//   Sales Debit Note    → POST /api/sales-debit-notes/       (increase AR)
//   Purchase Debit Note → POST /api/debit-notes/             (decrease AP)
//   Purchase Credit Note→ POST /api/purchase-credit-notes/   (increase AP)
//
// All four share InvoiceLineIn (apps/api/models/invoices.py), whose
// model_validator makes service_catalogue_id MANDATORY on every line ("Product/
// Service is required on every line item") — unlike buildSalesInvoices/
// buildPurchaseBills above, which still treat product_service as an optional
// pre-fill even though the same backend model now rejects a line with no
// catalogue link. product_service is therefore a REQUIRED column here.
//
// is_interstate is handled per-endpoint by the backend, and inconsistently:
// - routers/credit_notes.py IGNORES any client-sent is_interstate and always
//   re-derives it from the linked sales_invoice_id, forcing False when none is
//   linked — a standalone (unlinked) Sales Credit Note can never be interstate
//   via the API today.
// - routers/debit_notes.py, sales_debit_notes.py and purchase_credit_notes.py
//   all trust the client-sent is_interstate directly, with NO auto-derivation
//   from a linked bill/invoice.
// This mapper derives is_interstate from the linked document whenever an
// invoice/bill number is given (correct for all four regardless of which
// behaviour the endpoint has) and falls back to an explicit is_interstate
// column only for a standalone note with nothing linked.

function toYesNoOptional(v: string | undefined): boolean | undefined {
  const s = str(v).toLowerCase();
  if (!s) return undefined;
  return ["yes", "y", "true", "1", "t"].includes(s);
}

/** An existing Sales Invoice or Purchase Bill this note may link to. */
export interface OriginalDocRef {
  id: string;
  no: string;           // invoice_no or bill_no
  partyId: string;       // customer_id or vendor_id
  isInterstate: boolean;
}

/** Same shape as ServiceRef (lib/invoices/importMapping.ts) — duplicated
 * locally (5 fields) rather than importing across modules, matching how
 * PurchaseServiceRef above already stands alone in this file. */
export interface SalesServiceRef {
  id: string;
  name: string;
  description?: string | null;
  hsn_sac?: string | null;
  gst_rate_bps?: number | null;
  default_rate_paise?: number | null;
  unit?: string | null;
}

export interface BuiltNoteLine {
  description: string;
  hsn_sac?: string;
  quantity: number;
  rate_paise: number;
  gst_rate_percent: number;
  unit?: string;
  service_catalogue_id: string;
}

interface NoteGroup {
  partyId: string;
  docId?: string;
  noteDate: string;
  reason?: string;
  isInterstate: boolean;
  isReverseCharge: boolean;
  lines: BuiltNoteLine[];
}

/** Shared line/grouping parser for both Sales Credit Notes and Sales Debit
 * Notes — identical row shape (customer, optional linked sales invoice,
 * product_service-driven lines), differing only in the date column's label
 * and which endpoint the caller eventually posts to. */
function parseSalesNoteRows(
  rows: Record<string, string>[],
  dateColumnKey: string,
  customers: NameRef[],
  invoices: OriginalDocRef[],
  services: SalesServiceRef[],
): { groups: Map<string, NoteGroup>; errors: string[] } {
  const customersByName = new Map(customers.map((c) => [c.name.trim().toLowerCase(), c.id]));
  const invoicesByNo = new Map(invoices.map((d) => [d.no.trim().toLowerCase(), d]));
  const servicesByName = new Map(services.map((s) => [s.name.trim().toLowerCase(), s]));
  const groups = new Map<string, NoteGroup>();
  const errors: string[] = [];

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const customerName = str(r.customer);
    const invoiceNo = str(r.invoice_no);
    const noteRef = str(r.note_ref);
    const noteDate = str(r[dateColumnKey]);
    const explicitInterstate = toYesNoOptional(r.is_interstate);
    const productName = str(r.product_service);
    const service = productName ? servicesByName.get(productName.toLowerCase()) : undefined;

    let customerId = customersByName.get(customerName.toLowerCase());
    let docId: string | undefined;
    let isInterstate = explicitInterstate ?? false;

    if (invoiceNo) {
      const doc = invoicesByNo.get(invoiceNo.toLowerCase());
      if (!doc) { errors.push(`Row ${rowNo}: unknown invoice_no "${invoiceNo}" — it must already exist for this client`); return; }
      docId = doc.id;
      isInterstate = doc.isInterstate;
      if (customerName && customerId && customerId !== doc.partyId) {
        errors.push(`Row ${rowNo}: customer "${customerName}" does not match the customer on invoice "${invoiceNo}"`); return;
      }
      customerId = doc.partyId;
    }

    if (!customerId) { errors.push(`Row ${rowNo}: unknown customer "${customerName}" — create the customer first, or link a valid invoice_no`); return; }
    if (!DATE_RE.test(noteDate)) { errors.push(`Row ${rowNo}: ${dateColumnKey} must be YYYY-MM-DD`); return; }
    if (!productName) { errors.push(`Row ${rowNo}: product_service is required on every line (Product/Service is mandatory on every credit/debit note line)`); return; }
    if (!service) { errors.push(`Row ${rowNo}: unknown product/service "${productName}" — create it first`); return; }

    const description = str(r.description) || (service.description?.trim() ?? "");
    if (!description) { errors.push(`Row ${rowNo}: description is required (or use a Product/Service that has its own description set)`); return; }

    const qty = num(r.quantity);
    if (!Number.isFinite(qty) || qty <= 0) { errors.push(`Row ${rowNo}: quantity must be a positive number`); return; }

    const rateRaw = str(r.rate);
    const rate = rateRaw ? num(r.rate) : (service.default_rate_paise != null ? service.default_rate_paise / 100 : NaN);
    if (!Number.isFinite(rate) || rate < 0) { errors.push(`Row ${rowNo}: rate (₹) must be a non-negative number (or use a Product/Service with a default price)`); return; }

    const gstRaw = str(r.gst_rate);
    const gst = gstRaw ? num(r.gst_rate) : (service.gst_rate_bps != null ? service.gst_rate_bps / 100 : NaN);
    if (!Number.isFinite(gst) || gst < 0) { errors.push(`Row ${rowNo}: GST % must be a non-negative number (or use a Product/Service with a default rate)`); return; }

    const line: BuiltNoteLine = {
      description,
      hsn_sac: str(r.hsn_sac) || service.hsn_sac?.trim() || undefined,
      quantity: qty,
      rate_paise: Math.round(rate * 100),
      gst_rate_percent: gst,
      unit: service.unit?.trim() || undefined,
      service_catalogue_id: service.id,
    };

    const key = noteRef || invoiceNo || `${customerName.toLowerCase()}|${noteDate}`;
    const existing = groups.get(key);
    if (existing) {
      if (existing.partyId !== customerId) { errors.push(`Row ${rowNo}: rows grouped under "${key}" reference different customers`); return; }
      if (existing.noteDate !== noteDate) { errors.push(`Row ${rowNo}: rows grouped under "${key}" have different ${dateColumnKey} values`); return; }
      existing.lines.push(line);
    } else {
      groups.set(key, { partyId: customerId, docId, noteDate, reason: str(r.reason) || undefined, isInterstate, isReverseCharge: false, lines: [line] });
    }
  });

  return { groups, errors };
}

const NOTE_LINE_COLUMNS: ImportColumn[] = [
  { key: "product_service", label: "Product/Service", required: true, hint: "Existing catalogue item name — REQUIRED on every credit/debit note line" },
  { key: "description", label: "Description", required: false, hint: "Overrides the Product/Service's own description (optional)" },
  { key: "hsn_sac", label: "HSN/SAC", required: false, hint: "Overrides the Product/Service's own HSN/SAC (optional)" },
  { key: "quantity", label: "Quantity", required: true, hint: "e.g. 1" },
  { key: "rate", label: "Rate (₹)", required: false, hint: "Per-unit rate — required unless the Product/Service has a default price" },
  { key: "gst_rate", label: "GST %", required: false, hint: "e.g. 18 — required unless the Product/Service has a default rate" },
];

// ── Sales Credit Notes → POST /api/credit-notes/ ────────────────────────────

export interface BuiltSalesCreditNote {
  client_id: string;
  customer_id: string;
  credit_note_date: string;
  sales_invoice_id?: string;
  reason?: string;
  is_interstate: boolean;
  lines: BuiltNoteLine[];
}

export const SALES_CREDIT_NOTE_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "customer", label: "Customer", required: true, hint: "Existing customer name (must already exist for this client)" },
  { key: "invoice_no", label: "Invoice No", required: false, hint: "Existing Sales Invoice number to credit against (optional, recommended). Also groups multiple line rows into one note." },
  { key: "credit_note_date", label: "Credit Note Date", required: true, hint: "YYYY-MM-DD" },
  { key: "reason", label: "Reason", required: false, hint: "Free text, e.g. Sales return (optional)" },
  { key: "is_interstate", label: "Interstate", required: false, hint: "yes/no — only used when Invoice No is blank; a note linked to an invoice always inherits that invoice's own treatment" },
  { key: "note_ref", label: "Note Reference", required: false, hint: "Your own reference to group multiple lines into one note when Invoice No isn't enough (e.g. two separate notes against the same invoice) — not stored, grouping only" },
  ...NOTE_LINE_COLUMNS,
];

export function buildSalesCreditNotes(
  rows: Record<string, string>[],
  clientId: string,
  customers: NameRef[],
  invoices: OriginalDocRef[],
  services: SalesServiceRef[] = [],
): { notes: BuiltSalesCreditNote[]; errors: string[] } {
  const { groups, errors } = parseSalesNoteRows(rows, "credit_note_date", customers, invoices, services);
  const notes = Array.from(groups.values()).map((g) => ({
    client_id: clientId,
    customer_id: g.partyId,
    credit_note_date: g.noteDate,
    sales_invoice_id: g.docId,
    reason: g.reason,
    is_interstate: g.isInterstate,
    lines: g.lines,
  }));
  return { notes, errors };
}

// ── Sales Debit Notes → POST /api/sales-debit-notes/ ────────────────────────

export interface BuiltSalesDebitNote {
  client_id: string;
  customer_id: string;
  debit_note_date: string;
  sales_invoice_id?: string;
  reason?: string;
  is_interstate: boolean;
  lines: BuiltNoteLine[];
}

export const SALES_DEBIT_NOTE_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "customer", label: "Customer", required: true, hint: "Existing customer name (must already exist for this client)" },
  { key: "invoice_no", label: "Invoice No", required: false, hint: "Existing Sales Invoice number to debit against (optional, recommended). Also groups multiple line rows into one note." },
  { key: "debit_note_date", label: "Debit Note Date", required: true, hint: "YYYY-MM-DD" },
  { key: "reason", label: "Reason", required: false, hint: "Free text, e.g. Undercharge correction (optional)" },
  { key: "is_interstate", label: "Interstate", required: false, hint: "yes/no — used when Invoice No is blank; when Invoice No is given, this mapper still derives it from that invoice" },
  { key: "note_ref", label: "Note Reference", required: false, hint: "Your own reference to group multiple lines into one note when Invoice No isn't enough — not stored, grouping only" },
  ...NOTE_LINE_COLUMNS,
];

export function buildSalesDebitNotes(
  rows: Record<string, string>[],
  clientId: string,
  customers: NameRef[],
  invoices: OriginalDocRef[],
  services: SalesServiceRef[] = [],
): { notes: BuiltSalesDebitNote[]; errors: string[] } {
  const { groups, errors } = parseSalesNoteRows(rows, "debit_note_date", customers, invoices, services);
  const notes = Array.from(groups.values()).map((g) => ({
    client_id: clientId,
    customer_id: g.partyId,
    debit_note_date: g.noteDate,
    sales_invoice_id: g.docId,
    reason: g.reason,
    is_interstate: g.isInterstate,
    lines: g.lines,
  }));
  return { notes, errors };
}

/** Shared line/grouping parser for both Purchase Debit Notes and Purchase
 * Credit Notes — identical row shape (vendor, optional linked purchase bill,
 * product_service-driven lines, is_reverse_charge), mirroring
 * parseSalesNoteRows above. */
function parsePurchaseNoteRows(
  rows: Record<string, string>[],
  dateColumnKey: string,
  vendors: NameRef[],
  bills: OriginalDocRef[],
  services: PurchaseServiceRef[],
): { groups: Map<string, NoteGroup>; errors: string[] } {
  const vendorsByName = new Map(vendors.map((v) => [v.name.trim().toLowerCase(), v.id]));
  const billsByNo = new Map(bills.map((d) => [d.no.trim().toLowerCase(), d]));
  const servicesByName = new Map(services.map((s) => [s.name.trim().toLowerCase(), s]));
  const groups = new Map<string, NoteGroup>();
  const errors: string[] = [];

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const vendorName = str(r.vendor);
    const billNo = str(r.bill_no);
    const noteRef = str(r.note_ref);
    const noteDate = str(r[dateColumnKey]);
    const explicitInterstate = toYesNoOptional(r.is_interstate);
    const isReverseCharge = toBool(r.is_reverse_charge, false);
    const productName = str(r.product_service);
    const service = productName ? servicesByName.get(productName.toLowerCase()) : undefined;

    let vendorId = vendorsByName.get(vendorName.toLowerCase());
    let docId: string | undefined;
    let isInterstate = explicitInterstate ?? false;

    if (billNo) {
      const doc = billsByNo.get(billNo.toLowerCase());
      if (!doc) { errors.push(`Row ${rowNo}: unknown bill_no "${billNo}" — it must already exist for this client`); return; }
      docId = doc.id;
      isInterstate = doc.isInterstate;
      if (vendorName && vendorId && vendorId !== doc.partyId) {
        errors.push(`Row ${rowNo}: vendor "${vendorName}" does not match the vendor on bill "${billNo}"`); return;
      }
      vendorId = doc.partyId;
    }

    if (!vendorId) { errors.push(`Row ${rowNo}: unknown vendor "${vendorName}" — create the vendor first, or link a valid bill_no`); return; }
    if (!DATE_RE.test(noteDate)) { errors.push(`Row ${rowNo}: ${dateColumnKey} must be YYYY-MM-DD`); return; }
    if (!productName) { errors.push(`Row ${rowNo}: product_service is required on every line (Product/Service is mandatory on every credit/debit note line)`); return; }
    if (!service) { errors.push(`Row ${rowNo}: unknown product/service "${productName}" — create it first`); return; }

    const description = str(r.description) || (service.description?.trim() ?? "");
    if (!description) { errors.push(`Row ${rowNo}: description is required (or use a Product/Service that has its own description set)`); return; }

    const qty = num(r.quantity);
    if (!Number.isFinite(qty) || qty <= 0) { errors.push(`Row ${rowNo}: quantity must be a positive number`); return; }

    const rateRaw = str(r.rate);
    const rate = rateRaw ? num(r.rate) : (service.purchase_price_paise != null ? service.purchase_price_paise / 100 : NaN);
    if (!Number.isFinite(rate) || rate < 0) { errors.push(`Row ${rowNo}: rate (₹) must be a non-negative number (or use a Product/Service with a purchase price)`); return; }

    const gstRaw = str(r.gst_rate);
    const gst = gstRaw ? num(r.gst_rate) : (service.gst_rate_bps != null ? service.gst_rate_bps / 100 : NaN);
    if (!Number.isFinite(gst) || gst < 0) { errors.push(`Row ${rowNo}: GST % must be a non-negative number (or use a Product/Service with a default rate)`); return; }

    const line: BuiltNoteLine = {
      description,
      hsn_sac: str(r.hsn_sac) || service.hsn_sac?.trim() || undefined,
      quantity: qty,
      rate_paise: Math.round(rate * 100),
      gst_rate_percent: gst,
      unit: service.unit?.trim() || undefined,
      service_catalogue_id: service.id,
    };

    const key = noteRef || billNo || `${vendorName.toLowerCase()}|${noteDate}`;
    const existing = groups.get(key);
    if (existing) {
      if (existing.partyId !== vendorId) { errors.push(`Row ${rowNo}: rows grouped under "${key}" reference different vendors`); return; }
      if (existing.noteDate !== noteDate) { errors.push(`Row ${rowNo}: rows grouped under "${key}" have different ${dateColumnKey} values`); return; }
      existing.lines.push(line);
    } else {
      groups.set(key, { partyId: vendorId, docId, noteDate, reason: str(r.reason) || undefined, isInterstate, isReverseCharge, lines: [line] });
    }
  });

  return { groups, errors };
}

const REVERSE_CHARGE_COLUMN: ImportColumn = { key: "is_reverse_charge", label: "Reverse Charge", required: false, hint: "yes/no — CGST Act §9(3)/9(4) (defaults to no)" };

// ── Purchase Debit Notes → POST /api/debit-notes/ ───────────────────────────

export interface BuiltPurchaseDebitNote {
  client_id: string;
  vendor_id: string;
  debit_note_date: string;
  purchase_bill_id?: string;
  reason?: string;
  is_interstate: boolean;
  is_reverse_charge: boolean;
  lines: BuiltNoteLine[];
}

export const PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "vendor", label: "Vendor", required: true, hint: "Existing vendor name (must already exist for this client)" },
  { key: "bill_no", label: "Bill No", required: false, hint: "Existing Purchase Bill number to debit against (optional, recommended). Also groups multiple line rows into one note." },
  { key: "debit_note_date", label: "Debit Note Date", required: true, hint: "YYYY-MM-DD" },
  { key: "reason", label: "Reason", required: false, hint: "Free text, e.g. Purchase return (optional)" },
  { key: "is_interstate", label: "Interstate", required: false, hint: "yes/no — only used when Bill No is blank; a note linked to a bill always inherits that bill's own treatment" },
  REVERSE_CHARGE_COLUMN,
  { key: "note_ref", label: "Note Reference", required: false, hint: "Your own reference to group multiple lines into one note when Bill No isn't enough — not stored, grouping only" },
  ...NOTE_LINE_COLUMNS,
];

export function buildPurchaseDebitNotes(
  rows: Record<string, string>[],
  clientId: string,
  vendors: NameRef[],
  bills: OriginalDocRef[],
  services: PurchaseServiceRef[] = [],
): { notes: BuiltPurchaseDebitNote[]; errors: string[] } {
  const { groups, errors } = parsePurchaseNoteRows(rows, "debit_note_date", vendors, bills, services);
  const notes = Array.from(groups.values()).map((g) => ({
    client_id: clientId,
    vendor_id: g.partyId,
    debit_note_date: g.noteDate,
    purchase_bill_id: g.docId,
    reason: g.reason,
    is_interstate: g.isInterstate,
    is_reverse_charge: g.isReverseCharge,
    lines: g.lines,
  }));
  return { notes, errors };
}

// ── Purchase Credit Notes → POST /api/purchase-credit-notes/ ───────────────

export interface BuiltPurchaseCreditNote {
  client_id: string;
  vendor_id: string;
  credit_note_date: string;
  purchase_bill_id?: string;
  reason?: string;
  is_interstate: boolean;
  is_reverse_charge: boolean;
  lines: BuiltNoteLine[];
}

export const PURCHASE_CREDIT_NOTE_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "vendor", label: "Vendor", required: true, hint: "Existing vendor name (must already exist for this client)" },
  { key: "bill_no", label: "Bill No", required: false, hint: "Existing Purchase Bill number to credit against (optional, recommended). Also groups multiple line rows into one note." },
  { key: "credit_note_date", label: "Credit Note Date", required: true, hint: "YYYY-MM-DD" },
  { key: "reason", label: "Reason", required: false, hint: "Free text, e.g. Vendor undercharge correction (optional)" },
  { key: "is_interstate", label: "Interstate", required: false, hint: "yes/no — used when Bill No is blank; when Bill No is given, this mapper still derives it from that bill" },
  REVERSE_CHARGE_COLUMN,
  { key: "note_ref", label: "Note Reference", required: false, hint: "Your own reference to group multiple lines into one note when Bill No isn't enough — not stored, grouping only" },
  ...NOTE_LINE_COLUMNS,
];

export function buildPurchaseCreditNotes(
  rows: Record<string, string>[],
  clientId: string,
  vendors: NameRef[],
  bills: OriginalDocRef[],
  services: PurchaseServiceRef[] = [],
): { notes: BuiltPurchaseCreditNote[]; errors: string[] } {
  const { groups, errors } = parsePurchaseNoteRows(rows, "credit_note_date", vendors, bills, services);
  const notes = Array.from(groups.values()).map((g) => ({
    client_id: clientId,
    vendor_id: g.partyId,
    credit_note_date: g.noteDate,
    purchase_bill_id: g.docId,
    reason: g.reason,
    is_interstate: g.isInterstate,
    is_reverse_charge: g.isReverseCharge,
    lines: g.lines,
  }));
  return { notes, errors };
}
