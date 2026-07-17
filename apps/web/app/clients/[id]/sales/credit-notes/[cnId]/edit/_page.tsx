"use client";

/**
 * Edit Sales Credit Note — client view. Mirrors sales/debit-notes/[sdnId]/
 * edit/_page.tsx (same static-export id resolution, same loading/error
 * skeleton shell).
 */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { SalesCreditNoteEditor, type SalesCreditNoteDetail } from "@/components/sales/SalesCreditNoteEditor";
import { ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadSalesCreditNoteEditorContext, loadSalesCreditNoteDetail, type SalesCreditNoteEditorContext,
} from "@/lib/sales/salesCreditNoteEditorContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getCnIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/sales\/credit-notes\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function EditSalesCreditNotePageClient() {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [cnId, setCnId] = useState<string>(() => getCnIdFromLocation());
  useEffect(() => { setCnId(getCnIdFromLocation()); }, [pathname]);
  const router = useRouter();
  const [ctx, setCtx] = useState<SalesCreditNoteEditorContext | null>(null);
  const [note, setNote] = useState<SalesCreditNoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !cnId || cnId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setNote(null); setError(null);
    Promise.all([loadSalesCreditNoteEditorContext(clientId), loadSalesCreditNoteDetail(cnId)])
      .then(([c, n]) => {
        if (cancelled) return;
        if (!n) { setError("Credit note not found."); return; }
        setCtx(c); setNote(n);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the credit note."); });
    return () => { cancelled = true; };
  }, [clientId, cnId, reloadKey]);

  if (ctx && note) {
    return (
      <SalesCreditNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        customers={ctx.customers}
        existing={note}
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
