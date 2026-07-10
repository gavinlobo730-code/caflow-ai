"use client";

/**
 * Products & Services management (HSN/SAC workflow alignment, migration
 * 182) — client-owned reusable goods/services billing presets. This route
 * exists so the sidebar entry has a real, bookmarkable/deep-linkable URL;
 * the actual UI is ProductServiceManagerPanel (mode="embedded") — the SAME
 * component ServiceCataloguePicker opens as a slide-over from a Sales
 * Invoice line's "+ Add Product/Service" row, so there is exactly ONE
 * management screen, not two that could drift out of sync.
 */
import { RoleGuard } from "@/components/RoleGuard";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { ProductServiceManagerPanel } from "@/components/catalogue/ProductServiceManagerPanel";

export default function ProductsServicesPage() {
  const { clientId } = useClientNav();

  if (!clientId || clientId === "_placeholder") {
    return <div className="p-6 max-w-4xl mx-auto text-sm text-[#94A3B8]">Loading…</div>;
  }

  return (
    <RoleGuard allowed={["Partner", "Manager"]}>
      <ProductServiceManagerPanel clientId={clientId} mode="embedded" />
    </RoleGuard>
  );
}
