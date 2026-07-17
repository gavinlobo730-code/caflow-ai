"use client";

/**
 * Create Sales Credit Note route — mirrors sales/debit-notes/new/page.tsx.
 * Loads editor context (active customers), then renders SalesCreditNoteEditor,
 * which owns the workspace layout, toolbar, summary and dirty guard.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { SalesCreditNoteEditor, type SalesCreditNoteDetail } from "@/components/sales/SalesCreditNoteEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import { loadSalesCreditNoteEditorContext, type SalesCreditNoteEditorContext } from "@/lib/sales/salesCreditNoteEditorContext";
import { readAndClearSalesCreditNoteDuplicateSeed } from "@/lib/sales/salesCreditNoteDuplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

export default function NewSalesCreditNotePage() {
  const { clientId } = useClientNav();
  const router = useRouter();
  const [ctx, setCtx] = useState<SalesCreditNoteEditorContext | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const seedRef = useRef<SalesCreditNoteDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearSalesCreditNoteDuplicateSeed();
  const duplicateSeed = seedRef.current;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setError(false);
    loadSalesCreditNoteEditorContext(clientId)
      .then((c) => { if (!cancelled) setCtx(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [clientId, reloadKey]);

  if (ctx && ctx.customers.length > 0) {
    return (
      <SalesCreditNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        customers={ctx.customers}
        duplicateSeed={duplicateSeed}
        onDone={(msg) => router.push(`/clients/${clientId}/sales?tab=credit-notes&flash=${encodeURIComponent(msg)}`)}
        onCancel={() => router.push(`/clients/${clientId}/sales?tab=credit-notes`)}
      />
    );
  }

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: ctx?.clientName || "Client", href: `/clients/${clientId}` },
        { label: "Sales", href: `/clients/${clientId}/sales?tab=credit-notes` },
        { label: "New Credit Note" },
      ]}
      title="New Credit Note"
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      toolbar={!error && !ctx ? <InvoiceToolbarSkeleton /> : undefined}
      summary={!error && !ctx ? <SummaryPanelSkeleton /> : undefined}
    >
      {error ? (
        <ErrorState message="Couldn't load customers for this client." onRetry={() => setReloadKey((k) => k + 1)} />
      ) : !ctx ? (
        <InvoiceEditorSkeleton />
      ) : (
        <EmptyState
          title="No customers yet"
          description="Add a customer before creating a credit note."
          action={
            <button onClick={() => router.push(`/clients/${clientId}/sales?tab=customers`)} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Sales
            </button>
          }
        />
      )}
    </InvoiceWorkspaceLayout>
  );
}
