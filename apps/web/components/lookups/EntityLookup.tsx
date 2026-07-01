"use client";
import * as React from "react";
import { Combobox } from "@/components/ui/combobox";

/**
 * id-string-controlled adapter over <Combobox> — the shared base for the entity
 * wrappers (Customer/Vendor/Account/Client). It preserves the exact contract of
 * the <select> it replaces: `value` is the selected id ("" = none) and
 * `onChange` fires with the id, so a page swap needs no state changes. The full
 * object is surfaced via `onSelect` for dependent auto-fill (GST state, terms…).
 *
 * Sync by default (searches the already-loaded `items`, zero new fetches → no
 * regression). Pass `fetchOptions` to switch to debounced server search with the
 * identical UI; a small `selectedItem` cache keeps the chosen label visible even
 * when it is not in the current result page.
 */
export interface EntityLookupProps<T> {
  /** Already-loaded rows (sync search source). */
  items: T[];
  /** Selected id; "" means nothing selected. */
  value: string;
  onChange: (id: string) => void;
  /** Full selected row (or null) — for dependent auto-fill. */
  onSelect?: (item: T | null) => void;
  getId: (o: T) => string;
  getLabel: (o: T) => string;
  getSecondary?: (o: T) => string | undefined;
  getSearchFields?: (o: T) => string[];
  /** Async server search (identical UI). Overrides client-side search when set. */
  fetchOptions?: (query: string) => Promise<T[]>;
  recent?: T[];
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  clearable?: boolean;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  className?: string;
  emptyText?: string;
  onCreate?: (label: string) => void | Promise<void>;
  createLabel?: (q: string) => string;
  renderOption?: (o: T, ctx: { selected: boolean }) => React.ReactNode;
  minChars?: number;
}

export function EntityLookup<T>(props: EntityLookupProps<T>) {
  const { items, value, onChange, onSelect, getId, fetchOptions, ...rest } = props;

  // Remember the last chosen object so async pickers keep the label after the
  // result set changes; sync pickers resolve straight from `items`.
  const [cache, setCache] = React.useState<T | null>(null);
  const resolved = React.useMemo(() => {
    const fromItems = items.find((i) => getId(i) === value);
    if (fromItems) return fromItems;
    if (cache && getId(cache) === value) return cache;
    return null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, value, cache]);

  const handleChange = (v: T | T[] | null) => {
    const o = (Array.isArray(v) ? v[0] : v) ?? null;
    setCache(o);
    onChange(o ? getId(o) : "");
    onSelect?.(o);
  };

  return (
    <Combobox<T>
      {...rest}
      value={resolved}
      onChange={handleChange}
      options={fetchOptions ? undefined : items}
      fetchOptions={fetchOptions}
      getOptionId={getId}
    />
  );
}
