"use client";
import * as React from "react";
import { EntityLookup } from "./EntityLookup";

/** Minimal customer shape the lookup needs (structural — extra fields ignored). */
export interface CustomerLike {
  id: string;
  name: string;
  gstin?: string | null;
  pan?: string | null;
  email?: string | null;
  phone?: string | null;
  state_code?: string | null;
  outstanding_paise?: number | null;
}

const fmtOutstanding = (p?: number | null) =>
  p == null || p === 0 ? "" : `₹${(Math.abs(p) / 100).toLocaleString("en-IN")} due`;

/**
 * Searchable customer picker — a drop-in for the old `<select>` (id-controlled).
 * Searches name, GSTIN, PAN, email and phone; rich rows show GSTIN / amount due.
 * `onSelect` surfaces the full row so the caller can auto-fill GST state / terms.
 */
export function CustomerLookup(props: {
  customers: CustomerLike[];
  value: string;
  onChange: (id: string) => void;
  onSelect?: (c: CustomerLike | null) => void;
  fetchOptions?: (q: string) => Promise<CustomerLike[]>;
  recent?: CustomerLike[];
  disabled?: boolean;
  clearable?: boolean;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  className?: string;
  placeholder?: string;
  onCreate?: (label: string) => void | Promise<void>;
}) {
  const { customers, ...rest } = props;
  return (
    <EntityLookup<CustomerLike>
      items={customers}
      getId={(c) => c.id}
      getLabel={(c) => c.name}
      getSecondary={(c) => [c.gstin, fmtOutstanding(c.outstanding_paise)].filter(Boolean).join(" · ") || undefined}
      getSearchFields={(c) => [c.name, c.gstin ?? "", c.pan ?? "", c.email ?? "", c.phone ?? ""]}
      placeholder={props.placeholder ?? "Select customer…"}
      searchPlaceholder="Search name, GSTIN, PAN…"
      emptyText="No customers found"
      {...rest}
    />
  );
}
