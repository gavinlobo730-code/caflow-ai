"use client";

/**
 * Sales Debit Note editor — client view. Handles BOTH create and edit:
 * sdnId === "new" is the create-mode sentinel (merged from the former
 * standalone sales/debit-notes/new/page.tsx — see redirect-rule-count
 * budget note in scripts/generate-redirects.js for why). Any other sdnId
 * value is a real id to edit. Mirrors sales/credit-notes/[cnId]/edit/
 * _page.tsx (same merge, same shape).
 */
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { SalesDebitNoteEditor, type SalesDebitNoteDetail } from "@/components/sales/SalesDebitNoteEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadSalesDebitNoteEditorContext, loadSalesDebitNoteDetail, type SalesDebitNoteEditorContext,
} from "@/lib/sales/salesDebitNoteEditorContext";
import { readAndClearSalesDebitNoteDuplicateSeed } from "@/lib/sales/salesDebitNoteDuplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getSdnIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/sales\/debit-notes\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function SalesDebitNotePageClient() {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [sdnId, setSdnId] = useState<string>(() => getSdnIdFromLocation());
  useEffect(() => { setSdnId(getSdnIdFromLocation()); }, [pathname]);
  const isNew = sdnId === "new";
  const router = useRouter();
  const [ctx, setCtx] = useState<SalesDebitNoteEditorContext | null>(null);
  const [note, setNote] = useState<SalesDebitNoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const seedRef = useRef<SalesDebitNoteDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearSalesDebitNoteDuplicateSeed();
  const duplicateSeed = isNew ? seedRef.current : undefined;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !sdnId || sdnId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setNote(null); setError(null);
    if (isNew) {
      loadSalesDebitNoteEditorContext(clientId)
        .then((c) => { if (!cancelled) setCtx(c); })
        .catch(() => { if (!cancelled) setError("Couldn't load customers for this client."); });
      return () => { cancelled = true; };
    }
    Promise.all([loadSalesDebitNoteEditorContext(clientId), loadSalesDebitNoteDetail(sdnId)])
      .then(([c, n]) => {
        if (cancelled) return;
        if (!n) { setError("Debit note not found."); return; }
        setCtx(c); setNote(n);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the debit note."); });
    return () => { cancelled = true; };
  }, [clientId, sdnId, isNew, reloadKey]);

  if (ctx && isNew && ctx.customers.length === 0) {
    return (
      <InvoiceWorkspaceLayout
        breadcrumbs={[
          { label: ctx.clientName || "Client", href: `/clients/${clientId}` },
          { label: "Sales", href: `/clients/${clientId}/sales?tab=debit-notes` },
          { label: "New Debit Note" },
        ]}
        title="New Debit Note"
        statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      >
        <EmptyState
          title="No customers yet"
          description="Add a customer before creating a debit note."
          action={
            <button onClick={() => router.push(`/clients/${clientId}/sales?tab=customers`)} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Sales
            </button>
          }
        />
      </InvoiceWorkspaceLayout>
    );
  }

  if (ctx && (isNew || note)) {
    return (
      <SalesDebitNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        customers={ctx.customers}
        existing={isNew ? undefined : note}
        duplicateSeed={isNew ? duplicateSeed : undefined}
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
        { label: isNew ? "New Debit Note" : (note ? `Edit ${note.debit_note_no}` : "Edit Debit Note") },
      ]}
      title={isNew ? "New Debit Note" : (note ? `Edit ${note.debit_note_no}` : "Edit Debit Note")}
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
