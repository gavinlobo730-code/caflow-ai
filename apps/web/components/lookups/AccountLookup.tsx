"use client";
import * as React from "react";
import { EntityLookup } from "./EntityLookup";

/**
 * Chart-of-accounts row. Field names vary across the app (account_code vs code,
 * account_name vs name, account_type vs type), so the lookup reads either.
 */
export interface AccountLike {
  id?: string | null;
  code?: string | null;
  account_code?: string | null;
  name?: string | null;
  account_name?: string | null;
  type?: string | null;
  account_type?: string | null;
  account_subtype?: string | null;
}

const codeOf = (a: AccountLike) => a.account_code ?? a.code ?? "";
const nameOf = (a: AccountLike) => a.account_name ?? a.name ?? "";
const typeOf = (a: AccountLike) => a.account_type ?? a.type ?? "";

/**
 * Searchable Chart-of-Accounts picker — drop-in for the old `<select>`.
 * Searches account name and code; rows show "code · type". `idField` selects
 * whether the controlled value is the account id (default) or its code, matching
 * the call site's existing state.
 */
export function AccountLookup(props: {
  accounts: AccountLike[];
  value: string;
  onChange: (id: string) => void;
  onSelect?: (a: AccountLike | null) => void;
  /** Which field the controlled value uses. Default "id"; some screens key by code. */
  idField?: "id" | "code";
  fetchOptions?: (q: string) => Promise<AccountLike[]>;
  recent?: AccountLike[];
  disabled?: boolean;
  clearable?: boolean;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  className?: string;
  placeholder?: string;
}) {
  const { accounts, idField = "id", ...rest } = props;
  const getId = (a: AccountLike) => (idField === "code" ? codeOf(a) : a.id ?? codeOf(a));
  return (
    <EntityLookup<AccountLike>
      items={accounts}
      getId={getId}
      getLabel={(a) => nameOf(a) || codeOf(a)}
      getSecondary={(a) => [codeOf(a), typeOf(a)].filter(Boolean).join(" · ") || undefined}
      getSearchFields={(a) => [nameOf(a), codeOf(a), typeOf(a)]}
      placeholder={props.placeholder ?? "Select account…"}
      searchPlaceholder="Search account name or code…"
      emptyText="No accounts found"
      {...rest}
    />
  );
}
