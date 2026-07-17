"use client";

/**
 * Edit Purchase Debit Note — client view. Drafts get the full editor;
 * issued notes get the same editor in its locked mode (notes/attachment
 * only; see DebitNoteEditor's isLocked). Mirrors purchases/bills/[billId]/
 * edit/_page.tsx (same static-export id resolution, same loading/error
 * skeleton shell) — see that file's doc comment for why ids come from
 * window.location.pathname, not useParams().
 */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { DebitNoteEditor, type DebitNoteDetail } from "@/components/purchases/DebitNoteEditor";
import { ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadDebitNoteEditorContext, loadDebitNoteDetail, type DebitNoteEditorContext,
} from "@/lib/purchases/debitNoteEditorContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getDnIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/purchases\/debit-notes\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function EditDebitNotePageClient() {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [dnId, setDnId] = useState<string>(() => getDnIdFromLocation());
  useEffect(() => { setDnId(getDnIdFromLocation()); }, [pathname]);
  const router = useRouter();
  const [ctx, setCtx] = useState<DebitNoteEditorContext | null>(null);
  const [note, setNote] = useState<DebitNoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !dnId || dnId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setNote(null); setError(null);
    Promise.all([loadDebitNoteEditorContext(clientId), loadDebitNoteDetail(dnId)])
      .then(([c, n]) => {
        if (cancelled) return;
        if (!n) { setError("Debit note not found."); return; }
        setCtx(c); setNote(n);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the debit note."); });
    return () => { cancelled = true; };
  }, [clientId, dnId, reloadKey]);

  if (ctx && note) {
    return (
      <DebitNoteEditor
        clientId={clientId}
        clientName={ctx.clientName}
        vendors={ctx.vendors}
        existing={note}
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
