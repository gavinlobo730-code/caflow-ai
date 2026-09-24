/**
 * Client-workspace path detection (shared by AppShell). Pure + unit-tested so the
 * invariant it encodes can't silently regress.
 *
 * A "client workspace" path is `/clients/<uuid>` or any sub-path of it. The id
 * MUST be a real UUID: that is exactly what distinguishes a client workspace
 * (where the client layout owns the rails, so AppShell hides its global rails)
 * from firm-level pages that also live under /clients — e.g. `/clients` (the
 * list) and `/clients/documents`. It also means the static-export placeholder
 * (`/clients/_placeholder/…`) is deliberately NOT a workspace: navigation must
 * always resolve a real id (via useParams), never route to the placeholder — if
 * a "_placeholder" URL ever appears, both AppShell's rails and the client
 * layout's rails would render (the "two sidebars" regression).
 */
const CLIENT_UUID_RE =
  /^\/clients\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(\/|$)/i;

export function isClientWorkspacePath(pathname: string): boolean {
  return CLIENT_UUID_RE.test(pathname);
}

/**
 * Where the client switcher sends you: THE SAME SECTION OF A DIFFERENT CLIENT,
 * never the same document.
 *
 * That distinction is the whole rule. A CA reconciling June across four
 * clients wants to land on Bank for the next one, and carrying the WHOLE path
 * would send `/clients/A/sales/invoices/<invoiceId>/edit` to
 * `/clients/B/sales/invoices/<invoiceId>/edit` — B's workspace pointing at A's
 * invoice. Best case a 404; worse, a screen that renders one client's document
 * under another client's name.
 *
 * So exactly one segment travels: the section. That is safe by construction
 * rather than by a list — every one of the 21 first segments under
 * `/clients/:id/` has its own landing page, asserted by
 * `scripts/a-client-switch-lands-on-the-same-section.test.ts`, so the
 * destination always exists.
 *
 * A trailing slash because `next.config.mjs` sets `trailingSlash: true` and
 * the Cloudflare rewrite for a bare path is one of the 43 enumerated rules
 * D10 exists to protect — routing to the slashed form spends none of them.
 */
export function switchClientPath(pathname: string, newClientId: string): string {
  const overview = `/clients/${newClientId}/overview/`;
  if (!isClientWorkspacePath(pathname)) return overview;
  // ["", "clients", "<id>", "<section>", …]
  const section = pathname.split("/")[3] ?? "";
  // A section is a word. Anything uuid-shaped here would mean the path is not
  // the shape this function is reading, so fall back rather than build a URL
  // out of half of somebody else's document id.
  if (!section || !/^[a-z0-9-]+$/i.test(section) || UUID_ONLY_RE.test(section)) return overview;
  return `/clients/${newClientId}/${section}/`;
}

const UUID_ONLY_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
