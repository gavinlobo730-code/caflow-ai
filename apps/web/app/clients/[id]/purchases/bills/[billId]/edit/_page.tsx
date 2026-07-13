"use client";

/**
 * Edit Draft Purchase Bill — client view. Only drafts are editable — anything
 * else redirects to the Purchases list. Mirrors
 * sales/invoices/[invoiceId]/edit/_page.tsx exactly (same static-export id
 * resolution, same loading/error skeleton shell).
 *
 * Ids come from window.location.pathname, NOT useParams(): under `output:
 * export` + Cloudflare's rewrite-to-_placeholder hosting, the App Router's
 * FlightRouterState is permanently anchored to the "_placeholder" build
 * param, so useParams() never resolves to the real ids (see
 * ClientNavContext.tsx's doc comment) — the client id comes from the shared
 * useClientNav() hook (window.location-derived), and billId is read the
 * same way locally since there's no shared context for it.
 */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { PurchaseBillEditor, type PurchaseBillDetail } from "@/components/purchases/PurchaseBillEditor";
import { ErrorState } from "@/components/ui/states";
import {
  InvoiceEditorSkeleton, SummaryPanelSkeleton, InvoiceToolbarSkeleton,
} from "@/components/invoices/InvoiceEditorSkeleton";
import {
  loadPurchaseBillEditorContext, loadPurchaseBillDetail, type PurchaseBillEditorContext,
} from "@/lib/purchases/editorContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

function getBillIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/purchases\/bills\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function EditPurchaseBillPageClient() {
  const { clientId } = useClientNav();
  // usePathname() is only a re-run trigger (its own value is the build-time
  // placeholder segment) — the real id always comes from window.location,
  // mirroring ClientNavContext's clientId pattern.
  const pathname = usePathname();
  const [billId, setBillId] = useState<string>(() => getBillIdFromLocation());
  useEffect(() => { setBillId(getBillIdFromLocation()); }, [pathname]);
  const router = useRouter();
  const [ctx, setCtx] = useState<PurchaseBillEditorContext | null>(null);
  const [bill, setBill] = useState<PurchaseBillDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    // Never query the static-export placeholder ids.
    if (!clientId || clientId === "_placeholder" || !billId || billId === "_placeholder") return;
    let cancelled = false;
    setCtx(null); setBill(null); setError(null);
    Promise.all([loadPurchaseBillEditorContext(clientId), loadPurchaseBillDetail(billId)])
      .then(([c, b]) => {
        if (cancelled) return;
        if (!b) { setError("Purchase bill not found."); return; }
        if (b.status !== "draft") { router.replace(`/clients/${clientId}/purchases`); return; }
        setCtx(c); setBill(b);
      })
      .catch(() => { if (!cancelled) setError("Failed to load the purchase bill."); });
    return () => { cancelled = true; };
  }, [clientId, billId, reloadKey, router]);

  if (ctx && bill) {
    return (
      <PurchaseBillEditor
        clientId={clientId}
        clientName={ctx.clientName}
        clientStateCode={ctx.clientStateCode}
        vendors={ctx.vendors}
        accounts={ctx.accounts}
        existing={bill}
        onDone={(msg) => router.push(`/clients/${clientId}/purchases?flash=${encodeURIComponent(msg)}`)}
        onCancel={() => router.push(`/clients/${clientId}/purchases`)}
      />
    );
  }

  // Keep the toolbar + summary rail present (as disabled skeletons) while
  // loading so the two-column shell never collapses — see bills/new/page.tsx.
  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: ctx?.clientName || "Client", href: `/clients/${clientId}` },
        { label: "Purchases", href: `/clients/${clientId}/purchases` },
        { label: bill ? `Edit ${bill.bill_no}` : "Edit Purchase Bill" },
      ]}
      title={bill ? `Edit ${bill.bill_no}` : "Edit Draft Purchase Bill"}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Draft</span>}
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
