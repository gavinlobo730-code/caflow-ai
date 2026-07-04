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
 * generateStaticParams() in that segment's layout.tsx) and gets a rule
 * pair emitted (with and without a trailing slash — Cloudflare does not
 * normalize that for matching purposes). A route with no dynamic segment
 * is a plain static-export file and needs no rule at all.
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
# Rules are first-match-wins. Grouped by dynamic-segment root, deepest
# (most specific) paths first within each group, so a specific rule is
# never shadowed by a shorter one sharing its prefix.
`;

/** Recursively collects every page.tsx's path, as an array of segments
 * (":name" for a Next.js [name] dynamic segment, else the literal folder
 * name), relative to appDir. Throws on a catch-all ([...x]) segment rather
 * than silently mis-handling it — none exist today; a future one needs an
 * explicit decision about its rewrite shape, not a guess. */
export function walkPages(dir, segments = []) {
  const routes = [];
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
    if (fs.existsSync(path.join(childDir, "page.tsx"))) {
      routes.push(childSegments);
    }
    routes.push(...walkPages(childDir, childSegments));
  }
  return routes;
}

export function toRule(segments) {
  if (!segments.some((s) => s.startsWith(":"))) return null; // no dynamic segment -> no rewrite needed
  const from = "/" + segments.join("/");
  const to = "/" + segments.map((s) => (s.startsWith(":") ? "_placeholder" : s)).join("/") + "/";
  return { from, to, depth: segments.length };
}

/** Pure — returns the generated file content without touching disk. */
export function buildRedirectsFile(appDir) {
  const rules = walkPages(appDir)
    .map(toRule)
    .filter(Boolean)
    // Deepest (most specific) first within a first-match-wins file; stable
    // alphabetical tiebreak for deterministic output.
    .sort((a, b) => b.depth - a.depth || a.from.localeCompare(b.from));

  // Column-align "from" against the longest one in the whole file (purely
  // cosmetic — Cloudflare only needs whitespace between columns).
  const fromWidth = Math.max(...rules.map((r) => r.from.length + 1), 0) + 2;
  const pad = (s) => s + " ".repeat(Math.max(1, fromWidth - s.length));
  const formatPair = (from, to) =>
    [`${pad(from)}${to}  200`, `${pad(from + "/")}${to}  200`].join("\n");

  const body = rules.map((r) => formatPair(r.from, r.to)).join("\n\n");
  return `${HEADER}\n${body}\n`;
}

function main() {
  const content = buildRedirectsFile(APP_DIR);
  fs.writeFileSync(OUTPUT_FILE, content);
  console.log(`generate-redirects: wrote ${OUTPUT_FILE}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main();
}
