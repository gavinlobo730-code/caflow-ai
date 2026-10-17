"use client";
import * as React from "react";
import { EntityLookup } from "./EntityLookup";
import { INDIAN_STATES, PLACE_OF_SUPPLY_STATES, type IndianState } from "@/lib/constants/indianStates";

/**
 * Searchable Indian-state (place-of-supply) picker — drop-in for the old
 * `<select>` of 30+ states. The controlled value is the 2-digit GST state code
 * ("" = none); search by code OR name reduces mis-selection. The canonical GST
 * list is used. `placeOfSupply` adds 96 (Other Country, an export's place of
 * supply) and 97 (Other Territory) for the fields the server accepts them on: a
 * document's place of supply and a customer's state, never a GSTIN's. There is
 * deliberately no `states` prop: a caller passing its own copy is how four
 * state lists came to exist (scripts/there-is-one-state-master.test.ts).
 */
export function StateLookup(props: {
  value: string;
  onChange: (code: string) => void;
  placeOfSupply?: boolean;
  disabled?: boolean;
  clearable?: boolean;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  placeholder?: string;
}) {
  const { placeOfSupply, ...rest } = props;
  const states = placeOfSupply ? PLACE_OF_SUPPLY_STATES : INDIAN_STATES;
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
