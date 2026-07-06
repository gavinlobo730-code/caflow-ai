"use client";

/**
 * Create Invoice route (Batch 3). Loads editor context, then renders the new
 * InvoiceEditor (which owns the workspace layout, toolbar, summary and dirty guard).
 * Loading/empty/error render inside the same workspace shell for continuity.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { InvoiceEditor } from "@/components/invoices/InvoiceEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { FormSkeleton } from "@/components/ui/skeleton";
import { loadInvoiceEditorContext, type InvoiceEditorContext } from "@/lib/invoices/editorContext";
import { salesListHref, salesListFlashHref, invoiceBreadcrumbs } from "@/lib/invoices/workspaceNav";

export default function NewInvoicePage({ params }: { params: { id: string } }) {
  const clientId = params.id;
  const router = useRouter();
  const [ctx, setCtx] = useState<InvoiceEditorContext | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setCtx(null); setError(false);
    loadInvoiceEditorContext(clientId)
      .then((c) => { if (!cancelled) setCtx(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [clientId, reloadKey]);

  if (ctx && ctx.customers.length > 0) {
    return (
      <InvoiceEditor
        clientId={clientId}
        clientName={ctx.clientName}
        clientStateCode={ctx.clientStateCode}
        customers={ctx.customers}
        existing={null}
        onDone={(msg) => router.push(salesListFlashHref(clientId, msg))}
        onCancel={() => router.push(salesListHref(clientId))}
      />
    );
  }

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={invoiceBreadcrumbs(clientId, ctx?.clientName, "New Invoice")}
      title="New Sales Invoice"
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
    >
      {error ? (
        <ErrorState message="Couldn't load customers for this client." onRetry={() => setReloadKey((k) => k + 1)} />
      ) : !ctx ? (
        <FormSkeleton fields={6} />
      ) : (
        <EmptyState
          title="No customers yet"
          description="Add a customer before creating an invoice."
          action={
            <button onClick={() => router.push(salesListHref(clientId))} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Sales
            </button>
          }
        />
      )}
    </InvoiceWorkspaceLayout>
  );
}
