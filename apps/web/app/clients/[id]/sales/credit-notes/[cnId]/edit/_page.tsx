"use client";

/**
 * Sales Credit Note editor — client view. Handles BOTH create and edit:
 * cnId === "new" is the create-mode sentinel (merged from the former
 * standalone sales/credit-notes/new/page.tsx — see redirect-rule-count
 * budget note in scripts/generate-redirects.js for why: a separate static
 * "new" route sitting alongside this dynamic [cnId] route needed its own
 * shadow-splat workaround; folding "new" into this SAME route removes that
 * route/rule entirely). Any other cnId value is a real id to edit.
 * Mirrors sales/debit-notes/[sdnId]/edit/_page.tsx (same merge, same shape).
 */
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { SalesCreditNoteEditor, type SalesCreditNoteDetail } from "@/components/sales/SalesCreditNoteEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadSalesCreditNoteEditorContext, loadSalesCreditNoteDetail, type SalesCreditNoteEditorContext,
} from "@/lib/sales/salesCreditNoteEditorContext";
import { readAndClearSalesCreditNoteDuplicateSeed } from "@/lib/sales/salesCreditNoteDuplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getCnIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/sales\/credit-notes\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function SalesCreditNotePageClient() {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [cnId, setCnId] = useState<string>(() => getCnIdFromLocation());
  useEffect(() => { setCnId(getCnIdFromLocation()); }, [pathname]);
  const isNew = cnId === "new";
  const router = useRouter();
  const [ctx, setCtx] = useState<SalesCreditNoteEditorContext | null>(null);
  const [note, setNote] = useState<SalesCreditNoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // Create-mode-only "duplicate credit note" prefill — read once per mount.
  const seedRef = useRef<SalesCreditNoteDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearSalesCreditNoteDuplicateSeed();
  const duplicateSeed = isNew ? seedRef.current : undefined;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !cnId || cnId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setNote(null); setError(null);
    if (isNew) {
      loadSalesCreditNoteEditorContext(clientId)
        .then((c) => { if (!cancelled) setCtx(c); })
        .catch(() => { if (!cancelled) setError("Couldn't load customers for this client."); });
      return () => { cancelled = true; };
    }
    Promise.all([loadSalesCreditNoteEditorContext(clientId), loadSalesCreditNoteDetail(cnId)])
      .then(([c, n]) => {
        if (cancelled) return;
        if (!n) { setError("Credit note not found."); return; }
        setCtx(c); setNote(n);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the credit note."); });
    return () => { cancelled = true; };
  }, [clientId, cnId, isNew, reloadKey]);

  if (ctx && isNew && ctx.customers.length === 0) {
    return (
      <InvoiceWorkspaceLayout
        breadcrumbs={[
          { label: ctx.clientName || "Client", href: `/clients/${clientId}` },
          { label: "Sales", href: `/clients/${clientId}/sales?tab=credit-notes` },
          { label: "New Credit Note" },
        ]}
        title="New Credit Note"
        statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      >
        <EmptyState
          title="No customers yet"
          description="Add a customer before creating a credit note."
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
      <SalesCreditNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        customers={ctx.customers}
        existing={isNew ? undefined : note}
        duplicateSeed={isNew ? duplicateSeed : undefined}
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
