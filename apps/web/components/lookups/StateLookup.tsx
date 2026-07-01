"use client";
import * as React from "react";
import { EntityLookup } from "./EntityLookup";
import { INDIAN_STATES, type IndianState } from "@/lib/constants/indianStates";

/**
 * Searchable Indian-state (place-of-supply) picker — drop-in for the old
 * `<select>` of 30+ states. The controlled value is the 2-digit GST state code
 * ("" = none); search by code OR name reduces mis-selection. Callers may pass
 * their own `states` list; otherwise the canonical GST list is used.
 */
export function StateLookup(props: {
  value: string;
  onChange: (code: string) => void;
  states?: IndianState[];
  disabled?: boolean;
  clearable?: boolean;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  placeholder?: string;
}) {
  const { states = INDIAN_STATES, ...rest } = props;
  return (
    <EntityLookup<IndianState>
      items={states}
      getId={(s) => s.code}
      getLabel={(s) => `${s.code} — ${s.name}`}
      getSearchFields={(s) => [s.code, s.name]}
      placeholder={props.placeholder ?? "Select state…"}
      searchPlaceholder="Search state or code…"
      emptyText="No matching state"
      {...rest}
    />
  );
}
