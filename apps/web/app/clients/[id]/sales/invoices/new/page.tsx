"use client";

/**
 * Create Invoice route (Batch 3). Loads editor context, then renders the new
 * InvoiceEditor (which owns the workspace layout, toolbar, summary and dirty guard).
 * Loading/empty/error render inside the same workspace shell for continuity.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { InvoiceEditor } from "@/components/invoices/InvoiceEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import { loadInvoiceEditorContext, type InvoiceEditorContext } from "@/lib/invoices/editorContext";
import { salesListHref, salesListFlashHref, invoiceBreadcrumbs } from "@/lib/invoices/workspaceNav";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { readAndClearDuplicateSeed } from "@/lib/invoices/duplicateSeed";
import type { InvoiceDetail } from "@/lib/invoices/shared";

export default function NewInvoicePage() {
  // Read the client id from ClientNavContext (window.location-derived), NOT
  // useParams(): under `output: export` + Cloudflare's rewrite-to-_placeholder
  // hosting, the App Router's FlightRouterState is permanently anchored to the
  // "_placeholder" build param — useParams() never resolves to the real id, on
  // first load OR after a client-side navigation (see ClientNavContext.tsx's
  // doc comment). A prior fix swapped a build-time `params` prop for
  // useParams(), which looked right but has the identical failure mode: both
  // are "_placeholder" forever, so this page's loader effect silently no-ops
  // and the workspace hangs on its loading skeleton permanently in production.
  const { clientId } = useClientNav();
  const router = useRouter();
  const [ctx, setCtx] = useState<InvoiceEditorContext | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // Read-and-clear exactly once. A useState lazy initializer would work in
  // production, but React 18 Strict Mode double-invokes it in dev — the
  // first call would clear sessionStorage, the second would read back null
  // and "win". A guarded ref survives that double-invoke (same ref object
  // across both calls in one render, so the guard already trips on call 2).
  const seedRef = useRef<InvoiceDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearDuplicateSeed();
  const duplicateSeed = seedRef.current;

  useEffect(() => {
    // Guard against the static-export placeholder ever reaching a data query.
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setError(false);
    loadInvoiceEditorContext(clientId)
      .then((c) => { if (!cancelled) setCtx(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [clientId, reloadKey]);

  if (ctx && ctx.customers.length > 0) {
    return (
      <InvoiceEditor
        clientId={clientId}
        clientName={ctx.clientName}
        clientStateCode={ctx.clientStateCode}
        customers={ctx.customers}
        existing={null}
        duplicateSeed={duplicateSeed}
        onDone={(msg) => router.push(salesListFlashHref(clientId, msg))}
        onCancel={() => router.push(salesListHref(clientId))}
      />
    );
  }

  // While context is loading, keep the toolbar + summary rail present (as
  // disabled skeletons) so the two-column workspace shell never collapses to a
  // single bare column — only the error/empty branches drop them, since those
  // are terminal states with their own centered treatment, not a "loading" beat.
  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={invoiceBreadcrumbs(clientId, ctx?.clientName, "New Invoice")}
      title="New Sales Invoice"
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      toolbar={!error && !ctx ? <InvoiceToolbarSkeleton /> : undefined}
      summary={!error && !ctx ? <SummaryPanelSkeleton /> : undefined}
    >
      {error ? (
        <ErrorState message="Couldn't load customers for this client." onRetry={() => setReloadKey((k) => k + 1)} />
      ) : !ctx ? (
        <InvoiceEditorSkeleton />
      ) : (
        <EmptyState
          title="No customers yet"
          description="Add a customer before creating an invoice."
          action={
            <button onClick={() => router.push(salesListHref(clientId))} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Sales
            </button>
          }
        />
      )}
    </InvoiceWorkspaceLayout>
  );
}
