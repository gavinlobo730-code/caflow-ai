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
