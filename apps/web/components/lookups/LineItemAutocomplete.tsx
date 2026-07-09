"use client";
import * as React from "react";
import { createPortal } from "react-dom";
import { Loader2, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCombobox } from "@/lib/combobox/useCombobox";
import type { ServiceCatalogueItem } from "@/lib/catalogue/service";
import { formatServicePrice } from "@/lib/catalogue/service";
import type { HsnRow } from "@/lib/lookups/hsn";
import { formatHsnRate } from "@/lib/lookups/hsn";
import {
  mergeLineItemSuggestions, suggestionToLinePatch, type LineItemSuggestion,
} from "@/lib/invoices/lineItemSuggestions";
import {
  getCachedCatalogue, getCachedHsnRecent, getCachedHsnSearch, recordCatalogueUsed,
} from "@/lib/invoices/lineItemSuggestionCache";
import type { InvoiceLine } from "@/lib/invoices/gst";

/** The "where this came from" pill shown on the right of each card. */
const SOURCE_BADGE_CLASS: Record<string, string> = {
  Catalogue: "bg-emerald-50 text-emerald-700",
  Recent: "bg-amber-50 text-amber-700",
  "Your Library": "bg-violet-50 text-violet-700",
};

/** The muted detail line for a suggestion row: "SAC 998222 · 18% GST · NOS · ₹5,000". */
function detailLine(s: LineItemSuggestion): string {
  const codeLabel = s.codeType ?? "Code";
  return [
    s.hsn_sac ? `${codeLabel} ${s.hsn_sac}` : "",
    s.gst_rate_bps != null ? formatHsnRate(s.gst_rate_bps) : "",
    s.unit ?? "",
    s.rate_paise ? formatServicePrice(s.rate_paise) : "",
  ].filter(Boolean).join(" · ");
}

/**
 * The primary, description-driven line-item entry field (HSN/SAC UX redesign).
 * Typing here searches the firm's Product & Service master AND the firm's
 * own HSN/SAC library+history in parallel (one search, not two — Caflow
 * ships no shared master here) and shows a floating "command palette" of
 * matches — each with its full description, code, GST %,
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
    onPick: (patch: Partial<InvoiceLine>) => void;
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

  // Service Catalogue: one CLIENT's own presets are few (tens, not
  // thousands) and fetched ONCE per client — cached and shared across every
  // line on the page for that client (see lineItemSuggestionCache) — then
  // matched entirely CLIENT-SIDE via the same sync engine every other
  // Combobox uses (lib/combobox/match.ts). That means catalogue matches,
  // which mergeLineItemSuggestions always ranks first, appear the instant a
  // key is pressed: no debounce, no network round trip.
  const [catalogue, setCatalogue] = React.useState<ServiceCatalogueItem[]>([]);
  const [catalogueReady, setCatalogueReady] = React.useState(false);
  const loadCatalogue = React.useCallback(() => {
    if (!clientId) { setCatalogue([]); setCatalogueReady(true); return; }
    getCachedCatalogue(clientId).then((rows) => { setCatalogue(rows); setCatalogueReady(true); });
  }, [clientId]);
  React.useEffect(() => { loadCatalogue(); }, [loadCatalogue]);
  const catalogueCombo = useCombobox<ServiceCatalogueItem>({
    options: catalogue,
    getOptionId: (s) => s.id,
    getLabel: (s) => s.name,
    getSearchFields: (s) => [s.name, s.description ?? "", s.hsn_sac ?? ""],
  });

  // HSN/SAC: the master is too large to ship client-side, so this stays a
  // debounced server search — but every result is cached by exact query
  // string and the "recent" list is deduped across every row on the page, so
  // a repeat/backspace-retyped query, or a second line on the same invoice,
  // never re-hits the network for data already fetched this session.
  const [hsnRecent, setHsnRecent] = React.useState<HsnRow[]>([]);
  React.useEffect(() => {
    if (!clientId) { setHsnRecent([]); return; }
    let alive = true;
    getCachedHsnRecent(clientId).then((rows) => { if (alive) setHsnRecent(rows); });
    return () => { alive = false; };
  }, [clientId]);
  const hsnFetch = React.useCallback((q: string) => getCachedHsnSearch(q, clientId), [clientId]);
  const hsnCombo = useCombobox<HsnRow>({
    fetchOptions: hsnFetch,
    recent: hsnRecent,
    getOptionId: (h) => h.hsn_code,
    getLabel: (h) => h.hsn_code,
    // Search starts from the FIRST character — no artificial minimum. The
    // debounce + per-query cache (lineItemSuggestionCache) keep this cheap
    // even though it now fires on "a" alone.
    minChars: 1,
    debounceMs: 120,
  });

  const query = catalogueCombo.query;
  const setQuery = React.useCallback(
    (v: string) => { catalogueCombo.setQuery(v); hsnCombo.setQuery(v); },
    [catalogueCombo, hsnCombo],
  );
  const results = React.useMemo(
    () => mergeLineItemSuggestions(catalogueCombo.results, hsnCombo.results),
    [catalogueCombo.results, hsnCombo.results],
  );
  // A single highlighted index over the MERGED list — each sub-combobox keeps
  // its own (unused) highlighted state, but the panel only ever renders one
  // list, so only one index makes sense here.
  const [highlighted, setHighlighted] = React.useState(0);
  React.useEffect(() => { setHighlighted(0); }, [results]);
  const loading = hsnCombo.loading || !catalogueReady;
  const error = hsnCombo.error;
  const retry = React.useCallback(() => { loadCatalogue(); hsnCombo.retry(); }, [loadCatalogue, hsnCombo]);

  // The description input is the query input — keep them driven by the same
  // onChange so no separate "search box" is ever needed.
  const handleInputChange = (v: string) => {
    onChange(v);
    setQuery(v);
    if (!open) setOpen(true);
  };

  const commit = React.useCallback(
    (s: LineItemSuggestion) => {
      onPick(suggestionToLinePatch(s));
      if (s.catalogueId && clientId) recordCatalogueUsed(s.catalogueId, clientId);
      setOpen(false);
      setQuery("");
    },
    [onPick, setQuery, clientId],
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
  const isEmptyQuery = query.trim().length === 0;
  // Flip the panel above the input when there isn't room below (a low row in
  // a long line-items table) so it's never squeezed to a sliver.
  const spaceBelow = rect ? window.innerHeight - rect.bottom - 12 : 0;
  const spaceAbove = rect ? rect.top - 12 : 0;
  const flipUp = rect ? spaceBelow < 200 && spaceAbove > spaceBelow : false;
  // Width based on content, floored at a comfortable command-palette size and
  // capped so it never runs off the viewport on a narrow row.
  const panelWidth = rect ? Math.min(Math.max(rect.width, 460), window.innerWidth - 16) : 460;
  const panelLeft = rect ? Math.min(rect.left, window.innerWidth - panelWidth - 8) : 0;
  // Use as much of the available viewport space as there is — a firm's
  // catalogue plus master matches can easily run past a small fixed cap, and
  // "no tiny internal scrolling unless absolutely necessary" means the cap
  // should be the viewport, not an arbitrary pixel count.
  const panelMaxHeight = rect ? Math.max(200, (flipUp ? spaceAbove : spaceBelow)) : 360;

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
            maxHeight: panelMaxHeight,
            ...(flipUp ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }),
          }}
          className="z-50 flex flex-col overflow-hidden rounded-xl border border-[#E2E8F0] bg-white shadow-2xl ring-1 ring-black/5"
        >
          <div className="flex flex-shrink-0 items-center gap-2 border-b border-[#F1F5F9] px-4 py-2.5 bg-[#F8FAFC]">
            <Search size={13} className="flex-shrink-0 text-[#94A3B8]" />
            <span className="text-[10.5px] font-medium tracking-wide text-[#64748B]">
              {isEmptyQuery ? "Recent & frequently used" : "Searching your catalogue & your HSN/SAC library"}
            </span>
            {loading && <Loader2 size={13} className="ml-auto flex-shrink-0 animate-spin text-[#94A3B8]" />}
          </div>
          <div
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-label="Item suggestions"
            className="min-h-0 flex-1 overflow-y-auto py-1.5"
          >
            {error ? (
              <div className="px-4 py-5 text-center text-[12px] text-red-600">
                {error}.{" "}
                <button type="button" onClick={retry} className="underline hover:text-red-700">
                  Retry
                </button>
              </div>
            ) : results.length === 0 ? (
              <div className="px-4 py-6 text-center text-[12px] text-[#94A3B8]">
                {loading
                  ? "Searching…"
                  : isEmptyQuery
                    ? "Start typing to search your Products & Services and your HSN/SAC library."
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
                      "flex cursor-pointer items-start gap-3 px-4 py-3",
                      active ? "bg-[#EFF6FF]" : "hover:bg-[#F8FAFC]",
                    )}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-medium leading-snug text-[#1E293B]">
                        {s.description}
                      </span>
                      <span className="mt-1 block text-[11px] leading-snug text-[#94A3B8]">
                        {detailLine(s) || "No SAC/HSN on file — pick to use as a free-text line"}
                      </span>
                    </span>
                    <span className="flex flex-shrink-0 flex-col items-end gap-1">
                      <span className={cn("rounded-full px-2 py-0.5 text-[9px] font-semibold", SOURCE_BADGE_CLASS[s.source])}>
                        {s.source}
                      </span>
                      {s.reason && (
                        <span className="text-[9px] font-medium text-[#94A3B8]">{s.reason}</span>
                      )}
                    </span>
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
