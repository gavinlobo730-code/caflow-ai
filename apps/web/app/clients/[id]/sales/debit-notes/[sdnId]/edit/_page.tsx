"use client";

/**
 * Edit Sales Debit Note — client view. Mirrors purchases/debit-notes/
 * [dnId]/edit/_page.tsx (same static-export id resolution, same loading/
 * error skeleton shell).
 */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { SalesDebitNoteEditor, type SalesDebitNoteDetail } from "@/components/sales/SalesDebitNoteEditor";
import { ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadSalesDebitNoteEditorContext, loadSalesDebitNoteDetail, type SalesDebitNoteEditorContext,
} from "@/lib/sales/salesDebitNoteEditorContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getSdnIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/sales\/debit-notes\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function EditSalesDebitNotePageClient() {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [sdnId, setSdnId] = useState<string>(() => getSdnIdFromLocation());
  useEffect(() => { setSdnId(getSdnIdFromLocation()); }, [pathname]);
  const router = useRouter();
  const [ctx, setCtx] = useState<SalesDebitNoteEditorContext | null>(null);
  const [note, setNote] = useState<SalesDebitNoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !sdnId || sdnId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setNote(null); setError(null);
    Promise.all([loadSalesDebitNoteEditorContext(clientId), loadSalesDebitNoteDetail(sdnId)])
      .then(([c, n]) => {
        if (cancelled) return;
        if (!n) { setError("Debit note not found."); return; }
        setCtx(c); setNote(n);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the debit note."); });
    return () => { cancelled = true; };
  }, [clientId, sdnId, reloadKey]);

  if (ctx && note) {
    return (
      <SalesDebitNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        customers={ctx.customers}
        existing={note}
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
        { label: note ? `Edit ${note.debit_note_no}` : "Edit Debit Note" },
      ]}
      title={note ? `Edit ${note.debit_note_no}` : "Edit Debit Note"}
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
