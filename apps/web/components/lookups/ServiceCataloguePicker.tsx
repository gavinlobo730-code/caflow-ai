"use client";
import * as React from "react";
import { Combobox } from "@/components/ui/combobox";
import { api, type ApiResp } from "@/lib/api";
import {
  serviceSecondaryLine, type ServiceCatalogueItem,
} from "@/lib/catalogue/service";

/**
 * ServiceCataloguePicker — pick a client's billing preset and drop a fully
 * pre-priced invoice line (Batch 6). Reuses the shared Combobox (debounced
 * server search, keyboard nav, loading/empty/error states, ARIA) exactly like
 * HsnLookup, so there is no bespoke lookup chrome.
 *
 * Products/Services are client-owned (migration 182), so every fetch here is
 * scoped to `clientId` — a firm's other clients' presets never appear.
 *
 * It holds no persistent value — selecting a preset fires `onPick` (the caller
 * fills a line) and records a usage bump so recent/frequent presets rank first.
 * The preset's values are copied onto the line, never linked, so a later edit or
 * archive of the preset can't change a past invoice.
 */
export function ServiceCataloguePicker({
  clientId, onPick, disabled, ariaLabel, className, size = "sm",
}: {
  clientId: string;
  onPick: (item: ServiceCatalogueItem) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
  size?: "sm" | "md";
}) {
  const fetchOptions = React.useCallback(async (q: string): Promise<ServiceCatalogueItem[]> => {
    if (!clientId) return [];
    const res = (await api.serviceCatalogue.list(clientId, { q, limit: 15 })) as ApiResp<ServiceCatalogueItem[]>;
    return res.data ?? [];
  }, [clientId]);

  // Recent/frequent presets shown before the CA types (empty query → recent).
  const [recent, setRecent] = React.useState<ServiceCatalogueItem[]>([]);
  React.useEffect(() => {
    if (!clientId) { setRecent([]); return; }
    let alive = true;
    (async () => {
      try {
        const res = (await api.serviceCatalogue.list(clientId, { limit: 8 })) as ApiResp<ServiceCatalogueItem[]>;
        if (alive) setRecent(res.data ?? []);
      } catch { /* best-effort */ }
    })();
    return () => { alive = false; };
  }, [clientId]);

  return (
    <Combobox<ServiceCatalogueItem>
      value={null}
      onChange={(v) => {
        const item = (Array.isArray(v) ? v[0] : v) ?? null;
        if (!item) return;
        onPick(item);
        // Fire-and-forget usage bump so recent/frequent ranking improves.
        api.serviceCatalogue.recordUsed(item.id).catch(() => {});
      }}
      fetchOptions={fetchOptions}
      recent={recent}
      getOptionId={(s) => s.id}
      getLabel={(s) => s.name}
      getSecondary={(s) => serviceSecondaryLine(s) || undefined}
      minChars={2}
      size={size}
      disabled={disabled}
      className={className}
      ariaLabel={ariaLabel ?? "Add from service catalogue"}
      placeholder="＋ Add from catalogue"
      searchPlaceholder="Search services by name, SAC or price…"
      emptyText="No matching services"
    />
  );
}
