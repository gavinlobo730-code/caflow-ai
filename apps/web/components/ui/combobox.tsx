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
  debounceMs?: number;
  minChars?: number;
  /** Enable the "+ Create …" row; receives the current query. */
  onCreate?: (label: string) => void | Promise<void>;
  createLabel?: (q: string) => string;
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
}

const SIZE = {
  sm: "px-2 py-1 text-xs",
  md: "px-3 py-1.5 text-xs",
} as const;

export function Combobox<T>(props: ComboboxProps<T>) {
  const {
    value,
    onChange,
    multiple = false,
    options,
    fetchOptions,
    recent,
    debounceMs,
    minChars,
    onCreate,
    createLabel,
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
    getOptionId,
    getLabel,
    getSecondary,
    getSearchFields,
  } = props;

  const reactId = React.useId();
  const baseId = id ?? reactId;
  const listboxId = `${baseId}-listbox`;
  const inputId = `${baseId}-input`;

  const [open, setOpen] = React.useState(false);
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const listRef = React.useRef<HTMLDivElement>(null);

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
      {/* Trigger — looks like the app's <select> field. */}
      <button
        type="button"
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
          "flex w-full items-center justify-between gap-2 rounded-lg border border-[#E2E8F0] bg-white text-left text-[#334155] transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]",
          SIZE[size],
          className,
        )}
      >
        <span className={cn("truncate", !triggerLabel && "text-[#94A3B8]")}>
          {!multiple && selectedArr[0] && renderTrigger
            ? renderTrigger(selectedArr[0])
            : triggerLabel || placeholder}
        </span>
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
      </button>

      {open && (
        <div
          className={cn(
            "absolute z-40 mt-1 w-full overflow-hidden rounded-lg border border-[#E2E8F0] bg-white shadow-lg",
            panelDensity === "spacious" ? "min-w-[26rem]" : "min-w-[16rem]",
          )}
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
            {loading && <Loader2 size={13} className="flex-shrink-0 animate-spin text-[#94A3B8]" />}
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
                {loading ? "Searching…" : emptyText}
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
