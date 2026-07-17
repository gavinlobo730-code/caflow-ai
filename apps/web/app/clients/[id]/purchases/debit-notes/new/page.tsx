"use client";

/**
 * Create Purchase Debit Note route — mirrors purchases/bills/new/page.tsx.
 * Loads editor context (active vendors), then renders DebitNoteEditor, which
 * owns the workspace layout, toolbar, summary and dirty guard.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { DebitNoteEditor, type DebitNoteDetail } from "@/components/purchases/DebitNoteEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import { loadDebitNoteEditorContext, type DebitNoteEditorContext } from "@/lib/purchases/debitNoteEditorContext";
import { readAndClearDebitNoteDuplicateSeed } from "@/lib/purchases/debitNoteDuplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

export default function NewDebitNotePage() {
  const { clientId } = useClientNav();
  const router = useRouter();
  const [ctx, setCtx] = useState<DebitNoteEditorContext | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const seedRef = useRef<DebitNoteDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearDebitNoteDuplicateSeed();
  const duplicateSeed = seedRef.current;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setError(false);
    loadDebitNoteEditorContext(clientId)
      .then((c) => { if (!cancelled) setCtx(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [clientId, reloadKey]);

  if (ctx && ctx.vendors.length > 0) {
    return (
      <DebitNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        vendors={ctx.vendors}
        duplicateSeed={duplicateSeed}
        onDone={(msg) => router.push(`/clients/${clientId}/purchases?tab=debit-notes&flash=${encodeURIComponent(msg)}`)}
        onCancel={() => router.push(`/clients/${clientId}/purchases?tab=debit-notes`)}
      />
    );
  }

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: ctx?.clientName || "Client", href: `/clients/${clientId}` },
        { label: "Purchases", href: `/clients/${clientId}/purchases?tab=debit-notes` },
        { label: "New Debit Note" },
      ]}
      title="New Debit Note"
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      toolbar={!error && !ctx ? <InvoiceToolbarSkeleton /> : undefined}
      summary={!error && !ctx ? <SummaryPanelSkeleton /> : undefined}
    >
      {error ? (
        <ErrorState message="Couldn't load vendors for this client." onRetry={() => setReloadKey((k) => k + 1)} />
      ) : !ctx ? (
        <InvoiceEditorSkeleton />
      ) : (
        <EmptyState
          title="No vendors yet"
          description="Add a vendor before creating a debit note."
          action={
            <button onClick={() => router.push(`/clients/${clientId}/purchases?tab=vendors`)} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Purchases
            </button>
          }
        />
      )}
    </InvoiceWorkspaceLayout>
  );
}
