#!/usr/bin/env node
/**
 * Regenerates public/_redirects from the real app/ route tree, so a
 * Cloudflare Pages rewrite rule can never silently drift from the pages
 * that actually exist. Two failure modes this closes:
 *   - a page is added under a dynamic-segment route (e.g. a new
 *     /clients/[id]/<section>) but nobody remembers to hand-add its rule
 *     -> that page 404s in production forever, while working fine in dev;
 *   - a page is deleted but its rule isn't, leaving a dead rewrite that
 *     just adds noise (harmless, but a sign nothing reconciles this file).
 *
 * Walks every page.tsx under app/; any route whose path passes through at
 * least one Next.js dynamic segment ([name]) needs Cloudflare's 200-rewrite
 * to the pre-rendered `_placeholder` shell (see the matching
 * generateStaticParams() in that segment's layout.tsx).
 *
 * RULE-COUNT BUDGET (important — do not regress this): Cloudflare Pages
 * caps the number of DYNAMIC (":name"/"*" placeholder) rules in _redirects
 * at 100. A naive one-rule-per-shape-per-page scheme blew through that cap
 * once this app grew past ~35 dynamic pages (39 pages x 4 shapes = 156
 * rules) — rules past position 100 in the file are silently ignored, which
 * is exactly what caused the "whole client workspace 404s" regression this
 * comment is here to prevent from recurring. Each page needs a rewrite for
 * 4 request shapes (trailingSlash:true, plus Next's RSC flight-payload
 * fetch — see the formatPair-equivalent logic below for why both a
 * trailing-slash and a bare form of each exist):
 *   1. /path            (bare)           -> needs a trailing "/" appended
 *   2. /path/           (trailing slash) -> straight copy, no transform
 *   3. /path/index.txt  (RSC payload)    -> straight copy, no transform
 *   4. /path.txt        (bare RSC)       -> needs "/index" inserted before ".txt"
 * Shapes 2 and 3 need NO transform beyond substituting "_placeholder" for
 * each dynamic segment — so instead of one rule PER PAGE for each, every
 * page sharing the same "splat-safe prefix" (the path up to and including
 * its LAST dynamic segment — see splatSafePrefix()) shares ONE splat rule
 * that covers both shapes for every page under it, including pages added
 * later with no regeneration needed. Only shapes 1 and 4 truly need a
 * transform Cloudflare's _redirects can't express via a wildcard, so those
 * stay enumerated one rule per page. This took 39 pages from 156 rules down
 * to ~83 (78 enumerated + 5 splats), with headroom for the app to keep
 * growing before hitting the cap again.
 *
 * One more wrinkle: a dynamic segment's placeholder (":invoiceId") matches
 * ANY literal value at that position, including a STATIC sibling route's
 * own segment (e.g. .../invoices/new is a sibling of .../invoices/:invoiceId
 * — "new" satisfies ":invoiceId" just as readily as a real id). Left alone,
 * the deeper group's splat (tried first, being more specific) would shadow
 * the static sibling, rewriting its requests as if "new" were a real
 * invoiceId. buildRedirectsFile detects exactly this (a shallower-group
 * route whose path still structurally matches a DEEPER group's pattern) and
 * gives that ONE route its OWN single-member splat group, keyed by its full
 * path instead of its natural (too-shallow) prefix — covering its
 * trailing-slash/RSC shapes without falling back to full 4-shape
 * enumeration, as long as nothing nests under it (true of every shadowed
 * route so far — "new"/"xbrl" leaves). Every other route sharing the deeper
 * group's splat (e.g. "edit" under :invoiceId) is unaffected and stays
 * splat-covered.
 *
 * Ordering (first-match-wins) is load-bearing in three ways:
 *   - EVERY enumerated (bare / bare-RSC) rule is listed before ANY splat
 *     rule. A splat like `/clients/:id/*` also technically matches a bare,
 *     no-trailing-slash request (e.g. `/clients/abc/overview`) — with the
 *     WRONG target (no trailing slash appended) — so the correct enumerated
 *     rule for that exact path must win first.
 *   - Splat rules are sorted deepest-prefix-first among themselves. A
 *     shallow splat like `/clients/:id/*` also matches paths that belong to
 *     a MORE SPECIFIC nested group, e.g. `/clients/:id/sales/invoices/:invoiceId/edit/`
 *     — greedily capturing "sales/invoices/xyz/edit/" and leaking the real
 *     invoiceId into the target instead of "_placeholder". The nested
 *     group's own splat (`/clients/:id/sales/invoices/:invoiceId/*`) must be
 *     tried first so it wins for paths under it.
 *   - On a depth TIE, most-literal-prefix-first (fewest dynamic
 *     placeholders) breaks it. A shadowed leaf's own synthetic group (e.g.
 *     `/clients/:id/sales/invoices/new/*`, 1 dynamic segment) ties in depth
 *     with the colliding natural group it was shadowed by
 *     (`/clients/:id/sales/invoices/:invoiceId/*`, 2 dynamic segments) —
 *     the more-literal one must win, or the whole point of giving it its
 *     own group is defeated.
 *
 * DECISION D10 (owner, 24-09-2026) — THE BUDGET IS A MEASUREMENT, NOT A
 * STYLE. The obvious saving left on the table is to drop the enumerated
 * bare-path rules and let the splats cover everything, which would take the
 * file from 98 rules to 55. THE OWNER OPENED THE CLOUDFLARE PREVIEW AND
 * CHECKED: a bare path with no rule of its own 404s, or bounces to the
 * trailing-slash form. So shapes 1 and 4 are LOAD-BEARING and the count
 * cannot be collapsed. That is the whole reason this file sits two rules
 * under a cap that fails silently, rather than comfortably below one.
 *
 * Today's composition, measured rather than remembered:
 *
 *     43  bare path        (shape 1) — one per dynamic page, no splat can
 *     43  bare RSC .txt    (shape 4) — express either transform
 *     12  splats           (shapes 2 and 3, many pages each)
 *     ──
 *     98  of a hard 100
 *
 * **41 OF THOSE 43 ARE UNDER `/clients/`**, which is why D10's consequence
 * names that subtree specifically and is binding on the whole navigation
 * phase: **no new dynamic route under `/clients/[id]`.** A new section there
 * is a QUERY PARAMETER on an existing route — the way the year-end workspace
 * already does it — not a new path segment. Adding one page under a dynamic
 * prefix costs 2 rules and lands on 100; adding one that also opens a new
 * splat group costs 3 and lands on 101, past the cap, silently.
 *
 * The real relief is FEWER dynamic pages, not cleverer rules. Every further
 * mechanical win has already been taken: the six create/edit merges (see the
 * test of that name) and the splat consolidation above. What is left would
 * mean re-architecting Year-End, Compliance or Tax into tabs, which is a
 * product decision rather than a codemod.
 *
 * A PLAIN RULE AFTER A DYNAMIC ONE IS COUNTED AS DYNAMIC (30-09-2026).
 * Cloudflare's parser keeps rules in file order once it has met the first
 * dynamic one, so every rule after it — placeholder or not — is spent from
 * the 100-dynamic budget. The 32 literal shadow-leaf rules
 * (staticLeafShadowRules) used to be sorted in among the dynamic ones, so
 * Cloudflare counted 98 + 32 = 130 and silently DROPPED THE LAST 30: the
 * /relationships/* rules and all twelve splats. Measured live, rule by rule:
 * rules 1-108 answered, 109-138 did not, and the casualties included a
 * plain non-splat rule (/relationships/:entity_id), which is what showed it
 * was a position cut and not a wildcard bug. Every hard reload or shared
 * link into /clients/<id>/<section>/ returned 404 while in-app navigation
 * (client-side, never asks the server) kept working. The test that said
 * "98 of 100" counted syntax, not position, so it stayed green throughout.
 * Plain rules are therefore emitted FIRST, in their own block — still in
 * sorted order, so each shadow leaf still precedes the dynamic sibling it
 * protects against. Do not interleave them again.
 *
 * Usage:
 *   node scripts/generate-redirects.js        # (re)writes public/_redirects
 *   import { buildRedirectsFile } from "./generate-redirects.js"
 *                                              # pure string, for tests
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(__dirname, "..", "app");
const OUTPUT_FILE = path.join(__dirname, "..", "public", "_redirects");

const HEADER = `# GENERATED FILE — do not hand-edit.
# Produced by scripts/generate-redirects.js from the app/ route tree on
# every build (see package.json's "build"/"pages:build" scripts). Re-run
# that script after adding, moving, or deleting any page under a dynamic
# ([param]) route segment; do not add entries here by hand — they will be
# overwritten on the next build.
#
# Rules are first-match-wins. Literal rules (no ":" or "*") come first,
# because Cloudflare counts every rule after the first dynamic one against
# its 100-dynamic cap. Then every page's own "bare path" / "bare RSC"
# rules (exact-shape, mutually exclusive — order among these doesn't
# matter), followed by one splat rule per dynamic-segment group, deepest
# group first, covering every page's "trailing slash" / "RSC payload"
# shapes at once. See generate-redirects.js's module doc for why this
# specific split/ordering is required, not just stylistic.
`;

/** Recursively collects every page.tsx's path, as an array of segments
 * (":name" for a Next.js [name] dynamic segment, else the literal folder
 * name), relative to appDir. Throws on a catch-all ([...x]) segment rather
 * than silently mis-handling it — none exist today; a future one needs an
 * explicit decision about its rewrite shape, not a guess. */
export function walkPages(dir, segments = []) {
  const routes = [];
  // A directory's own page.tsx is normally captured by its PARENT's
  // iteration below — except the very first call, whose "parent" is
  // whoever called walkPages(). Check it explicitly so e.g. app/page.tsx
  // (the "/" route) isn't silently dropped from the walk.
  if (fs.existsSync(path.join(dir, "page.tsx"))) {
    routes.push(segments);
  }
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const name = entry.name;
    if (name.startsWith("[...") || name.startsWith("[[...")) {
      throw new Error(
        `generate-redirects: catch-all segment "${name}" in ${dir} has no defined rewrite shape yet — add explicit handling before this route ships.`
      );
    }
    const isDynamic = name.startsWith("[") && name.endsWith("]");
    const segment = isDynamic ? `:${name.slice(1, -1)}` : name;
    const childDir = path.join(dir, name);
    const childSegments = [...segments, segment];
    routes.push(...walkPages(childDir, childSegments));
  }
  return routes;
}

const isDynamicSeg = (s) => s.startsWith(":");
const replaceDynamic = (segments) => segments.map((s) => (isDynamicSeg(s) ? "_placeholder" : s));

/** The path segments up to and including the LAST dynamic segment in a
 * route — the longest prefix after which every remaining segment is
 * guaranteed static, so a splat anchored here can safely capture the rest
 * verbatim (see the module doc's rule-count-budget note for why this
 * matters and isn't just an optimization). */
function splatSafePrefix(segments) {
  let lastDynamicIdx = -1;
  segments.forEach((s, i) => { if (isDynamicSeg(s)) lastDynamicIdx = i; });
  return segments.slice(0, lastDynamicIdx + 1);
}

/** True if `pathSegments`, truncated to `patternSegments`' length, matches
 * it position-by-position (a ":name" in the pattern matches any literal
 * segment there). Used to find splat-group false positives: a `:invoiceId`
 * placeholder matches the literal segment "new" exactly as readily as a
 * real id, so `/clients/:id/sales/invoices/:invoiceId/*` would otherwise
 * also (wrongly) claim `/clients/:id/sales/invoices/new/...` — a STATIC
 * sibling route, not an instance of the dynamic one. */
function pathMatchesPattern(pathSegments, patternSegments) {
  if (pathSegments.length < patternSegments.length) return false;
  return patternSegments.every((p, i) => isDynamicSeg(p) || p === pathSegments[i]);
}

/** The two shapes that need a real transform (append "/", or insert
 * "/index" before ".txt") and so always stay one rule per page, regardless
 * of whether the page's OTHER two shapes are splat-covered. */
function bareRules(segments) {
  const from = "/" + segments.join("/");
  const to = "/" + replaceDynamic(segments).join("/") + "/";
  return [
    { from, to },
    { from: `${from}.txt`, to: `${to}index.txt` },
  ];
}

/** Total order over enumerated rules' "from" paths, segment by segment: a
 * literal segment sorts before a placeholder (":name") at the same
 * position, so a more-specific rule is always checked first when two rules
 * could BOTH match the same concrete request (same length, one more literal
 * — the exact shape a shadowed leaf collides in). Falls back to a plain
 * alphabetical compare of that position's literal text, then to length.
 *
 * This is a real lexicographic order (map each token to (isDynamic,
 * literalText), compare tuples pairwise) rather than "compare literally,
 * with one exception" — which matters because a naive version of this
 * (segment-length tie -> specificity; else -> raw string compare) is NOT
 * transitive: it broke silently on real data, because dozens of OTHER,
 * DEEPER dynamic rules (every /clients/:id/<section> bare rule) sort
 * alphabetically BETWEEN "/clients/:id" and "/clients/documents" (":" is
 * ASCII 58, below every lowercase letter) despite differing in length from
 * both — chaining raw-string ties into a cycle that left "/clients/:id"
 * sorted first anyway, even though the two rules that actually collide were
 * ordered correctly in every direct, isolated comparison. Comparing
 * position-by-position never falls into that trap: two paths of different
 * length either diverge at a shared position (settled there, independent of
 * what either path does afterward) or one is a strict prefix of the other
 * (settled by length) — nothing about a third, unrelated path can flip it.
 */
function compareEnumeratedPaths(fromA, fromB) {
  const a = fromA.split("/");
  const b = fromB.split("/");
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i++) {
    if (a[i] === b[i]) continue;
    const dynA = isDynamicSeg(a[i]);
    const dynB = isDynamicSeg(b[i]);
    if (dynA !== dynB) return dynA ? 1 : -1;
    return a[i] < b[i] ? -1 : 1;
  }
  return a.length - b.length;
}

/** For a route with NO dynamic segment of its own that is nonetheless
 * structurally shadowed by a deeper dynamic group's placeholder — e.g.
 * /health/critical vs the sibling dynamic segment /health/:client_id, the
 * same "new" vs ":invoiceId" collision the shadow-detection above protects
 * DYNAMIC routes from, except this route was never IN dynamicRoutes at all
 * (it has no ":" segment anywhere in its own path), so that loop never even
 * looked at it. Confirmed live: Cloudflare Pages was silently serving
 * /health/[client_id]'s own bundle for /health/critical/, /health/at-risk/,
 * /health/alerts/ and /health/overrides/ — four pure-static siblings of the
 * dynamic [client_id] segment — because /health/:client_id and
 * /health/:client_id/* both matched first and nothing shadowed them.
 *
 * Four PURELY LITERAL rules (no ":" or "*" anywhere) rather than a splat
 * group: the leaf has no children (nothing nests under /health/critical), so
 * shapes 2 and 3 need no wildcard to "cover the rest" — there is no rest.
 * That keeps every rule here OUTSIDE the 100-DYNAMIC-rule cap entirely (see
 * the module doc's rule-count-budget note and isDynamicRule in the test
 * file): a wildcard splat per leaf would have cost 4 leaves × 1 rule = 4,
 * landing on 102 against a hard 100 — these 16 (4 leaves × 4 shapes) cost
 * nothing against that budget because none of them carry a placeholder.
 */
function staticLeafShadowRules(segments) {
  const bare = "/" + segments.join("/");
  const slash = `${bare}/`;
  return [
    { from: bare, to: slash },
    { from: `${bare}.txt`, to: `${slash}index.txt` },
    { from: slash, to: slash },
    { from: `${slash}index.txt`, to: `${slash}index.txt` },
  ];
}

/** Pure — returns the generated file content without touching disk. */
export function buildRedirectsFile(appDir) {
  const allRoutes = walkPages(appDir);
  const dynamicRoutes = allRoutes.filter((segments) => segments.some(isDynamicSeg));
  const groupOf = new Map(); // route key -> its natural splat-safe-prefix
  for (const segments of dynamicRoutes) groupOf.set(segments.join("/"), splatSafePrefix(segments));

  const groupPrefixes = new Map(); // prefix key -> prefix segments
  for (const prefix of groupOf.values()) groupPrefixes.set(prefix.join("/"), prefix);

  // A route is "shadowed" if it belongs to a SHALLOWER group than some
  // OTHER (deeper) group whose pattern its own path still structurally
  // matches. That means the deeper group's placeholder segment lines up
  // with this route's own static segment (the "new" vs ":invoiceId" case):
  // the deeper splat would otherwise claim this route's requests first and
  // rewrite them to the wrong target.
  const shadowedRouteKeys = new Set();
  for (const prefix of groupPrefixes.values()) {
    for (const route of dynamicRoutes) {
      const routeKey = route.join("/");
      const ownGroup = groupOf.get(routeKey);
      if (ownGroup.length < prefix.length && pathMatchesPattern(route, prefix)) {
        shadowedRouteKeys.add(routeKey);
      }
    }
  }

  // A shadowed route's trailing-slash/RSC shapes don't have to fall back to
  // full per-shape enumeration (4 rules) — every shadowed route seen so far
  // is a pure leaf (no route nests under it), so it can get its OWN
  // single-member splat group instead, keyed by its FULL path rather than
  // its natural (too-shallow) prefix. This ties the deeper colliding
  // group's prefix in segment count, so splats are sorted deepest-first
  // AND, on a depth tie, most-literal-first (fewest dynamic placeholders) —
  // "new" (1 dynamic segment: the outer :id) correctly outranks the
  // colliding ":invoiceId" group (2 dynamic segments) at the same depth,
  // while that group's OTHER, genuinely dynamic siblings (e.g. "edit")
  // still fall through to it exactly as before. Cuts 2 rules per shadowed
  // route (3 total instead of the previous 4: bareRules + this one splat)
  // without changing which requests resolve where.
  for (const routeKey of shadowedRouteKeys) {
    if (!groupPrefixes.has(routeKey)) groupPrefixes.set(routeKey, routeKey.split("/"));
  }

  // A STATIC route (no ":" segment anywhere in its own path) can be shadowed
  // the same way — see staticLeafShadowRules' doc above. Checked against
  // every group prefix at EQUAL segment length: a static leaf one level
  // shallower or deeper than a dynamic group's placeholder is a different
  // route entirely and must not be flagged on a partial, longer-prefix match.
  const staticRoutes = allRoutes.filter((segments) => !segments.some(isDynamicSeg));
  const shadowedStaticRoutes = staticRoutes.filter((route) =>
    [...groupPrefixes.values()].some(
      (prefix) => route.length === prefix.length && pathMatchesPattern(route, prefix)
    )
  );

  const enumerated = [...dynamicRoutes.flatMap((segments) => bareRules(segments)),
    ...shadowedStaticRoutes.flatMap((segments) => staticLeafShadowRules(segments))]
    // See compareEnumeratedPaths' doc for why this can't be segment-count-tie
    // plus a raw alphabetical fallback: that version is not transitive once a
    // third, unrelated rule's path sorts (by plain string comparison) between
    // two rules that actually collide, which real data hits immediately
    // (every /clients/:id/<section> bare rule sorts between "/clients/:id"
    // and "/clients/documents").
    .sort((a, b) => compareEnumeratedPaths(a.from, b.from));

  const literalCount = (segments) => segments.filter((s) => !isDynamicSeg(s)).length;
  const splats = [...groupPrefixes.values()]
    .map((prefix) => ({
      from: "/" + prefix.join("/") + "/*",
      to: "/" + replaceDynamic(prefix).join("/") + "/:splat",
      depth: prefix.length,
      literalCount: literalCount(prefix),
    }))
    // Deepest (most specific) prefix first; on a depth tie, most-literal
    // (fewest dynamic placeholders) first — see the shadowed-leaf note
    // above for why a tie can happen and why literal must win it.
    .sort((a, b) => b.depth - a.depth || b.literalCount - a.literalCount || a.from.localeCompare(b.from));

  // Column-align "from" against the longest one in the whole file (purely
  // cosmetic — Cloudflare only needs whitespace between columns).
  const fromWidth =
    Math.max(
      ...enumerated.map((r) => r.from.length),
      ...splats.map((r) => r.from.length),
      0
    ) + 2;
  const pad = (s) => s + " ".repeat(Math.max(1, fromWidth - s.length));

  // Literal rules first — see the module doc: a literal rule listed after a
  // dynamic one is counted against the 100-dynamic cap by Cloudflare.
  const isDynamicRule = (from) => from.includes(":") || from.includes("*");
  const body = (rules) => rules.map((r) => `${pad(r.from)}${r.to}  200`).join("\n");
  const blocks = [
    body(enumerated.filter((r) => !isDynamicRule(r.from))),
    body(enumerated.filter((r) => isDynamicRule(r.from))),
    body(splats),
  ].filter(Boolean);

  return `${HEADER}\n${blocks.join("\n\n")}\n`;
}

function main() {
  const content = buildRedirectsFile(APP_DIR);
  fs.writeFileSync(OUTPUT_FILE, content);
  console.log(`generate-redirects: wrote ${OUTPUT_FILE}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main();
}
