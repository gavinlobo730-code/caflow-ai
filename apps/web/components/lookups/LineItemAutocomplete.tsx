"use client";
import * as React from "react";
import { createPortal } from "react-dom";
import { Loader2, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCombobox } from "@/lib/combobox/useCombobox";
import { api, type ApiResp } from "@/lib/api";
import type { ServiceCatalogueItem } from "@/lib/catalogue/service";
import { formatServicePrice } from "@/lib/catalogue/service";
import type { HsnRow } from "@/lib/lookups/hsn";
import { formatHsnRate } from "@/lib/lookups/hsn";
import {
  mergeLineItemSuggestions, suggestionToLinePatch, type LineItemSuggestion,
} from "@/lib/invoices/lineItemSuggestions";
import type { InvoiceLine } from "@/lib/invoices/gst";

const BADGE_CLASS: Record<string, string> = {
  Service: "bg-emerald-50 text-emerald-700",
  SAC: "bg-violet-50 text-violet-700",
  HSN: "bg-sky-50 text-sky-700",
};

/** The muted detail line for a suggestion row: "SAC 998222 · 18% GST · ₹5,000". */
function detailLine(s: LineItemSuggestion): string {
  const codeLabel = s.badge === "Service" ? "SAC/HSN" : s.badge ?? "Code";
  return [
    s.hsn_sac ? `${codeLabel} ${s.hsn_sac}` : "",
    s.gst_rate_bps != null ? formatHsnRate(s.gst_rate_bps) : "",
    s.rate_paise ? formatServicePrice(s.rate_paise) : "",
  ].filter(Boolean).join(" · ");
}

/**
 * The primary, description-driven line-item entry field (HSN/SAC UX redesign).
 * Typing here searches the firm's Service Catalogue AND the HSN/SAC
 * master+history in parallel (one search, not two) and shows a floating
 * "command palette" of matches — each with its full description, code, GST %,
 * a recency badge and (for catalogue presets) a default price. Picking one
 * fills description, HSN/SAC, GST % and unit in a single action; a catalogue
 * pick also fills the rate. Nothing here is locked afterwards — every field
 * stays a normal, freely-editable input, and the code/rate are pre-fill hints
 * only (CGST Rule 46(g)/(h)) never applied to any tax/journal computation
 * without the existing CA-review path.
 *
 * The panel renders in a portal (fixed-positioned against the input's own
 * bounding rect) so it always draws above the line-items table's own
 * `overflow-x-auto` wrapper instead of being clipped or scrolling with it.
 */
export const LineItemAutocomplete = React.forwardRef<
  HTMLInputElement,
  {
    value: string;
    onChange: (v: string) => void;
    onPick: (patch: Partial<InvoiceLine>, meta: { catalogueId: string | null }) => void;
    clientId?: string;
    disabled?: boolean;
    placeholder?: string;
    ariaLabel?: string;
    id?: string;
    className?: string;
    /** Forwarded from the row's own onKeyDown (e.g. Enter-adds-a-row) — only
     * called when this field's own suggestion panel isn't handling the key. */
    onKeyDownFallback?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  }
>(function LineItemAutocomplete(
  { value, onChange, onPick, clientId, disabled, placeholder, ariaLabel, id, className, onKeyDownFallback },
  forwardedRef,
) {
  const reactId = React.useId();
  const baseId = id ?? reactId;
  const listboxId = `${baseId}-listbox`;

  const [open, setOpen] = React.useState(false);
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const innerInputRef = React.useRef<HTMLInputElement | null>(null);
  const listRef = React.useRef<HTMLDivElement>(null);
  // The suggestion panel renders in a portal (see below), so it is NOT a DOM
  // descendant of wrapRef even though it's a React child — the outside-click
  // check below must test both, or every click on a suggestion row would be
  // treated as an "outside" click and close/unmount the panel on mousedown,
  // before the click event that would have committed the pick ever runs.
  const panelRef = React.useRef<HTMLDivElement>(null);
  const setInputRef = React.useCallback(
    (el: HTMLInputElement | null) => {
      innerInputRef.current = el;
      if (typeof forwardedRef === "function") forwardedRef(el);
      else if (forwardedRef) (forwardedRef as React.MutableRefObject<HTMLInputElement | null>).current = el;
    },
    [forwardedRef],
  );

  const fetchOptions = React.useCallback(
    async (q: string): Promise<LineItemSuggestion[]> => {
      const [svcRes, hsnRes] = await Promise.all([
        api.serviceCatalogue.list({ q, limit: 6 }) as Promise<ApiResp<ServiceCatalogueItem[]>>,
        api.hsn.search(q, { client_id: clientId, limit: 8 }) as Promise<ApiResp<HsnRow[]>>,
      ]);
      return mergeLineItemSuggestions(svcRes.data ?? [], hsnRes.data ?? []);
    },
    [clientId],
  );

  // Recent-first (empty query): the firm's recent catalogue presets + recently
  // used HSN/SAC codes for this client, merged the same way. Best-effort — an
  // empty/failed fetch just means no suggestions until the CA types.
  const [recent, setRecent] = React.useState<LineItemSuggestion[]>([]);
  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [svcRes, hsnRes] = await Promise.all([
          api.serviceCatalogue.list({ limit: 6 }) as Promise<ApiResp<ServiceCatalogueItem[]>>,
          clientId
            ? (api.hsn.search("", { client_id: clientId, limit: 6 }) as Promise<ApiResp<HsnRow[]>>)
            : Promise.resolve({ success: true, error: null, data: [] } as ApiResp<HsnRow[]>),
        ]);
        if (alive) setRecent(mergeLineItemSuggestions(svcRes.data ?? [], hsnRes.data ?? []));
      } catch { /* best-effort recent list */ }
    })();
    return () => { alive = false; };
  }, [clientId]);

  const combo = useCombobox<LineItemSuggestion>({
    fetchOptions,
    recent,
    getOptionId: (s) => s.id,
    getLabel: (s) => s.description,
    minChars: 2,
    debounceMs: 250,
  });
  const { query, setQuery, results, loading, error, highlighted, setHighlighted, retry } = combo;

  // The description input is the query input — keep them driven by the same
  // onChange so no separate "search box" is ever needed.
  const handleInputChange = (v: string) => {
    onChange(v);
    setQuery(v);
    if (!open) setOpen(true);
  };

  const commit = React.useCallback(
    (s: LineItemSuggestion) => {
      onPick(suggestionToLinePatch(s), { catalogueId: s.catalogueId });
      setOpen(false);
      setQuery("");
    },
    [onPick, setQuery],
  );

  // Click-away closes the panel without discarding the typed description.
  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      const inWrap = wrapRef.current?.contains(t);
      const inPanel = panelRef.current?.contains(t);
      if (!inWrap && !inPanel) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Anchor rect for the portal panel — recomputed on open and kept in sync
  // with scrolling/resizing (capture phase so scrolling ANY ancestor, e.g. the
  // line-items table's horizontal scroller, repositions it too).
  const [rect, setRect] = React.useState<DOMRect | null>(null);
  React.useEffect(() => {
    if (!open) return;
    const update = () => setRect(innerInputRef.current?.getBoundingClientRect() ?? null);
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${highlighted}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [highlighted, open, results]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) {
      onKeyDownFallback?.(e);
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlighted(Math.min(highlighted + 1, results.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlighted(Math.max(highlighted - 1, 0));
        break;
      case "Enter":
        e.preventDefault();
        if (results[highlighted]) commit(results[highlighted]);
        break;
      case "Escape":
        e.preventDefault();
        setOpen(false);
        break;
      default:
        onKeyDownFallback?.(e);
    }
  };

  const showPanel = open && !disabled;
  // Flip the panel above the input when there isn't room below (a low row in
  // a long line-items table) so it's never squeezed to a sliver.
  const spaceBelow = rect ? window.innerHeight - rect.bottom - 12 : 0;
  const spaceAbove = rect ? rect.top - 12 : 0;
  const flipUp = rect ? spaceBelow < 160 && spaceAbove > spaceBelow : false;
  const panelWidth = rect ? Math.max(rect.width, 420) : 420;
  const panelLeft = rect ? Math.min(rect.left, window.innerWidth - panelWidth - 8) : 0;
  const panelMaxHeight = rect ? Math.max(160, Math.min(420, flipUp ? spaceAbove : spaceBelow)) : 320;

  return (
    <div ref={wrapRef} className="relative">
      <input
        ref={setInputRef}
        id={baseId}
        role="combobox"
        aria-expanded={showPanel}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-label={ariaLabel}
        aria-activedescendant={showPanel && results[highlighted] ? `${baseId}-opt-${highlighted}` : undefined}
        value={value}
        onChange={(e) => handleInputChange(e.target.value)}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoComplete="off"
        disabled={disabled}
        className={cn(
          "w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs",
          className,
        )}
      />

      {showPanel && rect && typeof document !== "undefined" && createPortal(
        <div
          ref={panelRef}
          style={{
            position: "fixed",
            left: panelLeft,
            width: panelWidth,
            ...(flipUp ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
          }}
          className="z-50 overflow-hidden rounded-lg border border-[#E2E8F0] bg-white shadow-xl"
        >
          <div className="flex items-center gap-2 border-b border-[#F1F5F9] px-3 py-2 bg-[#F8FAFC]">
            <Search size={13} className="flex-shrink-0 text-[#94A3B8]" />
            <span className="text-[10px] font-medium text-[#64748B]">
              {query.trim().length < 2 ? "Recent items" : "Matches from your catalogue & HSN/SAC master"}
            </span>
            {loading && <Loader2 size={13} className="ml-auto flex-shrink-0 animate-spin text-[#94A3B8]" />}
          </div>
          <div
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-label="Item suggestions"
            className="overflow-y-auto py-1"
            style={{ maxHeight: panelMaxHeight }}
          >
            {error ? (
              <div className="px-3 py-3 text-center text-[11px] text-red-600">
                {error}.{" "}
                <button type="button" onClick={retry} className="underline hover:text-red-700">
                  Retry
                </button>
              </div>
            ) : results.length === 0 ? (
              <div className="px-3 py-4 text-center text-[11px] text-[#94A3B8]">
                {loading
                  ? "Searching…"
                  : query.trim().length < 2
                    ? "Type at least 2 characters to search your catalogue and HSN/SAC master."
                    : "No matches — keep typing your own description; HSN/SAC stays editable below."}
              </div>
            ) : (
              results.map((s, i) => {
                const active = i === highlighted;
                return (
                  <div
                    key={s.id}
                    id={`${baseId}-opt-${i}`}
                    data-idx={i}
                    role="option"
                    aria-selected={active}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setHighlighted(i)}
                    onClick={() => commit(s)}
                    className={cn(
                      "flex cursor-pointer items-start gap-2.5 px-3.5 py-2.5",
                      active ? "bg-[#EFF6FF]" : "hover:bg-[#F8FAFC]",
                    )}
                  >
                    {s.badge && (
                      <span className={cn("mt-0.5 flex-shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold", BADGE_CLASS[s.badge])}>
                        {s.badge}
                      </span>
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-medium text-[#1E293B]">{s.description}</span>
                      <span className="block text-[10px] text-[#94A3B8] mt-0.5">{detailLine(s)}</span>
                    </span>
                    {s.reason && (
                      <span className="flex-shrink-0 rounded-full bg-[#F1F5F9] px-2 py-0.5 text-[9px] font-medium text-[#64748B]">
                        {s.reason}
                      </span>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
});
