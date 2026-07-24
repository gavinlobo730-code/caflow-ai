"use client";

/**
 * Purchase Bill editor — client view. Handles BOTH create and edit: billId
 * === "new" is the create-mode sentinel (merged from the former standalone
 * purchases/bills/new/page.tsx — see redirect-rule-count budget note in
 * scripts/generate-redirects.js for why). Any other billId value is a real
 * id to edit — drafts get the full editor; received/partially-paid/paid
 * bills get the same editor in its locked mode (soft fields only — our
 * reference, notes, due date, attachment; see PurchaseBillEditor's
 * isLocked). Only cancelled bills redirect away. Mirrors
 * sales/invoices/[invoiceId]/edit/_page.tsx (same merge, same shape).
 *
 * Ids come from window.location.pathname, NOT useParams(): under `output:
 * export` + Cloudflare's rewrite-to-_placeholder hosting, the App Router's
 * FlightRouterState is permanently anchored to the "_placeholder" build
 * param, so useParams() never resolves to the real ids (see
 * ClientNavContext.tsx's doc comment) — the client id comes from the shared
 * useClientNav() hook (window.location-derived), and billId is read the
 * same way locally since there's no shared context for it.
 */
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { PurchaseBillEditor, type PurchaseBillDetail } from "@/components/purchases/PurchaseBillEditor";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadPurchaseBillEditorContext, loadPurchaseBillDetail, type PurchaseBillEditorContext,
} from "@/lib/purchases/editorContext";
import { readAndClearPurchaseBillDuplicateSeed } from "@/lib/purchases/duplicateSeed";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getBillIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/purchases\/bills\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function PurchaseBillPageClient() {
  const { clientId } = useClientNav();
  // usePathname() is only a re-run trigger (its own value is the build-time
  // placeholder segment) — the real id always comes from window.location,
  // mirroring ClientNavContext's clientId pattern.
  const pathname = usePathname();
  const [billId, setBillId] = useState<string>(() => getBillIdFromLocation());
  useEffect(() => { setBillId(getBillIdFromLocation()); }, [pathname]);
  const isNew = billId === "new";
  const router = useRouter();
  const [ctx, setCtx] = useState<PurchaseBillEditorContext | null>(null);
  const [bill, setBill] = useState<PurchaseBillDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const seedRef = useRef<PurchaseBillDetail | null | undefined>(undefined);
  if (seedRef.current === undefined) seedRef.current = readAndClearPurchaseBillDuplicateSeed();
  const duplicateSeed = isNew ? seedRef.current : undefined;

  useEffect(() => {
    // Never query the static-export placeholder ids.
    if (!clientId || clientId === "_placeholder" || !billId || billId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setBill(null); setError(null);
    if (isNew) {
      loadPurchaseBillEditorContext(clientId)
        .then((c) => { if (!cancelled) setCtx(c); })
        .catch(() => { if (!cancelled) setError("Couldn't load vendors for this client."); });
      return () => { cancelled = true; };
    }
    Promise.all([loadPurchaseBillEditorContext(clientId), loadPurchaseBillDetail(billId)])
      .then(([c, b]) => {
        if (cancelled) return;
        if (!b) { setError("Purchase bill not found."); return; }
        // Cancelled bills are immutable end-to-end (backend rejects every
        // PATCH) — everything else opens: drafts fully editable, received/
        // partially-paid/paid in the editor's locked soft-fields-only mode.
        if (b.status === "cancelled") { router.replace(`/clients/${clientId}/purchases?flash=${encodeURIComponent("Cancelled bills cannot be edited.")}`); return; }
        setCtx(c); setBill(b);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the purchase bill."); });
    return () => { cancelled = true; };
  }, [clientId, billId, isNew, reloadKey, router]);

  if (ctx && isNew && ctx.vendors.length === 0) {
    return (
      <InvoiceWorkspaceLayout
        breadcrumbs={[
          { label: ctx.clientName || "Client", href: `/clients/${clientId}` },
          { label: "Purchases", href: `/clients/${clientId}/purchases` },
          { label: "New Purchase Bill" },
        ]}
        title="New Purchase Bill"
        statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
      >
        <EmptyState
          title="No vendors yet"
          description="Add a vendor before creating a purchase bill."
          action={
            <button onClick={() => router.push(`/clients/${clientId}/purchases?tab=vendors`)} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
              Back to Purchases
            </button>
          }
        />
      </InvoiceWorkspaceLayout>
    );
  }

  if (ctx && (isNew || bill)) {
    return (
      <PurchaseBillEditor
        clientId={clientId}
        clientName={ctx.clientName}
        clientStateCode={ctx.clientStateCode}
        vendors={ctx.vendors}
        accounts={ctx.accounts}
        existing={isNew ? undefined : bill}
        duplicateSeed={isNew ? duplicateSeed : undefined}
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
        { label: isNew ? "New Purchase Bill" : (bill ? `Edit ${bill.bill_no}` : "Edit Purchase Bill") },
      ]}
      title={isNew ? "New Purchase Bill" : (bill ? `Edit ${bill.bill_no}` : "Edit Purchase Bill")}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">{isNew ? "Draft" : (bill ? bill.status.replace("_", " ") : "…")}</span>}
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
