/**
 * True if pathname matches some real page in the app right now — either a
 * static route exactly, or a dynamic ([param]) route with the same segment
 * shape (any single segment in that position, not a specific id). `shapes`
 * comes from knownRoutes.generated.ts, generated fresh from app/ on every
 * build (see scripts/generate-known-routes.js), so this can't itself go
 * stale the way a hand-maintained list would.
 *
 * This is what actually closes the gap a same-workspace-prefix check
 * leaves open: /accounting/chart-of-accounts still starts with "/accounting"
 * (a workspace that's very much still alive) even though that exact page
 * was deleted — only an exact route-shape check catches that.
 *
 * Pure and parameterized (rather than importing the generated constant
 * directly) so it can be unit-tested against small hand-built fixtures,
 * independent of the app's actual current route list.
 */
export function matchesKnownRoute(pathname: string, shapes: string[][]): boolean {
  const candidate = pathname.split("?")[0].replace(/\/+$/, "").split("/").filter(Boolean);
  return shapes.some((shape) => {
    if (shape.length !== candidate.length) return false;
    return shape.every((seg, i) => seg.startsWith(":") || seg === candidate[i]);
  });
}
