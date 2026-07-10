/**
 * Product & Service master — pure domain helpers (Batch 6; broadened to
 * goods in the HSN/SAC redesign; made client-owned in migration 182). No
 * framework/browser deps, so this is unit-testable under `node --test` and
 * shared by the picker, the client-workspace management page and the editor
 * integration.
 *
 * A catalogue item is a billing preset for goods OR services (name +
 * default HSN/SAC, GST rate, price). Picking one drops a fully pre-priced
 * invoice line; the values are a starting point the CA can edit, and are
 * copied onto the line (never linked), so a later edit/archive of the
 * preset can't change a past invoice. There is deliberately no
 * stock/quantity/valuation/SKU/barcode/warehouse concept here.
 */
import type { InvoiceLine } from "../invoices/gst";

export interface ServiceCatalogueItem {
  id: string;
  client_id: string;
  name: string;
  description?: string | null;
  kind?: "good" | "service";
  hsn_sac?: string | null;
  gst_rate_bps?: number | null;
  default_rate_paise: number;
  purchase_price_paise?: number | null;
  unit?: string | null;
  category?: string | null;
  notes?: string | null;
  is_active: boolean;
  use_count?: number | null;
  last_used_at?: string | null;
  /** Set by the API when a create collided with an existing active name. */
  duplicate?: boolean;
}

/** Map a preset to the editor line fields it pre-fills (qty is left to the caller). */
export function serviceToLine(item: ServiceCatalogueItem): Pick<InvoiceLine, "description" | "hsn_sac" | "rate" | "gst_rate" | "unit"> {
  return {
    description: (item.description?.trim() || item.name).trim(),
    hsn_sac: item.hsn_sac ?? "",
    rate: item.default_rate_paise ? String(item.default_rate_paise / 100) : "",
    gst_rate: item.gst_rate_bps == null ? 0 : item.gst_rate_bps / 100,
    unit: item.unit ?? "",
  };
}

/** User-facing label for a catalogue item's kind — "good" (the CGST goods/
 * HSN vs services/SAC distinction used throughout the domain model and the
 * HSN/SAC library) reads as "Product" everywhere a CA sees it, matching the
 * "Product/Service" naming this whole module uses; the stored value stays
 * "good" so it keeps lining up with hsn_type and the backend model. */
export function formatServiceKind(kind?: "good" | "service" | null): string {
  return kind === "good" ? "Product" : "Service";
}

/** "18% GST" / "" (unknown rate stays blank — never shown as 0%). */
export function formatServiceRate(bps?: number | null): string {
  if (bps == null) return "";
  const pct = bps / 100;
  return `${Number.isInteger(pct) ? pct : pct.toFixed(2)}% GST`;
}

/** "₹50,000" / "₹123.45" from integer paise (Indian grouping; shows paise only
 * when the amount isn't a whole rupee, so a stored ₹123.45 is never truncated). */
export function formatServicePrice(paise?: number | null): string {
  if (!paise) return "";
  const hasPaise = paise % 100 !== 0;
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: hasPaise ? 2 : 0,
    maximumFractionDigits: 2,
  })}`;
}

/** The muted secondary line for a picker/list row. */
export function serviceSecondaryLine(item: ServiceCatalogueItem): string {
  return [
    item.hsn_sac ? `SAC ${item.hsn_sac}` : "",
    formatServiceRate(item.gst_rate_bps),
    formatServicePrice(item.default_rate_paise),
  ].filter(Boolean).join(" · ");
}

// ── Management-form validation + payload mapping ──────────────────────────────
export interface ServiceFormInput {
  name: string;
  description: string;
  kind: "good" | "service";
  hsn_sac: string;
  gstRate: number;      // percent, e.g. 18
  rate: string;         // selling price, rupees (free text)
  purchasePrice: string; // rupees (free text), optional
  category: string;
  notes: string;
}

export interface ServiceFormValidation {
  errors: { name?: string; rate?: string; gstRate?: string; purchasePrice?: string };
  ok: boolean;
}

export function validateServiceForm(input: ServiceFormInput): ServiceFormValidation {
  const errors: ServiceFormValidation["errors"] = {};
  if (!input.name.trim()) errors.name = "Name is required.";
  const rate = parseFloat(input.rate);
  if (input.rate.trim() !== "" && (!Number.isFinite(rate) || rate < 0)) {
    errors.rate = "Enter a valid non-negative price.";
  }
  const purchasePrice = parseFloat(input.purchasePrice);
  if (input.purchasePrice.trim() !== "" && (!Number.isFinite(purchasePrice) || purchasePrice < 0)) {
    errors.purchasePrice = "Enter a valid non-negative price.";
  }
  if (!Number.isFinite(input.gstRate) || input.gstRate < 0 || input.gstRate > 100) {
    errors.gstRate = "GST rate must be between 0 and 100.";
  }
  return { errors, ok: Object.keys(errors).length === 0 };
}

export interface ServicePayload {
  client_id: string;
  name: string;
  description?: string;
  kind: "good" | "service";
  hsn_sac?: string;
  gst_rate_bps: number;
  default_rate_paise: number;
  purchase_price_paise?: number;
  category?: string;
  notes?: string;
}

/** Map a validated form to the API create/update body (rupees → integer paise). */
export function serviceFormToPayload(input: ServiceFormInput, clientId: string): ServicePayload {
  const rupees = parseFloat(input.rate);
  const purchaseRupees = parseFloat(input.purchasePrice);
  return {
    client_id: clientId,
    name: input.name.trim(),
    description: input.description.trim() || undefined,
    kind: input.kind,
    hsn_sac: input.hsn_sac.trim() || undefined,
    gst_rate_bps: Math.round((input.gstRate || 0) * 100),
    default_rate_paise: Number.isFinite(rupees) && rupees > 0 ? Math.round(rupees * 100) : 0,
    purchase_price_paise: Number.isFinite(purchaseRupees) && purchaseRupees > 0 ? Math.round(purchaseRupees * 100) : undefined,
    category: input.category.trim() || undefined,
    notes: input.notes.trim() || undefined,
  };
}

/** Seed a form from an existing item (for the Edit modal). */
export function serviceToForm(item: ServiceCatalogueItem): ServiceFormInput {
  return {
    name: item.name,
    description: item.description ?? "",
    kind: item.kind ?? "service",
    hsn_sac: item.hsn_sac ?? "",
    gstRate: item.gst_rate_bps == null ? 18 : item.gst_rate_bps / 100,
    rate: item.default_rate_paise ? String(item.default_rate_paise / 100) : "",
    purchasePrice: item.purchase_price_paise ? String(item.purchase_price_paise / 100) : "",
    category: item.category ?? "",
    notes: item.notes ?? "",
  };
}
