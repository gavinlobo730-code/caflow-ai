/**
 * WHETHER A CLIENT SCREEN HAS A SUBJECT TO RENDER, AS A PURE FUNCTION.
 *
 * ⚠️ THIS FILE HAS NO IMPORTS, DELIBERATELY, so a `node --test` guard can load
 * it — the same reason `routeOwnership.ts` was split out of
 * `workspaceConfig.ts`. The decision this makes is the one that could
 * introduce a visible bug (a screen saying "no such client" while it is still
 * loading), so it has to be testable as BEHAVIOUR rather than asserted as a
 * shape of source.
 *
 * `ClientNavContext` re-exports the two names that were already public from
 * there, so every existing importer is untouched.
 */

/**
 * THE ID THE STATIC EXPORT IS BUILT UNDER, WHICH IS NEVER A CLIENT.
 *
 * `output: "export"` pre-renders `/clients/[id]/**` exactly once, under this
 * literal, and Cloudflare 200-rewrites every real client onto that HTML — so
 * the string appears in `useParams()` for every client in the product and in
 * `window.location.pathname` for none of them. Reading it out of the ADDRESS
 * therefore means one specific thing: the visitor is standing on the built
 * shell with no client named at all.
 *
 * It was spelled as a literal in roughly forty files before this. The new code
 * reads the constant; the existing literals are deliberately not swept, since
 * a rename is not in prospect and a forty-file diff would bury this change.
 */
export const PLACEHOLDER_CLIENT_ID = "_placeholder";

/**
 * WHETHER THE ADDRESS NAMES A CLIENT THIS FIRM HAS — SIX ANSWERS, AND THE
 * DIFFERENCES BETWEEN THEM ARE THE WHOLE POINT.
 *
 * `ClientTopBar` used to ask this question privately and kept two of the
 * answers (`client` and `clientLoadFailed`); nothing else could see either, so
 * every screen under `/clients/[id]/**` rendered as though the client were
 * simply slow to arrive. `app/clients/[id]/overview/page.tsx` is the worked
 * example: its loader opens `if (!clientId || clientId === "_placeholder")
 * return;`, so `setLoading(false)` never runs and the page shows its skeleton
 * for ever.
 *
 * - `"off-route"`    the address is not a client route at all. The provider is
 *                    mounted app-wide, so this is most of the product. It is
 *                    also the state the SERVER renders, since the static
 *                    export has no window to read an id out of.
 * - `"unnamed"`      a client route whose id segment is the build placeholder:
 *                    no client is named, so there is nothing to look up and
 *                    nothing failed.
 * - `"resolving"`    a real id, lookup in flight. NOT "absent" — that
 *                    conflation is the one visible bug this could introduce,
 *                    so it is a state of its own and `gateVerdict` renders it.
 * - `"resolved"`     the row is in hand.
 * - `"absent"`       the lookup succeeded and returned no row. Under RLS a
 *                    client belonging to another firm reads as absent, which
 *                    is the honest answer from this firm's side.
 * - `"unavailable"`  the lookup itself failed. Telling a CA their client does
 *                    not exist because the network blipped is a different and
 *                    worse wrong answer than telling them the lookup failed,
 *                    so the two never share a state.
 */
export type ClientResolution =
  | "off-route"
  | "unnamed"
  | "resolving"
  | "resolved"
  | "absent"
  | "unavailable";

/** What the gate does: render the screen, or refuse it with this reason. */
export type GateVerdict = "render" | "unnamed" | "absent" | "unavailable";

/**
 * `/clients/<id>` itself, with no module after it.
 *
 * Counting segments rather than matching a shape, because the id may be a
 * uuid, the build placeholder, or whatever somebody pasted.
 */
export function isClientFrontDoor(pathname: string): boolean {
  return pathname.split("/").filter(Boolean).length <= 2;
}

/**
 * ⚠️ `resolving` RENDERS, AND SO DOES `off-route`. The gate decides only
 * whether there is a subject to load; the screens keep their own loading and
 * error states. That is what makes it inert on the path every CA actually
 * walks — a real client's screens behave exactly as they did.
 *
 * The front door is the one place `unnamed` renders: `/clients/<id>` already
 * answers an unnamed id by returning to the client list, a redirect the smoke
 * walk pins as correct, and refusing here would replace a working redirect
 * with a dead end. A real id naming no client is refused on both, front door
 * included — a module grid over a client that is not there is the same defect
 * one level up.
 */
export function gateVerdict(resolution: ClientResolution, pathname: string): GateVerdict {
  if (resolution === "absent") return "absent";
  if (resolution === "unavailable") return "unavailable";
  if (resolution === "unnamed" && !isClientFrontDoor(pathname)) return "unnamed";
  return "render";
}

/**
 * THE ADDRESS THE VISITOR ACTUALLY ASKED FOR.
 *
 * Rebuilt from the resolved id plus the tail of the router's pathname rather
 * than read off `window.location`: under Cloudflare's 200-rewrite the router
 * holds the build placeholder in the ID segment and the real thing in every
 * segment after it, and `clientId` is already the real id. Reading the
 * location in an effect would do the same job one render later, for nothing.
 *
 * Showing it is the honest thing for somebody holding a dead link — it is what
 * they can check or correct. That it also makes forty refusals forty different
 * bodies, and so keeps `pnpm smoke`'s duplicate-body check meaningful without
 * moving its threshold, is a side effect rather than the reason.
 */
export function refusalAddress(clientId: string, pathname: string): string {
  const tail = pathname.split("/").slice(3).filter(Boolean).join("/");
  return `/clients/${clientId}${tail ? `/${tail}` : ""}`;
}

/**
 * The module segment of a client route, or "" on the front door.
 *
 * Position 3, the way `ClientTopBar` reads it, and deliberately NOT
 * `getSectionForPathname`, which defaults to "overview": on the front door
 * there is no module, and naming one there would describe a screen the visitor
 * is not standing on. Under the rewrite the ID segment is the placeholder and
 * every segment after it is real, so position 3 is safe.
 */
export function clientSectionSegment(pathname: string): string {
  return pathname.split("/")[3] ?? "";
}
