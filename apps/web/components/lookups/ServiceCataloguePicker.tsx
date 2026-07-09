"use client";
import * as React from "react";
import { Combobox } from "@/components/ui/combobox";
import { api, type ApiResp } from "@/lib/api";
import { ProductServiceFormModal } from "@/components/catalogue/ProductServiceFormModal";
import {
  serviceSecondaryLine, type ServiceCatalogueItem,
} from "@/lib/catalogue/service";

/**
 * ServiceCataloguePicker — the "+ Add Product/Service" primary action (Final
 * Invoice Workflow Alignment). This is the ONLY way a Sales Invoice line
 * gets created: search the client's Product/Service catalogue; picking a
 * result drops a fully pre-priced line (description, HSN/SAC, GST, unit,
 * rate — description stays editable afterwards). Reuses the shared
 * Combobox (debounced server search, keyboard nav, loading/empty/error
 * states, ARIA) exactly like HsnLookup, so there is no bespoke lookup chrome.
 *
 * Products/Services are client-owned (migration 182), so every fetch here is
 * scoped to `clientId` — a firm's other clients' presets never appear.
 *
 * No match ("No Product/Service Found") → the "+" row opens
 * ProductServiceFormModal (the SAME create dialog as the client-workspace
 * management page — one creation workflow, not a separate "custom line"
 * path). On save, the new item is handed straight to `onPick`, exactly like
 * a normal search result — auto-select + auto-fill, no extra step.
 *
 * It holds no persistent value — selecting/creating a preset fires `onPick`
 * (the caller fills a line) and records a usage bump so recent/frequent
 * presets rank first. The preset's values are copied onto the line, never
 * linked, so a later edit or archive of the preset can't change a past
 * invoice.
 */
export function ServiceCataloguePicker({
  clientId, onPick, disabled, ariaLabel, className, size = "sm", onError,
}: {
  clientId: string;
  onPick: (item: ServiceCatalogueItem) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
  size?: "sm" | "md";
  /** Forwarded create-dialog errors (e.g. duplicate name). If omitted, the
   * picker shows a small inline message of its own so a failure is never
   * silent. */
  onError?: (msg: string) => void;
}) {
  const [quickCreateSeed, setQuickCreateSeed] = React.useState<string | null>(null);
  const [localError, setLocalError] = React.useState<string | null>(null);

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
    <>
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
        onCreate={(label) => setQuickCreateSeed(label)}
        createLabel={(q) => `No Product/Service Found — + Create "${q}"`}
        minChars={2}
        size={size}
        disabled={disabled}
        className={className}
        ariaLabel={ariaLabel ?? "Add Product/Service"}
        placeholder="＋ Add Product/Service"
        searchPlaceholder="Search products & services…"
        emptyText="No Product/Service Found"
      />
      {localError && !onError && (
        <p className="mt-1 text-[11px] text-red-600">{localError}</p>
      )}
      {quickCreateSeed !== null && (
        <ProductServiceFormModal
          clientId={clientId}
          existing={null}
          seedName={quickCreateSeed}
          onClose={() => setQuickCreateSeed(null)}
          onSaved={(item) => {
            setQuickCreateSeed(null);
            setLocalError(null);
            onPick(item);
          }}
          onError={(msg) => (onError ? onError(msg) : setLocalError(msg))}
        />
      )}
    </>
  );
}
