"use client";

/**
 * Edit Draft Invoice route (Batch 3). Loads editor context + the invoice detail, then
 * renders InvoiceEditor. Only drafts are editable — anything else redirects to the
 * Sales list. Loading/error render inside the workspace shell for continuity.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { InvoiceEditor } from "@/components/invoices/InvoiceEditor";
import { ErrorState } from "@/components/ui/states";
import { FormSkeleton } from "@/components/ui/skeleton";
import {
  loadInvoiceEditorContext, loadInvoiceDetail, type InvoiceEditorContext,
} from "@/lib/invoices/editorContext";
import { salesListHref, salesListFlashHref, invoiceBreadcrumbs } from "@/lib/invoices/workspaceNav";
import { type InvoiceDetail } from "@/lib/invoices/shared";

export default function EditInvoicePage({ params }: { params: { id: string; invoiceId: string } }) {
  const clientId = params.id;
  const invoiceId = params.invoiceId;
  const router = useRouter();
  const [ctx, setCtx] = useState<InvoiceEditorContext | null>(null);
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
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

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={invoiceBreadcrumbs(clientId, ctx?.clientName, invoice ? `Edit ${invoice.invoice_no}` : "Edit Invoice")}
      title={invoice ? `Edit ${invoice.invoice_no}` : "Edit Draft Invoice"}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
    >
      {error ? (
        <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />
      ) : (
        <FormSkeleton fields={6} />
      )}
    </InvoiceWorkspaceLayout>
  );
}
