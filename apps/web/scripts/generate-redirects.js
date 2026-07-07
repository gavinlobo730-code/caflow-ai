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
 * route whose path still structurally matches a DEEPER group's pattern)
 * and enumerates that ONE route's trailing-slash/RSC shapes too, instead of
 * relying on any splat for it — every other route sharing the deeper
 * group's splat (e.g. "edit" under :invoiceId) is unaffected and stays
 * splat-covered, keeping the rule-count savings everywhere the ambiguity
 * doesn't apply.
 *
 * Ordering (first-match-wins) is load-bearing in two ways:
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
# Rules are first-match-wins. Every page's own "bare path" / "bare RSC"
# rules come first (exact-shape, mutually exclusive — order among these
# doesn't matter), followed by one splat rule per dynamic-segment group,
# deepest group first, covering every page's "trailing slash" / "RSC
# payload" shapes at once. See generate-redirects.js's module doc for why
# this specific split/ordering is required, not just stylistic.
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

/** The other two shapes (trailing slash, RSC /index.txt) — safe to fold
 * into a group's shared splat rule ONLY when the page's own group isn't
 * shadowed (see pathMatchesPattern above); a shadowed page needs these
 * enumerated too, same as bareRules. */
function slashRules(segments) {
  const from = "/" + segments.join("/") + "/";
  const to = "/" + replaceDynamic(segments).join("/") + "/";
  return [
    { from, to },
    { from: `${from}index.txt`, to: `${to}index.txt` },
  ];
}

/** Pure — returns the generated file content without touching disk. */
export function buildRedirectsFile(appDir) {
  const dynamicRoutes = walkPages(appDir).filter((segments) => segments.some(isDynamicSeg));
  const groupOf = new Map(); // route key -> its natural splat-safe-prefix
  for (const segments of dynamicRoutes) groupOf.set(segments.join("/"), splatSafePrefix(segments));

  const groupPrefixes = new Map(); // prefix key -> prefix segments
  for (const prefix of groupOf.values()) groupPrefixes.set(prefix.join("/"), prefix);

  // A route is "shadowed" — and needs its trailing-slash/RSC shapes
  // enumerated too, not just left to a splat — if it belongs to a
  // SHALLOWER group than some OTHER (deeper) group whose pattern its own
  // path still structurally matches. That means the deeper group's
  // placeholder segment lines up with this route's own static segment (the
  // "new" vs ":invoiceId" case): the deeper splat would otherwise claim
  // this route's requests first and rewrite them to the wrong target. Every
  // OTHER route keeps relying on its own group's splat for those two shapes
  // — only the specific shadowed routes need the extra rules, not their
  // whole group, which keeps the total rule count much lower than falling
  // back to full enumeration for every route sharing that group.
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

  const enumerated = dynamicRoutes
    .flatMap((segments) => {
      const shadowed = shadowedRouteKeys.has(segments.join("/"));
      return shadowed ? [...bareRules(segments), ...slashRules(segments)] : bareRules(segments);
    })
    .sort((a, b) => a.from.localeCompare(b.from));

  const splats = [...groupPrefixes.values()]
    .map((prefix) => ({
      from: "/" + prefix.join("/") + "/*",
      to: "/" + replaceDynamic(prefix).join("/") + "/:splat",
      depth: prefix.length,
    }))
    // Deepest (most specific) prefix first — see the module doc's ordering note.
    .sort((a, b) => b.depth - a.depth || a.from.localeCompare(b.from));

  // Column-align "from" against the longest one in the whole file (purely
  // cosmetic — Cloudflare only needs whitespace between columns).
  const fromWidth =
    Math.max(
      ...enumerated.map((r) => r.from.length),
      ...splats.map((r) => r.from.length),
      0
    ) + 2;
  const pad = (s) => s + " ".repeat(Math.max(1, fromWidth - s.length));

  const enumeratedBody = enumerated.map((r) => `${pad(r.from)}${r.to}  200`).join("\n");
  const splatBody = splats.map((r) => `${pad(r.from)}${r.to}  200`).join("\n");

  return `${HEADER}\n${enumeratedBody}\n\n${splatBody}\n`;
}

function main() {
  const content = buildRedirectsFile(APP_DIR);
  fs.writeFileSync(OUTPUT_FILE, content);
  console.log(`generate-redirects: wrote ${OUTPUT_FILE}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main();
}
