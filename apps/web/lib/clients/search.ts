import type { Client } from "@/lib/types";

// Every client field the Clients search scans. Each value is normalized
// null-safely (see `normalize`), so a null / undefined / empty / non-string
// field is simply skipped — the search can never throw on missing data.
//
// This matters because several of these columns are nullable in the database
// (PAN became optional in migration 133; gstin/email/mobile/address/city/state
// have always been optional), even where older TypeScript types implied a value
// was always present. Normalizing here is the single source of truth so the
// page never calls a string method on null.
const SEARCHABLE_FIELDS = [
  "client_name", // company / contact name
  "pan",
  "gstin",
  "email",
  "mobile", // phone
  "address_line1",
  "address_line2",
  "city",
  "state",
  "pincode",
] as const;

/**
 * Lower-case a value only when it is actually a string; anything else
 * (null, undefined, number, object) collapses to "" and is therefore ignored.
 */
function normalize(value: unknown): string {
  return typeof value === "string" ? value.toLowerCase() : "";
}

/**
 * True when the query is empty or matches any searchable field of the client.
 * Never throws, regardless of which fields are null/undefined/empty.
 */
export function clientMatchesQuery(client: Client, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  const record = client as unknown as Record<string, unknown>;
  return SEARCHABLE_FIELDS.some((field) => normalize(record[field]).includes(q));
}

/**
 * Null-safe client search. An empty or whitespace-only query returns every
 * client unchanged. Used by the Clients page so a missing PAN/GSTIN/etc. can
 * never crash the page.
 */
export function filterClients(clients: Client[], query: string): Client[] {
  if (query.trim() === "") return clients;
  return clients.filter((client) => clientMatchesQuery(client, query));
}
