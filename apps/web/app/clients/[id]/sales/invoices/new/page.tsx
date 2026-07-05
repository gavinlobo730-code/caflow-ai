"use client";

/**
 * Create Invoice route (Batch 2). Hosts the reused <InvoiceForm> inside the workspace
 * shell. The editor's own Save/Cancel actions are unchanged (Save & Issue/Send is a
 * later batch); on save or cancel we return to the Sales list.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { InvoiceForm } from "@/components/invoices/InvoiceForm";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { FormSkeleton } from "@/components/ui/skeleton";
import { loadInvoiceEditorContext, type InvoiceEditorContext } from "@/lib/invoices/editorContext";
import { salesListHref } from "@/lib/invoices/workspaceNav";
import { useUnsavedChanges } from "@/lib/invoices/dirtyState";

export default function NewInvoicePage({ params }: { params: { id: string } }) {
  const clientId = params.id;
  const router = useRouter();
  const [ctx, setCtx] = useState<InvoiceEditorContext | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // Unsaved-changes protection: flip "touched" on the first edit in the form, then
  // warn on tab-close/reload (beforeunload) and confirm on an explicit cancel.
  const [touched, setTouched] = useState(false);
  const { confirmLeave } = useUnsavedChanges(touched);

  useEffect(() => {
    let cancelled = false;
    setCtx(null);
    setError(false);
    loadInvoiceEditorContext(clientId)
      .then((c) => { if (!cancelled) setCtx(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [clientId, reloadKey]);

  const back = () => router.push(salesListHref(clientId));

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[{ label: "Sales", href: salesListHref(clientId) }, { label: "New Invoice" }]}
      title="New Sales Invoice"
      statusPill={
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>
      }
    >
      {error ? (
        <ErrorState message="Couldn't load customers for this client." onRetry={() => setReloadKey((k) => k + 1)} />
      ) : !ctx ? (
        <FormSkeleton fields={6} />
      ) : ctx.customers.length === 0 ? (
        <EmptyState
          title="No customers yet"
          description="Add a customer before creating an invoice."
          action={
            <button onClick={back} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Sales
            </button>
          }
        />
      ) : (
        <div onChangeCapture={() => setTouched(true)}>
          <InvoiceForm
            clientId={clientId}
            clientStateCode={ctx.clientStateCode}
            customers={ctx.customers}
            existing={null}
            onSaved={() => { setTouched(false); back(); }}
            onCancel={() => { if (confirmLeave()) back(); }}
          />
        </div>
      )}
    </InvoiceWorkspaceLayout>
  );
}
