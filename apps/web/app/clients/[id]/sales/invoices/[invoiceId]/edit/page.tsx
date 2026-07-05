"use client";

/**
 * Edit Draft Invoice route (Batch 2). Loads the invoice detail + editor context and
 * reuses <InvoiceForm>. Only drafts are editable — a non-draft invoice redirects to
 * the Sales list (where the View drawer/Hub shows it). Save/cancel return to the list.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { InvoiceForm } from "@/components/invoices/InvoiceForm";
import { ErrorState } from "@/components/ui/states";
import { FormSkeleton } from "@/components/ui/skeleton";
import {
  loadInvoiceEditorContext, loadInvoiceDetail, type InvoiceEditorContext,
} from "@/lib/invoices/editorContext";
import { salesListHref } from "@/lib/invoices/workspaceNav";
import { useUnsavedChanges } from "@/lib/invoices/dirtyState";
import { STATUS_BADGE, type InvoiceDetail } from "@/lib/invoices/shared";

export default function EditInvoicePage({ params }: { params: { id: string; invoiceId: string } }) {
  const clientId = params.id;
  const invoiceId = params.invoiceId;
  const router = useRouter();
  const [touched, setTouched] = useState(false);
  const { confirmLeave } = useUnsavedChanges(touched);
  const [ctx, setCtx] = useState<InvoiceEditorContext | null>(null);
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setCtx(null);
    setInvoice(null);
    setError(null);
    Promise.all([loadInvoiceEditorContext(clientId), loadInvoiceDetail(invoiceId)])
      .then(([c, inv]) => {
        if (cancelled) return;
        if (!inv) { setError("Invoice not found."); return; }
        // Only drafts are editable — send anything else back to the list/hub.
        if (inv.status !== "draft") { router.replace(salesListHref(clientId)); return; }
        setCtx(c);
        setInvoice(inv);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the invoice."); });
    return () => { cancelled = true; };
  }, [clientId, invoiceId, reloadKey, router]);

  const back = () => router.push(salesListHref(clientId));

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: "Sales", href: salesListHref(clientId) },
        { label: invoice ? `Edit ${invoice.invoice_no}` : "Edit Invoice" },
      ]}
      title={invoice ? `Edit ${invoice.invoice_no}` : "Edit Draft Invoice"}
      statusPill={
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE.draft}`}>Draft</span>
      }
    >
      {error ? (
        <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />
      ) : !ctx || !invoice ? (
        <FormSkeleton fields={6} />
      ) : (
        <div onChangeCapture={() => setTouched(true)}>
          <InvoiceForm
            clientId={clientId}
            clientStateCode={ctx.clientStateCode}
            customers={ctx.customers}
            existing={invoice}
            onSaved={() => { setTouched(false); back(); }}
            onCancel={() => { if (confirmLeave()) back(); }}
          />
        </div>
      )}
    </InvoiceWorkspaceLayout>
  );
}
