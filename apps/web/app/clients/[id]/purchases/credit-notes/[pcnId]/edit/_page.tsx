"use client";

/**
 * Purchase Credit Note editor — client view. Handles BOTH create and edit:
 * pcnId === "new" is the create-mode sentinel (merged from the former
 * standalone purchases/credit-notes/new/page.tsx — see redirect-rule-count
 * budget note in scripts/generate-redirects.js for why). Any other pcnId
 * value is a real id to edit. Mirrors purchases/debit-notes/[dnId]/edit/
 * _page.tsx (same merge, same shape).
 */
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { PurchaseCreditNoteEditor, type PurchaseCreditNoteDetail } from "@/components/purchases/PurchaseCreditNoteEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadPurchaseCreditNoteEditorContext, loadPurchaseCreditNoteDetail, type PurchaseCreditNoteEditorContext,
} from "@/lib/purchases/purchaseCreditNoteEditorContext";
import { readAndClearPurchaseCreditNoteDuplicateSeed } from "@/lib/purchases/purchaseCreditNoteDuplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getPcnIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/purchases\/credit-notes\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function PurchaseCreditNotePageClient() {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [pcnId, setPcnId] = useState<string>(() => getPcnIdFromLocation());
  useEffect(() => { setPcnId(getPcnIdFromLocation()); }, [pathname]);
  const isNew = pcnId === "new";
  const router = useRouter();
  const [ctx, setCtx] = useState<PurchaseCreditNoteEditorContext | null>(null);
  const [note, setNote] = useState<PurchaseCreditNoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const seedRef = useRef<PurchaseCreditNoteDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearPurchaseCreditNoteDuplicateSeed();
  const duplicateSeed = isNew ? seedRef.current : undefined;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !pcnId || pcnId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setNote(null); setError(null);
    if (isNew) {
      loadPurchaseCreditNoteEditorContext(clientId)
        .then((c) => { if (!cancelled) setCtx(c); })
        .catch(() => { if (!cancelled) setError("Couldn't load vendors for this client."); });
      return () => { cancelled = true; };
    }
    Promise.all([loadPurchaseCreditNoteEditorContext(clientId), loadPurchaseCreditNoteDetail(pcnId)])
      .then(([c, n]) => {
        if (cancelled) return;
        if (!n) { setError("Credit note not found."); return; }
        setCtx(c); setNote(n);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the credit note."); });
    return () => { cancelled = true; };
  }, [clientId, pcnId, isNew, reloadKey]);

  if (ctx && isNew && ctx.vendors.length === 0) {
    return (
      <InvoiceWorkspaceLayout
        breadcrumbs={[
          { label: ctx.clientName || "Client", href: `/clients/${clientId}` },
          { label: "Purchases", href: `/clients/${clientId}/purchases?tab=credit-notes` },
          { label: "New Credit Note" },
        ]}
        title="New Credit Note"
        statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      >
        <EmptyState
          title="No vendors yet"
          description="Add a vendor before creating a credit note."
          action={
            <button onClick={() => router.push(`/clients/${clientId}/purchases?tab=vendors`)} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Purchases
            </button>
          }
        />
      </InvoiceWorkspaceLayout>
    );
  }

  if (ctx && (isNew || note)) {
    return (
      <PurchaseCreditNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        vendors={ctx.vendors}
        existing={isNew ? undefined : note}
        duplicateSeed={isNew ? duplicateSeed : undefined}
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
        { label: isNew ? "New Credit Note" : (note ? `Edit ${note.credit_note_no}` : "Edit Credit Note") },
      ]}
      title={isNew ? "New Credit Note" : (note ? `Edit ${note.credit_note_no}` : "Edit Credit Note")}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">{isNew ? "Draft" : (note ? note.status : "…")}</span>}
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
