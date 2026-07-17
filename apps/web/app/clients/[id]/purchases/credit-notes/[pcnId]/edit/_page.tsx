"use client";

/**
 * Edit Purchase Credit Note — client view. Mirrors purchases/debit-notes/
 * [dnId]/edit/_page.tsx (same static-export id resolution, same loading/
 * error skeleton shell).
 */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { PurchaseCreditNoteEditor, type PurchaseCreditNoteDetail } from "@/components/purchases/PurchaseCreditNoteEditor";
import { ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadPurchaseCreditNoteEditorContext, loadPurchaseCreditNoteDetail, type PurchaseCreditNoteEditorContext,
} from "@/lib/purchases/purchaseCreditNoteEditorContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getPcnIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/purchases\/credit-notes\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function EditPurchaseCreditNotePageClient() {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [pcnId, setPcnId] = useState<string>(() => getPcnIdFromLocation());
  useEffect(() => { setPcnId(getPcnIdFromLocation()); }, [pathname]);
  const router = useRouter();
  const [ctx, setCtx] = useState<PurchaseCreditNoteEditorContext | null>(null);
  const [note, setNote] = useState<PurchaseCreditNoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !pcnId || pcnId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setNote(null); setError(null);
    Promise.all([loadPurchaseCreditNoteEditorContext(clientId), loadPurchaseCreditNoteDetail(pcnId)])
      .then(([c, n]) => {
        if (cancelled) return;
        if (!n) { setError("Credit note not found."); return; }
        setCtx(c); setNote(n);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the credit note."); });
    return () => { cancelled = true; };
  }, [clientId, pcnId, reloadKey]);

  if (ctx && note) {
    return (
      <PurchaseCreditNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        vendors={ctx.vendors}
        existing={note}
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
        { label: note ? `Edit ${note.credit_note_no}` : "Edit Credit Note" },
      ]}
      title={note ? `Edit ${note.credit_note_no}` : "Edit Credit Note"}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">{note ? note.status : "…"}</span>}
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
