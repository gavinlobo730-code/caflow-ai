"use client";

/**
 * Create Purchase Bill route — mirrors sales/invoices/new/page.tsx. Loads
 * editor context (vendors + expense accounts + the buying client's own GST
 * state), then renders PurchaseBillEditor, which owns the workspace layout,
 * toolbar, summary and dirty guard.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { PurchaseBillEditor } from "@/components/purchases/PurchaseBillEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import { loadPurchaseBillEditorContext, type PurchaseBillEditorContext } from "@/lib/purchases/editorContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

export default function NewPurchaseBillPage() {
  // See sales/invoices/new/page.tsx's identical comment: useParams() never
  // resolves under Cloudflare's static-export placeholder routing — read the
  // client id from ClientNavContext instead.
  const { clientId } = useClientNav();
  const router = useRouter();
  const [ctx, setCtx] = useState<PurchaseBillEditorContext | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setError(false);
    loadPurchaseBillEditorContext(clientId)
      .then((c) => { if (!cancelled) setCtx(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [clientId, reloadKey]);

  if (ctx && ctx.vendors.length > 0) {
    return (
      <PurchaseBillEditor
        clientId={clientId}
        clientName={ctx.clientName}
        clientStateCode={ctx.clientStateCode}
        vendors={ctx.vendors}
        accounts={ctx.accounts}
        onDone={(msg) => router.push(`/clients/${clientId}/purchases?flash=${encodeURIComponent(msg)}`)}
        onCancel={() => router.push(`/clients/${clientId}/purchases`)}
      />
    );
  }

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: ctx?.clientName || "Client", href: `/clients/${clientId}` },
        { label: "Purchases", href: `/clients/${clientId}/purchases` },
        { label: "New Purchase Bill" },
      ]}
      title="New Purchase Bill"
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
          description="Add a vendor before creating a purchase bill."
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
