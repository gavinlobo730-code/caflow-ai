"use client";

/**
 * Sales Invoice editor — client view. Handles BOTH create and edit:
 * invoiceId === "new" is the create-mode sentinel (merged from the former
 * standalone sales/invoices/new/page.tsx — see redirect-rule-count budget
 * note in scripts/generate-redirects.js for why: a separate static "new"
 * route sitting alongside this dynamic [invoiceId] route needed its own
 * shadow-splat workaround; folding "new" into this SAME route removes that
 * route/rule entirely). Any other invoiceId value is a real id to edit —
 * drafts get the full editor; issued/partially-paid/paid invoices get the
 * same editor in its locked mode (soft fields only — reference, notes,
 * payment terms, due date, line units; see InvoiceEditor's isLocked). Only
 * cancelled invoices redirect away (the backend rejects every PATCH on them).
 * Mirrors purchases/bills/[billId]/edit/_page.tsx.
 *
 * Ids come from window.location.pathname, NOT useParams(): under `output:
 * export` + Cloudflare's rewrite-to-_placeholder hosting, the App Router's
 * FlightRouterState is permanently anchored to the "_placeholder" build
 * param, so useParams() never resolves to the real ids (see
 * ClientNavContext.tsx's doc comment) — the client id comes from the shared
 * useClientNav() hook (window.location-derived), and invoiceId is read the
 * same way locally since there's no shared context for it.
 */
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { InvoiceEditor } from "@/components/invoices/InvoiceEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadInvoiceEditorContext, loadInvoiceDetail, type InvoiceEditorContext,
} from "@/lib/invoices/editorContext";
import { salesListHref, salesListFlashHref, invoiceBreadcrumbs } from "@/lib/invoices/workspaceNav";
import { type InvoiceDetail } from "@/lib/invoices/shared";
import { readAndClearDuplicateSeed } from "@/lib/invoices/duplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getInvoiceIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/sales\/invoices\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function SalesInvoicePageClient() {
  const { clientId } = useClientNav();
  // usePathname() is only a re-run trigger (its own value is the build-time
  // placeholder segment) — the real id always comes from window.location,
  // mirroring ClientNavContext's clientId pattern.
  const pathname = usePathname();
  const [invoiceId, setInvoiceId] = useState<string>(() => getInvoiceIdFromLocation());
  useEffect(() => { setInvoiceId(getInvoiceIdFromLocation()); }, [pathname]);
  const isNew = invoiceId === "new";
  const router = useRouter();
  const [ctx, setCtx] = useState<InvoiceEditorContext | null>(null);
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // Create-mode-only "duplicate invoice" prefill — read once per mount (see
  // NewInvoicePage's original comment: a guarded ref survives React 18
  // Strict Mode's double-invoke of the lazy initializer in dev).
  const seedRef = useRef<InvoiceDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearDuplicateSeed();
  const duplicateSeed = isNew ? seedRef.current : undefined;

  useEffect(() => {
    // Never query the static-export placeholder ids.
    if (!clientId || clientId === "_placeholder" || !invoiceId || invoiceId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setInvoice(null); setError(null);
    if (isNew) {
      loadInvoiceEditorContext(clientId)
        .then((c) => { if (!cancelled) setCtx(c); })
        .catch(() => { if (!cancelled) setError("Couldn't load customers for this client."); });
      return () => { cancelled = true; };
    }
    Promise.all([loadInvoiceEditorContext(clientId), loadInvoiceDetail(invoiceId)])
      .then(([c, inv]) => {
        if (cancelled) return;
        if (!inv) { setError("Invoice not found."); return; }
        // Cancelled invoices are immutable end-to-end (backend rejects every
        // PATCH) — everything else opens: drafts fully editable, issued/
        // partially-paid/paid in the editor's locked soft-fields-only mode.
        if (inv.status === "cancelled") { router.replace(salesListFlashHref(clientId, "Cancelled invoices cannot be edited.")); return; }
        setCtx(c); setInvoice(inv);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the invoice."); });
    return () => { cancelled = true; };
  }, [clientId, invoiceId, isNew, reloadKey, router]);

  if (ctx && isNew && ctx.customers.length === 0) {
    return (
      <InvoiceWorkspaceLayout
        breadcrumbs={invoiceBreadcrumbs(clientId, ctx.clientName, "New Invoice")}
        title="New Sales Invoice"
        statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      >
        <EmptyState
          title="No customers yet"
          description="Add a customer before creating an invoice."
          action={
            <button onClick={() => router.push(salesListHref(clientId))} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Sales
            </button>
          }
        />
      </InvoiceWorkspaceLayout>
    );
  }

  if (ctx && (isNew || invoice)) {
    return (
      <InvoiceEditor
        clientId={clientId}
        clientName={ctx.clientName}
        clientStateCode={ctx.clientStateCode}
        customers={ctx.customers}
        existing={isNew ? null : invoice}
        duplicateSeed={isNew ? duplicateSeed : undefined}
        onDone={(msg) => router.push(salesListFlashHref(clientId, msg))}
        onCancel={() => router.push(salesListHref(clientId))}
      />
    );
  }

  // See the create-mode branch above: keep the toolbar + summary rail
  // present (as disabled skeletons) while loading so the two-column
  // workspace shell never collapses to a single bare column.
  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={invoiceBreadcrumbs(clientId, ctx?.clientName, isNew ? "New Invoice" : (invoice ? `Edit ${invoice.invoice_no}` : "Edit Invoice"))}
      title={isNew ? "New Sales Invoice" : (invoice ? `Edit ${invoice.invoice_no}` : "Edit Invoice")}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">{isNew ? "Draft" : (invoice ? invoice.status.replace("_", " ") : "…")}</span>}
      toolbar={!error ? <InvoiceToolbarSkeleton /> : undefined}
      summary={!error ? <SummaryPanelSkeleton /> : undefined}
    >
      {error ? (
        <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />
      ) : (
        <InvoiceEditorSkeleton />
      )}
    </InvoiceWorkspaceLayout>
  );
}
