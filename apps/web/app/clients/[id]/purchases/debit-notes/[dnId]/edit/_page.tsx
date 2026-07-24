"use client";

/**
 * Purchase Debit Note editor — client view. Handles BOTH create and edit:
 * dnId === "new" is the create-mode sentinel (merged from the former
 * standalone purchases/debit-notes/new/page.tsx — see redirect-rule-count
 * budget note in scripts/generate-redirects.js for why). Any other dnId
 * value is a real id to edit — drafts get the full editor; issued notes get
 * the same editor in its locked mode (notes/attachment only; see
 * DebitNoteEditor's isLocked). Mirrors purchases/bills/[billId]/edit/
 * _page.tsx (same merge, same shape) — see that file's doc comment for why
 * ids come from window.location.pathname, not useParams().
 */
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { DebitNoteEditor, type DebitNoteDetail } from "@/components/purchases/DebitNoteEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadDebitNoteEditorContext, loadDebitNoteDetail, type DebitNoteEditorContext,
} from "@/lib/purchases/debitNoteEditorContext";
import { readAndClearDebitNoteDuplicateSeed } from "@/lib/purchases/debitNoteDuplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getDnIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/purchases\/debit-notes\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function PurchaseDebitNotePageClient() {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [dnId, setDnId] = useState<string>(() => getDnIdFromLocation());
  useEffect(() => { setDnId(getDnIdFromLocation()); }, [pathname]);
  const isNew = dnId === "new";
  const router = useRouter();
  const [ctx, setCtx] = useState<DebitNoteEditorContext | null>(null);
  const [note, setNote] = useState<DebitNoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const seedRef = useRef<DebitNoteDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearDebitNoteDuplicateSeed();
  const duplicateSeed = isNew ? seedRef.current : undefined;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !dnId || dnId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setNote(null); setError(null);
    if (isNew) {
      loadDebitNoteEditorContext(clientId)
        .then((c) => { if (!cancelled) setCtx(c); })
        .catch(() => { if (!cancelled) setError("Couldn't load vendors for this client."); });
      return () => { cancelled = true; };
    }
    Promise.all([loadDebitNoteEditorContext(clientId), loadDebitNoteDetail(dnId)])
      .then(([c, n]) => {
        if (cancelled) return;
        if (!n) { setError("Debit note not found."); return; }
        setCtx(c); setNote(n);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the debit note."); });
    return () => { cancelled = true; };
  }, [clientId, dnId, isNew, reloadKey]);

  if (ctx && isNew && ctx.vendors.length === 0) {
    return (
      <InvoiceWorkspaceLayout
        breadcrumbs={[
          { label: ctx.clientName || "Client", href: `/clients/${clientId}` },
          { label: "Purchases", href: `/clients/${clientId}/purchases?tab=debit-notes` },
          { label: "New Debit Note" },
        ]}
        title="New Debit Note"
        statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      >
        <EmptyState
          title="No vendors yet"
          description="Add a vendor before creating a debit note."
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
      <DebitNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        vendors={ctx.vendors}
        existing={isNew ? undefined : note}
        duplicateSeed={isNew ? duplicateSeed : undefined}
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
