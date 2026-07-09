"use client";
import * as React from "react";
import { Combobox, type ComboboxHandle } from "@/components/ui/combobox";
import { api, type ApiResp } from "@/lib/api";
import { ProductServiceFormModal } from "@/components/catalogue/ProductServiceFormModal";
import {
  serviceSecondaryLine, type ServiceCatalogueItem,
} from "@/lib/catalogue/service";

/**
 * ServiceCataloguePicker — the FIRST CELL of every Sales Invoice line
 * (Final Invoice Workflow Alignment; refined so the picker lives per-row
 * instead of a single header-level "+ Add Product/Service" control).
 * Picking a result auto-fills that same row's description, HSN/SAC, GST,
 * unit and rate — description stays editable afterwards. Reuses the shared
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
 * It is a controlled display, not a controlled input: `value` is the
 * caller's current pick for THIS row (shown in the trigger instead of the
 * placeholder), but selecting/creating a preset only ever fires `onPick` —
 * the caller owns the line state. The preset's values are copied onto the
 * line, never linked, so a later edit or archive of the preset can't change
 * a past invoice. Ref-forwards a `{ focus() }` handle so the invoice editor
 * can move focus here after adding a line or spreadsheet-style Tab.
 */
export const ServiceCataloguePicker = React.forwardRef<ComboboxHandle, {
  clientId: string;
  /** This row's current pick, if any — shown in the trigger. */
  value?: ServiceCatalogueItem | null;
  onPick: (item: ServiceCatalogueItem) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
  size?: "sm" | "md";
  placeholder?: string;
  /** Forwarded create-dialog errors (e.g. duplicate name). If omitted, the
   * picker shows a small inline message of its own so a failure is never
   * silent. */
  onError?: (msg: string) => void;
}>(function ServiceCataloguePicker(
  { clientId, value, onPick, disabled, ariaLabel, className, size = "sm", placeholder, onError },
  ref,
) {
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
        ref={ref}
        value={value ?? null}
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
        ariaLabel={ariaLabel ?? "Product or service"}
        placeholder={placeholder ?? "＋ Add Product/Service"}
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
});
