"use client";

/**
 * Create Sales Debit Note route — mirrors purchases/debit-notes/new/page.tsx.
 * Loads editor context (active customers), then renders SalesDebitNoteEditor,
 * which owns the workspace layout, toolbar, summary and dirty guard.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { SalesDebitNoteEditor, type SalesDebitNoteDetail } from "@/components/sales/SalesDebitNoteEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import { loadSalesDebitNoteEditorContext, type SalesDebitNoteEditorContext } from "@/lib/sales/salesDebitNoteEditorContext";
import { readAndClearSalesDebitNoteDuplicateSeed } from "@/lib/sales/salesDebitNoteDuplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

export default function NewSalesDebitNotePage() {
  const { clientId } = useClientNav();
  const router = useRouter();
  const [ctx, setCtx] = useState<SalesDebitNoteEditorContext | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const seedRef = useRef<SalesDebitNoteDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearSalesDebitNoteDuplicateSeed();
  const duplicateSeed = seedRef.current;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setError(false);
    loadSalesDebitNoteEditorContext(clientId)
      .then((c) => { if (!cancelled) setCtx(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [clientId, reloadKey]);

  if (ctx && ctx.customers.length > 0) {
    return (
      <SalesDebitNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        customers={ctx.customers}
        duplicateSeed={duplicateSeed}
        onDone={(msg) => router.push(`/clients/${clientId}/sales?tab=debit-notes&flash=${encodeURIComponent(msg)}`)}
        onCancel={() => router.push(`/clients/${clientId}/sales?tab=debit-notes`)}
      />
    );
  }

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: ctx?.clientName || "Client", href: `/clients/${clientId}` },
        { label: "Sales", href: `/clients/${clientId}/sales?tab=debit-notes` },
        { label: "New Debit Note" },
      ]}
      title="New Debit Note"
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
          description="Add a customer before creating a debit note."
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
