"use client";
import * as React from "react";
import { EntityLookup } from "./EntityLookup";

/** Minimal vendor shape the lookup needs (structural — extra fields ignored). */
export interface VendorLike {
  id: string;
  name: string;
  gstin?: string | null;
  pan?: string | null;
  email?: string | null;
  phone?: string | null;
  tds_section?: string | null;
  state_code?: string | null;
  outstanding_paise?: number | null;
}

const fmtOutstanding = (p?: number | null) =>
  p == null || p === 0 ? "" : `₹${(Math.abs(p) / 100).toLocaleString("en-IN")} due`;

/**
 * Searchable vendor picker — drop-in for the old `<select>` (id-controlled).
 * Searches name, GSTIN, PAN, email and phone; `onSelect` surfaces the full row
 * so the caller can auto-fill TDS section / payment terms / GST state.
 */
export function VendorLookup(props: {
  vendors: VendorLike[];
  value: string;
  onChange: (id: string) => void;
  onSelect?: (v: VendorLike | null) => void;
  fetchOptions?: (q: string) => Promise<VendorLike[]>;
  recent?: VendorLike[];
  disabled?: boolean;
  clearable?: boolean;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  className?: string;
  placeholder?: string;
  onCreate?: (label: string) => void | Promise<void>;
}) {
  const { vendors, ...rest } = props;
  return (
    <EntityLookup<VendorLike>
      items={vendors}
      getId={(v) => v.id}
      getLabel={(v) => v.name}
      getSecondary={(v) => [v.gstin, fmtOutstanding(v.outstanding_paise)].filter(Boolean).join(" · ") || undefined}
      getSearchFields={(v) => [v.name, v.gstin ?? "", v.pan ?? "", v.email ?? "", v.phone ?? ""]}
      placeholder={props.placeholder ?? "Select vendor…"}
      searchPlaceholder="Search name, GSTIN, PAN…"
      emptyText="No vendors found"
      {...rest}
    />
  );
}
