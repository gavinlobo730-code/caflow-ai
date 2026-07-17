"use client";

/**
 * Create Purchase Credit Note route — mirrors purchases/debit-notes/new/page.tsx.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { PurchaseCreditNoteEditor, type PurchaseCreditNoteDetail } from "@/components/purchases/PurchaseCreditNoteEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import { loadPurchaseCreditNoteEditorContext, type PurchaseCreditNoteEditorContext } from "@/lib/purchases/purchaseCreditNoteEditorContext";
import { readAndClearPurchaseCreditNoteDuplicateSeed } from "@/lib/purchases/purchaseCreditNoteDuplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

export default function NewPurchaseCreditNotePage() {
  const { clientId } = useClientNav();
  const router = useRouter();
  const [ctx, setCtx] = useState<PurchaseCreditNoteEditorContext | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const seedRef = useRef<PurchaseCreditNoteDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearPurchaseCreditNoteDuplicateSeed();
  const duplicateSeed = seedRef.current;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setError(false);
    loadPurchaseCreditNoteEditorContext(clientId)
      .then((c) => { if (!cancelled) setCtx(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [clientId, reloadKey]);

  if (ctx && ctx.vendors.length > 0) {
    return (
      <PurchaseCreditNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        vendors={ctx.vendors}
        duplicateSeed={duplicateSeed}
        onDone={(msg) => router.push(`/clients/${clientId}/purchases?tab=credit-notes&flash=${encodeURIComponent(msg)}`)}
        onCancel={() => router.push(`/clients/${clientId}/purchases?tab=credit-notes`)}
      />
    );
  }

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: ctx?.clientName || "Client", href: `/clients/${clientId}` },
        { label: "Purchases", href: `/clients/${clientId}/purchases?tab=credit-notes` },
        { label: "New Credit Note" },
      ]}
      title="New Credit Note"
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
          description="Add a vendor before creating a credit note."
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
