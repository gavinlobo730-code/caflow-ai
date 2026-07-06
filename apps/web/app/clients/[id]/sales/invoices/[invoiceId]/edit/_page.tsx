"use client";

/**
 * Edit Draft Invoice — client view (Batch 3). Only drafts are editable —
 * anything else redirects to the Sales list.
 *
 * Ids come from window.location.pathname, NOT useParams(): under `output:
 * export` + Cloudflare's rewrite-to-_placeholder hosting, the App Router's
 * FlightRouterState is permanently anchored to the "_placeholder" build
 * param, so useParams() never resolves to the real ids (see
 * ClientNavContext.tsx's doc comment) — the client id comes from the shared
 * useClientNav() hook (window.location-derived), and invoiceId is read the
 * same way locally since there's no shared context for it.
 */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { InvoiceEditor } from "@/components/invoices/InvoiceEditor";
import { ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadInvoiceEditorContext, loadInvoiceDetail, type InvoiceEditorContext,
} from "@/lib/invoices/editorContext";
import { salesListHref, salesListFlashHref, invoiceBreadcrumbs } from "@/lib/invoices/workspaceNav";
import { type InvoiceDetail } from "@/lib/invoices/shared";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getInvoiceIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/sales\/invoices\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function EditInvoicePageClient() {
  const { clientId } = useClientNav();
  // usePathname() is only a re-run trigger (its own value is the build-time
  // placeholder segment) — the real id always comes from window.location,
  // mirroring ClientNavContext's clientId pattern.
  const pathname = usePathname();
  const [invoiceId, setInvoiceId] = useState<string>(() => getInvoiceIdFromLocation());
  useEffect(() => { setInvoiceId(getInvoiceIdFromLocation()); }, [pathname]);
  const router = useRouter();
  const [ctx, setCtx] = useState<InvoiceEditorContext | null>(null);
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    // Never query the static-export placeholder ids.
    if (!clientId || clientId === "_placeholder" || !invoiceId || invoiceId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setInvoice(null); setError(null);
    Promise.all([loadInvoiceEditorContext(clientId), loadInvoiceDetail(invoiceId)])
      .then(([c, inv]) => {
        if (cancelled) return;
        if (!inv) { setError("Invoice not found."); return; }
        if (inv.status !== "draft") { router.replace(salesListHref(clientId)); return; }
        setCtx(c); setInvoice(inv);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the invoice."); });
    return () => { cancelled = true; };
  }, [clientId, invoiceId, reloadKey, router]);

  if (ctx && invoice) {
    return (
      <InvoiceEditor
        clientId={clientId}
        clientName={ctx.clientName}
        clientStateCode={ctx.clientStateCode}
        customers={ctx.customers}
        existing={invoice}
        onDone={(msg) => router.push(salesListFlashHref(clientId, msg))}
        onCancel={() => router.push(salesListHref(clientId))}
      />
    );
  }

  // See NewInvoicePage: keep the toolbar + summary rail present (as disabled
  // skeletons) while loading so the two-column shell never collapses.
  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={invoiceBreadcrumbs(clientId, ctx?.clientName, invoice ? `Edit ${invoice.invoice_no}` : "Edit Invoice")}
      title={invoice ? `Edit ${invoice.invoice_no}` : "Edit Draft Invoice"}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
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
