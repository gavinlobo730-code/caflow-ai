"use client";
import * as React from "react";
import { EntityLookup } from "./EntityLookup";

/**
 * CA client row. Name lives under different keys across the app
 * (name / client_name / legal_name / business_name), so the lookup reads any.
 */
export interface ClientLike {
  id: string;
  name?: string;
  client_name?: string;
  legal_name?: string;
  business_name?: string;
  pan?: string | null;
  gstin?: string | null;
}

const nameOf = (c: ClientLike) =>
  c.name ?? c.client_name ?? c.legal_name ?? c.business_name ?? "";

/**
 * Searchable CA-client picker — drop-in for the old `<select>` (id-controlled).
 * Recurs across the app (tasks, documents, reports, tax modules…); searches
 * client name, PAN and GSTIN.
 */
export function ClientLookup(props: {
  clients: ClientLike[];
  value: string;
  onChange: (id: string) => void;
  onSelect?: (c: ClientLike | null) => void;
  fetchOptions?: (q: string) => Promise<ClientLike[]>;
  recent?: ClientLike[];
  disabled?: boolean;
  clearable?: boolean;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  className?: string;
  placeholder?: string;
}) {
  const { clients, ...rest } = props;
  return (
    <EntityLookup<ClientLike>
      items={clients}
      getId={(c) => c.id}
      getLabel={nameOf}
      getSecondary={(c) => [c.pan, c.gstin].filter(Boolean).join(" · ") || undefined}
      getSearchFields={(c) => [nameOf(c), c.pan ?? "", c.gstin ?? ""]}
      placeholder={props.placeholder ?? "Select client…"}
      searchPlaceholder="Search client, PAN, GSTIN…"
      emptyText="No clients found"
      {...rest}
    />
  );
}
