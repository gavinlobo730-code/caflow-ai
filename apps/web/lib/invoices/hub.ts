/**
 * Invoice Hub pure logic (Batch 4) — action availability by state, derived status
 * groups (delivery / compliance), and timeline assembly. No framework/browser deps,
 * so it lives beside the pure domain (./gst) and is unit-testable under node --test.
 *
 * These are DERIVED presentation concerns only: financial status stays the single
 * accounting truth; delivery + compliance are computed from side data (deliveries,
 * e-invoice / e-way records) and never fed back into the accounting state.
 */
import type { InvoiceStatus, InvoiceDelivery } from "./gst";

// ── Action availability ───────────────────────────────────────────────────────
export interface HubActions {
  edit: boolean;
  editDetails: boolean;
  delete: boolean;
  issue: boolean;
  recordPayment: boolean;
  paymentLink: boolean;
  send: boolean;
  duplicate: boolean;
  creditNote: boolean;
  viewJournal: boolean;
  pdf: boolean;
}

/** What a user may do to an invoice in a given financial state (prevents invalid actions). */
export function availableActions(status: InvoiceStatus): HubActions {
  const isDraft = status === "draft";
  const posted = status === "issued" || status === "partially_paid" || status === "paid";
  const collectible = status === "issued" || status === "partially_paid"; // owed money remains
  return {
    edit: isDraft,
    // Reference/PO number, notes, due date and line unit — none of these
    // affect amount or tax, so they stay editable once posted (routers/
    // sales_invoices.py: update_invoice's _SOFT_UPDATE_FIELDS). Everything
    // else needs a Credit Note to correct (CGST Act §34) — not editable
    // here even when posted, matching `edit` staying draft-only above.
    editDetails: posted,
    delete: isDraft,
    issue: isDraft,
    recordPayment: collectible,
    paymentLink: collectible,
    send: posted,                 // (re)send an issued document; a draft isn't a document yet
    duplicate: !isDraft,          // clone any real invoice; a draft is edited in place instead
    creditNote: posted,           // only a posted supply can be credited
    viewJournal: posted,          // a journal exists only after posting
    pdf: !isDraft,                // the tax invoice PDF is meaningful once issued
  };
}

// ── Delivery status (derived from invoice_deliveries) ─────────────────────────
export interface DeliverySummary {
  sent: boolean;
  viewed: boolean;
  lastSentTo: string | null;
  lastSentAt: string | null;
  /** Status of the delivery the summary reports on (keeps the Hub's
   * "Email status" consistent with its "Sent to / at" rows). */
  lastStatus: string | null;
  attempts: number;
}

/**
 * Summarise delivery from the deliveries list (newest-first as the API returns them).
 * "viewed" is not tracked yet (no open/tracking-pixel signal), so it stays false —
 * surfaced as a placeholder in the UI, never as an accounting state.
 */
export function deliverySummary(deliveries: InvoiceDelivery[]): DeliverySummary {
  const sentOnes = deliveries.filter((d) => d.status === "sent");
  const last = sentOnes[0] ?? deliveries[0] ?? null;
  return {
    sent: sentOnes.length > 0,
    viewed: false,
    lastSentTo: last?.sent_to ?? null,
    lastSentAt: last ? (last.sent_at ?? last.created_at) : null,
    lastStatus: last?.status ?? null,
    attempts: deliveries.length,
  };
}

// ── Compliance status (derived from e-invoice / e-way records) ────────────────
export interface ComplianceRecord {
  sales_invoice_id?: string | null;
  irn?: string | null;
  ewb_number?: string | null;
  status?: string | null;
}

export interface ComplianceSummary {
  irn: string | null;
  ewayBill: string | null;
}

/** Match e-invoice / e-way records to this invoice (generation itself is out of scope). */
export function complianceSummary(
  invoiceId: string,
  einvoiceRecords: ComplianceRecord[],
  ewayRecords: ComplianceRecord[],
): ComplianceSummary {
  const irnRec = einvoiceRecords.find((r) => r.sales_invoice_id === invoiceId && r.irn);
  const ewbRec = ewayRecords.find((r) => r.sales_invoice_id === invoiceId && r.ewb_number);
  return { irn: irnRec?.irn ?? null, ewayBill: ewbRec?.ewb_number ?? null };
}

// ── Activity timeline assembly ────────────────────────────────────────────────
export interface TimelineItem {
  at: string;            // ISO timestamp
  title: string;
  detail?: string;
  kind: "lifecycle" | "delivery" | "compliance";
}

interface RawTimelineEvent {
  entity_id?: string | null;
  entity_type?: string | null;
  title?: string | null;
  description?: string | null;
  event_type?: string | null;
  created_at?: string | null;
}

/**
 * Merge the invoice's lifecycle events (client timeline, filtered to this invoice)
 * with its delivery attempts into one newest-first activity feed.
 */
export function buildActivity(
  invoiceId: string,
  events: RawTimelineEvent[],
  deliveries: InvoiceDelivery[],
  extra: TimelineItem[] = [],
): TimelineItem[] {
  const lifecycle: TimelineItem[] = events
    .filter((e) => e.entity_type === "sales_invoice" && e.entity_id === invoiceId)
    .map((e) => ({
      at: e.created_at ?? "",
      title: e.title ?? e.event_type ?? "Activity",
      detail: e.description ?? undefined,
      kind: "lifecycle" as const,
    }));

  const delivery: TimelineItem[] = deliveries.map((d) => ({
    at: d.sent_at ?? d.created_at,
    title: d.status === "sent" ? "Emailed to customer" : `Email ${d.status}`,
    detail: d.sent_to,
    kind: "delivery" as const,
  }));

  // `extra` carries pre-built items from other sources (e.g. compliance records
  // derived by lib/invoices/compliance) so the Hub feed is one merged stream.
  return [...lifecycle, ...delivery, ...extra]
    .filter((i) => i.at)
    .sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0)); // newest first
}
