"use client";
import * as React from "react";
import { Combobox, type ComboboxHandle } from "@/components/ui/combobox";
import { api, type ApiResp } from "@/lib/api";
import { ProductServiceManagerPanel } from "@/components/catalogue/ProductServiceManagerPanel";
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
 * The pinned "+ Add Product/Service" row opens ProductServiceManagerPanel as
 * a slide-over — the full management screen (browse/search/create/edit/
 * archive/delete/bulk-actions), not a separate "quick create" dialog — so a
 * CA who wants to fix a typo on an existing preset, or just look at what's
 * already there, never has to leave the invoice. Picking (or freshly
 * creating) a row there is handed straight to `onPick`, exactly like a
 * normal search result.
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
}>(function ServiceCataloguePicker(
  { clientId, value, onPick, disabled, ariaLabel, className, size = "sm", placeholder },
  ref,
) {
  // ProductServiceManagerPanel owns its own error toast (shown right next to
  // the action that failed) — nothing needs to bubble up to the invoice
  // editor's page-level banner, which used to be the exact "error shows far
  // from where it happened" problem this picker's create flow once had.
  const [showManager, setShowManager] = React.useState(false);

  const fetchOptions = React.useCallback(async (q: string): Promise<ServiceCatalogueItem[]> => {
    if (!clientId) return [];
    const res = (await api.serviceCatalogue.list(clientId, { q, limit: 15 })) as ApiResp<ServiceCatalogueItem[]>;
    // An app-level failure (success:false, e.g. a caught backend exception —
    // still HTTP 200) must THROW, not silently resolve to []: useCombobox
    // already has a real error+Retry path for a rejected fetchOptions call,
    // but only if it actually rejects. Swallowing this here would show the
    // exact same "no matches" panel as a genuinely empty result — a false
    // negative for something that actually exists but failed to load.
    if (!res.success) throw new Error(res.error ?? "Couldn't search products/services");
    return res.data ?? [];
  }, [clientId]);

  // Recent/frequent presets shown before the CA types (empty query → recent).
  // `recentLoading` matters as much as `recent` itself: without it, opening
  // the picker before this fetch resolves is indistinguishable from a
  // genuinely empty catalogue, so the panel would falsely claim "No
  // Product/Service Found" for an item that exists and just hasn't loaded
  // yet (most visible on a cold backend start).
  //
  // `recentError` matters just as much: a FAILED fetch (network timeout, a
  // still-cold backend, a 5xx) used to be swallowed by a bare `catch {}`,
  // leaving `recent` at its empty initial value forever — indistinguishable
  // from "this client genuinely has nothing", which is a false negative a
  // CA has no way to tell apart from the truth. Surfaced now through the
  // same error+Retry UI the search path already has, via a seq-guarded
  // fetchRecent that doubles as both the initial load and the Retry handler.
  const [recent, setRecent] = React.useState<ServiceCatalogueItem[]>([]);
  const [recentLoading, setRecentLoading] = React.useState(false);
  const [recentError, setRecentError] = React.useState<string | null>(null);
  const recentSeqRef = React.useRef(0);

  const fetchRecent = React.useCallback(() => {
    const seq = ++recentSeqRef.current;
    if (!clientId) { setRecent([]); setRecentLoading(false); setRecentError(null); return; }
    setRecentLoading(true);
    setRecentError(null);
    (async () => {
      try {
        const res = (await api.serviceCatalogue.list(clientId, { limit: 8 })) as ApiResp<ServiceCatalogueItem[]>;
        if (seq !== recentSeqRef.current) return;
        if (res.success) setRecent(res.data ?? []);
        else setRecentError(res.error ?? "Couldn't load products/services");
      } catch (e) {
        if (seq !== recentSeqRef.current) return;
        setRecentError(e instanceof Error ? e.message : "Couldn't load products/services");
      } finally {
        if (seq === recentSeqRef.current) setRecentLoading(false);
      }
    })();
  }, [clientId]);

  React.useEffect(() => { fetchRecent(); }, [fetchRecent]);

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
        recentLoading={recentLoading}
        recentError={recentError}
        onRetryRecent={fetchRecent}
        getOptionId={(s) => s.id}
        getLabel={(s) => s.name}
        getSecondary={(s) => serviceSecondaryLine(s) || undefined}
        onCreate={() => setShowManager(true)}
        // QuickBooks-style: "+ Add Product/Service" is always the first row
        // in the list, with the client's existing presets listed below it —
        // not just a fallback that appears after a no-match search. This is
        // also what keeps a picker usable the instant it opens even while
        // `recent`/search results are still loading.
        pinCreateAtTop
        emptyCreateLabel="+ Add Product/Service"
        minChars={2}
        size={size}
        disabled={disabled}
        className={className}
        ariaLabel={ariaLabel ?? "Product or service"}
        placeholder={placeholder ?? "＋ Add Product/Service"}
        searchPlaceholder="Search products & services…"
        emptyText="No Product/Service Found"
      />
      {showManager && (
        <ProductServiceManagerPanel
          clientId={clientId}
          onClose={() => setShowManager(false)}
          onPick={onPick}
        />
      )}
    </>
  );
});
