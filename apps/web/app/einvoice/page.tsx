"use client";

/**
 * The firm-level e-invoice screen: which invoices still need an IRN, and the IRN
 * records prepared for one client.
 *
 * IT DOES NOT PREPARE A RECORD OR RECORD AN IRN (POST-A-065). It used to: a form
 * took an invoice NUMBER and a date for a client whose id the CA pasted into a
 * box, and stored a record with no `sales_invoice_id` and no GST treatment, free
 * of any invoice. The invoice's own compliance panel is the one place that does
 * both, and does them properly: it reads the invoice's treatment, refuses a
 * record that contradicts it, carries the LUT reference and says whether the
 * invoice owes an IRN at all. Two screens writing one record is how they drift, so
 * this one shows the records and sends the CA to the invoice.
 *
 * PREPARE-ONLY. The IRN is obtained on the IRP by a human and recorded afterwards;
 * nothing here generates one or reaches a portal.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Zap } from "lucide-react";
import { api, type EInvoiceRecord } from "@/lib/api";
import { readWindow } from "@/lib/lists/readWindow";
import { windowDescription } from "@/lib/lists/window";
import { ListWindowNotice } from "@/components/lists/ListWindowNotice";
import { MissingIrnPanel } from "@/components/gst/MissingIrnPanel";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TransactionListSkeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";
import { documentTarget } from "@/lib/accounting/sourceDocument";
import { formatDate } from "@/lib/dates/format";
import { describeRecord } from "@/lib/einvoice/recordRow";
import { treatmentLabel } from "@/lib/invoices/compliance";
import { useClientPicker } from "@/lib/workspace/useClientPicker";

/** The window the screen first asks for; "Show more" widens it by the shared step up to the server's ceiling. */
const DEFAULT_WINDOW = 100;

const STATUS_COLOR: Record<string, string> = {
  draft: "bg-ps-muted text-ps-label",
  generated: "bg-state-ready-surface text-state-ready",
  cancelled: "bg-state-problem-surface text-state-problem",
};

/** A treatment code the browser can name, or null: an unknown code is not guessed at. */
function treatmentText(code: string | null | undefined): string | null {
  if (!code) return null;
  return treatmentLabel(code as Parameters<typeof treatmentLabel>[0]) ?? null;
}

export default function EInvoicePage() {
  const { clients, clientId, setClientId } = useClientPicker();
  const [records, setRecords] = useState<EInvoiceRecord[]>([]);
  // The server's window over the client's records: the list stops at a number, and the screen says so.
  const [recordWindow, setWindow] = useState<{ hasMore: boolean; limit: number; maxLimit: number } | null>(null);
  const [limit, setLimit] = useState(DEFAULT_WINDOW);
  const [loading, setLoading] = useState(false);
  // Distinguishes "fetch failed" from "no e-invoice records yet" — a masked
  // failure previously rendered an empty list with no indication of failure.
  const [loadError, setLoadError] = useState<string | null>(null);
  // The client whose records are on screen. `null` means nothing has been
  // loaded yet, which is a different thing from "loaded, and there are none".
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  const load = useCallback(async (cid: string, askedLimit: number, isCurrent: () => boolean) => {
    setLoading(true);
    try {
      const res = await api.einvoice.records(cid, { limit: askedLimit });
      if (!isCurrent()) return;
      const win = res?.success ? readWindow<EInvoiceRecord>(res.data, "records", askedLimit) : null;
      if (win) {
        setRecords(win.rows);
        setWindow({ hasMore: win.hasMore, limit: win.limit, maxLimit: win.maxLimit });
        setLoadError(null);
      } else {
        // A refusal, or a payload that is not a list: said, and never drawn as "no records".
        setRecords([]);
        setWindow(null);
        setLoadError((res?.success ? null : res?.error) ?? "Couldn't load e-invoice records.");
      }
    } catch {
      if (!isCurrent()) return;
      setRecords([]);
      setWindow(null);
      setLoadError("Couldn't load e-invoice records. Please try again.");
    } finally {
      if (isCurrent()) {
        setLoadedFor(cid);
        setLoading(false);
      }
    }
  }, []);

  // Picking a client loads its records; a slower answer for a client the CA has
  // already moved off must not replace the one now on screen.
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!clientId) {
      setRecords([]);
      setWindow(null);
      setLoadError(null);
      setLoadedFor(null);
      return;
    }
    let current = true;
    void load(clientId, limit, () => current);
    return () => { current = false; };
  }, [clientId, attempt, limit, load]);

  return (
    <div className="p-6 max-w-4xl space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-ps-ink">E-Invoice Integration</h2>
        <p className="text-xs text-ps-hint mt-0.5">CGST Act §31B, Rule 48(4) — IRN management</p>
      </div>

      <div className="flex items-center gap-2 bg-state-problem-surface border border-state-problem-border rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-state-problem flex-shrink-0" />
        <p className="text-xs font-medium text-red-800">
          CA REVIEW REQUIRED — Generate IRN on IRP portal (einvoice1.gst.gov.in) first, then record it on the invoice.
          DO NOT AUTO-SUBMIT.
        </p>
      </div>

      {/* GST-20. Across the whole book until a client's records are loaded
          below, then that client's — so the list of what still needs an IRN is
          one click from the client's records. */}
      <MissingIrnPanel clientId={loadedFor} />

      <div className="bg-white border border-ps-border rounded-xl p-4 space-y-2">
        <label className="block text-xs font-medium text-ps-body" htmlFor="einvoice-client">Client</label>
        <div className="max-w-sm">
          <ClientLookup
            id="einvoice-client"
            clients={clients}
            value={clientId}
            // Another client starts again from the default window.
            onChange={(id) => { setLimit(DEFAULT_WINDOW); setClientId(id); }}
            ariaLabel="Client"
            placeholder="Select a client to see its e-invoice records…"
          />
        </div>
        <p className="text-xs text-ps-hint">
          An IRN record is prepared and its IRN recorded on the invoice itself — open the invoice and use its
          compliance panel, where the record takes the invoice&apos;s own GST treatment. This list shows what has
          been recorded.
        </p>
      </div>

      {loading ? (
        <TransactionListSkeleton rows={3} />
      ) : loadError ? (
        <div className="bg-white rounded-xl border border-state-problem-border text-center py-10 space-y-2">
          <p className="text-sm text-red-600 font-medium">{loadError}</p>
          <button onClick={() => setAttempt((n) => n + 1)}
            className="text-xs px-3 py-1 border border-ps-border rounded hover:bg-ps-bg text-ps-body">Retry</button>
        </div>
      ) : loadedFor === null ? (
        <div className="bg-white rounded-xl border border-ps-border text-center py-10">
          <p className="text-xs text-ps-hint">Select a client to see its e-invoice records.</p>
        </div>
      ) : records.length === 0 ? (
        <div className="bg-white rounded-xl border border-ps-border">
          <EmptyState
            className="py-10"
            title="No e-invoice records found"
            description="No IRN record has been prepared for this client yet. Open one of its invoices and prepare the record from the invoice's compliance panel; the IRN itself comes from the portal."
          />
        </div>
      ) : (
        <>
        {recordWindow && (
          <ListWindowNotice
            hasMore={recordWindow.hasMore}
            what={windowDescription(records.length, "e-invoice records", "latest")}
            limit={recordWindow.limit}
            maxLimit={recordWindow.maxLimit}
            onShowMore={setLimit}
            busy={loading}
            elsewhere="Open an invoice to see the records prepared for it."
          />
        )}
        <ul className="space-y-2">
          {records.map((r) => {
            const row = describeRecord(r);
            const target = row.linked && r.sales_invoice_id
              ? documentTarget(r.client_id, { entry_id: "", source_type: "sales_invoice", source_id: r.sales_invoice_id })
              : null;
            const treatment = treatmentText(r.gst_treatment);
            return (
              <li key={r.id} className="bg-white border border-ps-border rounded-xl px-4 py-3 flex items-center gap-3">
                <Zap size={16} className={r.status === "generated" ? "text-green-500" : r.status === "cancelled" ? "text-red-400" : "text-ps-hint"} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-ps-ink">{r.invoice_number} — {formatDate(r.invoice_date)}</p>
                  <p className="text-3xs text-ps-hint">
                    {r.irn ? `IRN: ${r.irn.slice(0, 20)}...` : "No IRN recorded"}
                    {r.ack_number && ` · Ack: ${r.ack_number}`}
                    {treatment && ` · ${treatment}`}
                  </p>
                  <p className={`text-3xs mt-0.5 ${row.linked ? "text-ps-hint" : "text-state-attention"}`}>{row.line}</p>
                </div>
                <span className={`text-3xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_COLOR[r.status] ?? STATUS_COLOR.draft}`}>
                  {r.status}
                </span>
                {target && row.openLabel && (
                  <Link href={target.href} className="text-3xs text-brand hover:underline flex-shrink-0">{row.openLabel}</Link>
                )}
              </li>
            );
          })}
        </ul>
        </>
      )}
    </div>
  );
}
