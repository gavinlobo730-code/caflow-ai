/**
 * Where each section of the morning digest leads (ai-25).
 *
 * The VOCABULARY is the server's — `domain/practice/digest.ITEM_KEYS` — and the
 * ROUTES are the browser's, because which screen opens is a fact about Next.js
 * paths the backend cannot hold. `ledger → document` is split the same way
 * (`lib/accounting/sourceDocument.ts`), and for the same reason it is pinned FROM
 * THE PYTHON SIDE: `tests/test_the_practice_digest_is_built_from_the_existing_
 * checks.py` reads this file and asserts every key the server can emit is routed
 * here, and that each route names a screen that exists. A guard written in
 * `apps/web` would assert this map against a copy of itself.
 *
 * A key the map does not know falls back to the client's Overview and no section
 * link — never a raw key shown to a CA, and never a dead link.
 */

export interface DigestRoute {
  /** The firm-level screen for the whole section, or null where there is none —
   *  there is no firm-wide Verify Books screen, and inventing a link to one would
   *  send a CA somewhere that cannot show what the line said. */
  section: string | null;
  /** The screen for ONE client's share of the section. Deep-links to a tab by
   *  query parameter, never a new dynamic route (decision D10). */
  client: (clientId: string) => string;
}

export const DIGEST_ROUTES: Record<string, DigestRoute> = {
  filings_overdue: { section: "/deadlines", client: (id) => `/clients/${id}/compliance` },
  filings_due_soon: { section: "/deadlines", client: (id) => `/clients/${id}/compliance` },
  tasks_overdue: { section: "/tasks", client: (id) => `/clients/${id}/tasks` },
  books_findings: {
    section: null,
    client: (id) => `/clients/${id}/accounting?tab=verify-books`,
  },
};

export function digestClientHref(key: string, clientId: string): string {
  return (DIGEST_ROUTES[key]?.client ?? ((id: string) => `/clients/${id}/overview`))(clientId);
}

export function digestSectionHref(key: string): string | null {
  return DIGEST_ROUTES[key]?.section ?? null;
}
