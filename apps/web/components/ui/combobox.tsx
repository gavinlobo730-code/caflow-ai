"use client";
import * as React from "react";
import { Check, ChevronsUpDown, Loader2, Plus, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCombobox } from "@/lib/combobox/useCombobox";
import type { ComboboxCore } from "@/lib/combobox/types";

/**
 * Shared searchable combobox — a drop-in, accessible replacement for a long
 * <select>. One component, two data modes (identical UI):
 *   • sync   — pass `options`; search/rank runs client-side.
 *   • async  — pass `fetchOptions`; a debounced server search backs it.
 *
 * Trigger looks like the app's select field; opening reveals a search box + a
 * WAI-ARIA listbox with keyboard navigation, rich rows, recent-first, loading/
 * empty/error states and an optional "+ Create" row. Entity wrappers
 * (CustomerLookup, VendorLookup, …) are thin id-string-controlled adapters.
 */
export interface ComboboxProps<T> extends ComboboxCore<T> {
  value: T | T[] | null;
  onChange: (v: T | T[] | null) => void;
  multiple?: boolean;
  /** Sync data source (already loaded). */
  options?: T[];
  /** Async data source (debounced server search). Takes precedence when set. */
  fetchOptions?: (query: string) => Promise<T[]>;
  /** Shown before typing (recent / frequent / favourites). */
  recent?: T[];
  /**
   * True while the caller's own `recent` fetch is still in flight. Without
   * this, opening the picker before that fetch resolves shows `recent` as an
   * empty array indistinguishable from "genuinely nothing here" — the panel
   * asserts `emptyText` (e.g. "No Product/Service Found") even though data
   * exists and is simply still loading (most visible on a cold backend
   * start). Wire this to the same loading flag the caller uses for its
   * `recent` fetch so the panel shows a neutral loading state instead of a
   * false negative.
   */
  recentLoading?: boolean;
  debounceMs?: number;
  minChars?: number;
  /** Enable the "+ Create …" row; receives the current query. */
  onCreate?: (label: string) => void | Promise<void>;
  createLabel?: (q: string) => string;
  /**
   * When set, the "+ Create …" action is also offered in the empty-results
   * panel BEFORE the user types anything (e.g. a brand-new client with no
   * Product/Service catalogue yet) — not just after a no-match search.
   * Without this, `onCreate` only surfaces once the query is non-empty, so
   * an entirely empty list would otherwise show no way in at all.
   */
  emptyCreateLabel?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  /** Accessible label (associate an external <label> via `id` too). */
  ariaLabel?: string;
  id?: string;
  /** Extra classes for the trigger button. */
  className?: string;
  size?: "sm" | "md";
  /** Show a clear (×) affordance on the trigger (single-select). */
  clearable?: boolean;
  emptyText?: string;
  /** Custom row renderer (defaults to label + secondary). */
  renderOption?: (o: T, ctx: { selected: boolean }) => React.ReactNode;
  /**
   * Custom trigger content when a single value is selected (e.g. a compact
   * colored chip instead of the plain label). Ignored while nothing is
   * selected or in multi-select mode — the default label/placeholder always
   * renders then. The trigger button itself (click/keyboard/ARIA) is
   * unchanged; only the content inside it is swapped.
   */
  renderTrigger?: (o: T) => React.ReactNode;
  /**
   * "spacious" widens the popup and gives rows more room (taller max-height,
   * more padding, full-text wrapping instead of truncation) for a lookup
   * meant to be scanned like a command palette rather than a short <select>
   * replacement. Defaults to the original compact sizing everywhere it isn't
   * passed, so existing callers (CustomerLookup, StateLookup, …) are unaffected.
   */
  panelDensity?: "compact" | "spacious";
  /**
   * "plain" strips the field-style chrome (border, background, chevron) so
   * the trigger reads as inline text plus an action (e.g. a "Change" chip
   * via `renderTrigger`) rather than a <select>-like control — used for the
   * Sales Invoice HSN/SAC cell, which auto-fills from the Product/Service
   * pick and should not look like an always-open dropdown. Defaults to
   * "field", the original styling, everywhere it isn't passed.
   */
  chrome?: "field" | "plain";
}

/** Imperative handle for callers that need to move focus onto a Combobox
 * from outside (e.g. spreadsheet-style Tab navigation creating a new invoice
 * row and focusing its Product/Service picker). Ref-forwarding only — no
 * other imperative surface is exposed. */
export interface ComboboxHandle {
  focus: () => void;
}

const SIZE = {
  sm: "px-2 py-1 text-xs",
  md: "px-3 py-1.5 text-xs",
} as const;

// Matches the popup's former min-w-[16rem]/[26rem] Tailwind classes, now
// applied in JS alongside the trigger's own width (see updateCoords below).
const DENSITY_MIN_WIDTH_PX = { compact: 256, spacious: 416 } as const;

function ComboboxInner<T>(props: ComboboxProps<T>, ref: React.ForwardedRef<ComboboxHandle>) {
  const {
    value,
    onChange,
    multiple = false,
    options,
    fetchOptions,
    recent,
    recentLoading = false,
    debounceMs,
    minChars,
    onCreate,
    createLabel,
    emptyCreateLabel,
    placeholder = "Select…",
    searchPlaceholder = "Search…",
    disabled,
    ariaLabel,
    id,
    className,
    size = "md",
    clearable = false,
    emptyText = "No matches",
    renderOption,
    renderTrigger,
    panelDensity = "compact",
    chrome = "field",
    getOptionId,
    getLabel,
    getSecondary,
    getSearchFields,
  } = props;
  const plain = chrome === "plain";

  const reactId = React.useId();
  const baseId = id ?? reactId;
  const listboxId = `${baseId}-listbox`;
  const inputId = `${baseId}-input`;

  const [open, setOpen] = React.useState(false);
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useImperativeHandle(ref, () => ({
    focus: () => triggerRef.current?.focus(),
  }), []);

  const combo = useCombobox<T>({
    options,
    fetchOptions,
    recent,
    getOptionId,
    getLabel,
    getSecondary,
    getSearchFields,
    onCreate,
    debounceMs,
    minChars,
  });
  const { query, setQuery, results, loading, error, highlighted, setHighlighted, showCreate, retry } = combo;

  // Before the query reaches minChars, `results` is just `recent` (see
  // useCombobox) — so while the caller's own recent-fetch is still in
  // flight, treat it exactly like an in-flight search for display purposes
  // (loading text/spinner, no premature "+ Create"/emptyText).
  const showingRecent = !!fetchOptions && query.trim().length < (minChars ?? 1);
  const recentPending = showingRecent && recentLoading;
  const busy = loading || recentPending;

  // Selection helpers (works for single value or an array).
  const selectedArr: T[] = React.useMemo(
    () =>
      multiple
        ? Array.isArray(value) ? value : []
        : value != null && !Array.isArray(value) ? [value] : [],
    [multiple, value],
  );
  const selectedIds = new Set(selectedArr.map(getOptionId));
  const isSel = (o: T) => selectedIds.has(getOptionId(o));

  const triggerLabel = React.useMemo(() => {
    if (multiple) {
      if (selectedArr.length === 0) return "";
      if (selectedArr.length === 1) return getLabel(selectedArr[0]);
      return `${selectedArr.length} selected`;
    }
    return selectedArr[0] ? getLabel(selectedArr[0]) : "";
  }, [multiple, selectedArr, getLabel]);

  // ── open / close / focus / click-away ──────────────────────────────────────
  const close = React.useCallback(() => {
    setOpen(false);
    setQuery("");
  }, [setQuery]);

  React.useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, close]);

  // Keep the highlighted row scrolled into view.
  React.useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${highlighted}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [highlighted, open, results]);

  // The popup is positioned via fixed coordinates computed from the trigger's
  // own bounding rect, NOT CSS `absolute` relative to the trigger's DOM
  // parent — a plain `absolute` popup gets clipped (and forces a stray
  // scrollbar) by any scrollable ancestor, e.g. the invoice line-items
  // table's own `overflow-x-auto` wrapper. `position: fixed` escapes that
  // clipping entirely (its containing block is the viewport, not the
  // scrolling ancestor) as long as no ancestor sets transform/filter/
  // perspective, which none here do.
  const [coords, setCoords] = React.useState<{ top: number; left: number; width: number } | null>(null);
  const updateCoords = React.useCallback(() => {
    const r = wrapRef.current?.getBoundingClientRect();
    if (!r) return;
    const width = Math.max(r.width, DENSITY_MIN_WIDTH_PX[panelDensity]);
    const left = Math.min(r.left, Math.max(8, window.innerWidth - width - 8));
    setCoords({ top: r.bottom + 4, left, width });
  }, [panelDensity]);
  React.useLayoutEffect(() => {
    if (!open) { setCoords(null); return; }
    updateCoords();
    // Reposition on resize and on scroll of ANY ancestor (capture:true —
    // scroll doesn't bubble), so the popup tracks the trigger instead of
    // drifting out of place while it's open.
    window.addEventListener("resize", updateCoords);
    document.addEventListener("scroll", updateCoords, true);
    return () => {
      window.removeEventListener("resize", updateCoords);
      document.removeEventListener("scroll", updateCoords, true);
    };
  }, [open, updateCoords]);

  const commit = React.useCallback(
    (o: T) => {
      if (multiple) {
        const exists = selectedIds.has(getOptionId(o));
        const next = exists
          ? selectedArr.filter((s) => getOptionId(s) !== getOptionId(o))
          : [...selectedArr, o];
        onChange(next);
        setQuery("");
        inputRef.current?.focus();
      } else {
        onChange(o);
        close();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [multiple, selectedArr, onChange, getOptionId, close, setQuery],
  );

  const doCreate = React.useCallback(async () => {
    if (!onCreate) return;
    await onCreate(query.trim());
    if (!multiple) close();
    else setQuery("");
  }, [onCreate, query, multiple, close, setQuery]);

  const createIdx = results.length; // create row sits after the last option

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const last = results.length - 1 + (showCreate ? 1 : 0);
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlighted(Math.min(highlighted + 1, Math.max(0, last)));
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlighted(Math.max(highlighted - 1, 0));
        break;
      case "Home":
        e.preventDefault();
        setHighlighted(0);
        break;
      case "End":
        e.preventDefault();
        setHighlighted(Math.max(0, last));
        break;
      case "Enter":
        e.preventDefault();
        if (showCreate && highlighted === createIdx) void doCreate();
        else if (results[highlighted]) commit(results[highlighted]);
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        // Commit the highlighted option, then let focus move on.
        if (results[highlighted] && !multiple) {
          commit(results[highlighted]);
        } else {
          close();
        }
        break;
    }
  };

  const openMenu = () => {
    if (disabled) return;
    setOpen(true);
  };

  const clear = (e: React.MouseEvent) => {
    e.stopPropagation();
    onChange(multiple ? [] : null);
  };

  const defaultCreateLabel = (q: string) => `Create “${q}”`;

  return (
    <div ref={wrapRef} className="relative">
      {/* Trigger — looks like the app's <select> field, unless chrome="plain"
          (the invoice HSN cell), where it reads as inline text + an action. */}
      <button
        type="button"
        ref={triggerRef}
        id={baseId}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={(e) => {
          if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
            e.preventDefault();
            openMenu();
          }
        }}
        className={cn(
          "items-center gap-2 text-left text-[#334155] transition-colors focus:outline-none disabled:cursor-not-allowed disabled:text-[#94A3B8]",
          plain
            ? "inline-flex rounded focus:ring-1 focus:ring-blue-500"
            : cn("flex w-full justify-between rounded-lg border border-[#E2E8F0] bg-white focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC]", SIZE[size]),
          className,
        )}
      >
        <span
          className={cn(
            "truncate",
            !triggerLabel && (plain ? "text-[10px] font-medium text-blue-600" : "text-[#94A3B8]"),
          )}
        >
          {!multiple && selectedArr[0] && renderTrigger
            ? renderTrigger(selectedArr[0])
            : triggerLabel || placeholder}
        </span>
        {!plain && (
          <span className="flex flex-shrink-0 items-center gap-1">
            {clearable && !multiple && selectedArr.length > 0 && !disabled && (
              <span
                role="button"
                tabIndex={-1}
                aria-label="Clear"
                onClick={clear}
                className="rounded p-0.5 text-[#CBD5E1] hover:text-red-500"
              >
                <X size={13} />
              </span>
            )}
            <ChevronsUpDown size={13} className="text-[#94A3B8]" />
          </span>
        )}
      </button>

      {open && coords && (
        <div
          style={{ position: "fixed", top: coords.top, left: coords.left, width: coords.width }}
          className="z-40 overflow-hidden rounded-lg border border-[#E2E8F0] bg-white shadow-lg"
        >
          {/* Search box */}
          <div className="flex items-center gap-2 border-b border-[#F1F5F9] px-2.5 py-2">
            <Search size={13} className="flex-shrink-0 text-[#94A3B8]" />
            <input
              ref={inputRef}
              id={inputId}
              role="combobox"
              aria-expanded="true"
              aria-controls={listboxId}
              aria-autocomplete="list"
              aria-activedescendant={
                results[highlighted]
                  ? `${baseId}-opt-${highlighted}`
                  : showCreate && highlighted === createIdx
                    ? `${baseId}-create`
                    : undefined
              }
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={searchPlaceholder}
              autoComplete="off"
              className="w-full bg-transparent text-xs text-[#334155] placeholder:text-[#94A3B8] focus:outline-none"
            />
            {busy && <Loader2 size={13} className="flex-shrink-0 animate-spin text-[#94A3B8]" />}
          </div>

          {/* Results */}
          <div
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-label={ariaLabel}
            className={cn("overflow-y-auto py-1", panelDensity === "spacious" ? "max-h-[28rem]" : "max-h-64")}
          >
            {error ? (
              <div className="px-3 py-3 text-center text-[11px] text-red-600">
                {error}.{" "}
                <button type="button" onClick={retry} className="underline hover:text-red-700">
                  Retry
                </button>
              </div>
            ) : results.length === 0 && !showCreate ? (
              <div className="px-3 py-3 text-center text-[11px] text-[#94A3B8]">
                <p>{busy ? "Loading…" : emptyText}</p>
                {/* Offered before typing when emptyCreateLabel is set (an
                    entirely empty list, e.g. a new client's catalogue), or
                    once a query exists even below minChars — either way,
                    onCreate must never be reachable ONLY via a 2+ character
                    search with no visible entry point. Suppressed while the
                    recent-fetch is still in flight so it doesn't flash a
                    "create new" affordance for an item that already exists
                    and simply hasn't loaded yet. */}
                {!busy && onCreate && (emptyCreateLabel != null || query.trim().length > 0) && (
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => void doCreate()}
                    className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700"
                  >
                    <Plus size={13} className="flex-shrink-0" />
                    {emptyCreateLabel ?? (createLabel ?? defaultCreateLabel)(query.trim())}
                  </button>
                )}
              </div>
            ) : (
              <>
                {results.map((o, i) => {
                  const selected = isSel(o);
                  const active = i === highlighted;
                  return (
                    <div
                      key={getOptionId(o)}
                      id={`${baseId}-opt-${i}`}
                      data-idx={i}
                      role="option"
                      aria-selected={selected}
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setHighlighted(i)}
                      onClick={() => commit(o)}
                      className={cn(
                        "flex cursor-pointer items-center justify-between gap-2",
                        panelDensity === "spacious" ? "px-3.5 py-2.5" : "px-3 py-1.5",
                        active ? "bg-[#EFF6FF]" : "hover:bg-[#F8FAFC]",
                      )}
                    >
                      {renderOption ? (
                        renderOption(o, { selected })
                      ) : (
                        <span className="min-w-0">
                          <span className="block truncate text-xs text-[#1E293B]">{getLabel(o)}</span>
                          {getSecondary?.(o) && (
                            <span className="block truncate text-[10px] text-[#94A3B8]">
                              {getSecondary(o)}
                            </span>
                          )}
                        </span>
                      )}
                      {selected && <Check size={13} className="flex-shrink-0 text-blue-600" />}
                    </div>
                  );
                })}

                {showCreate && (
                  <div
                    id={`${baseId}-create`}
                    data-idx={createIdx}
                    role="option"
                    aria-selected={false}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setHighlighted(createIdx)}
                    onClick={() => void doCreate()}
                    className={cn(
                      "flex cursor-pointer items-center gap-1.5 border-t border-[#F1F5F9] px-3 py-1.5 text-xs text-blue-600",
                      highlighted === createIdx ? "bg-[#EFF6FF]" : "hover:bg-[#F8FAFC]",
                    )}
                  >
                    <Plus size={13} className="flex-shrink-0" />
                    <span className="truncate">{(createLabel ?? defaultCreateLabel)(query.trim())}</span>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// React.forwardRef erases the generic <T> on a plain assignment; cast back to
// a generic call signature so existing `<Combobox<Foo> .../>` call sites
// (with or without a ref) keep their per-caller type inference.
export const Combobox = React.forwardRef(ComboboxInner) as <T>(
  props: ComboboxProps<T> & { ref?: React.ForwardedRef<ComboboxHandle> },
) => React.ReactElement | null;
