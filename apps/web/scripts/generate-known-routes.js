#!/usr/bin/env node
/**
 * Generates lib/workspace/knownRoutes.generated.ts: every real page's route,
 * as a segment shape (":name" matches any single Next.js dynamic segment).
 * Reuses generate-redirects.js's app/ walker so there is exactly one piece
 * of code that knows how to enumerate the route tree — this script and
 * generate-redirects.js just consume it for two different purposes (a
 * Cloudflare rewrite list vs. a "does this page still exist" manifest).
 *
 * Consumed by lib/workspace/routeManifest.ts's isKnownAppRoute(), which
 * WorkspaceContext's sanitizeLastRoute() uses to catch a persisted
 * lastRoute entry pointing at a page that has been deleted since it was
 * written — the same-workspace-prefix check alone lets that through (e.g.
 * /accounting/chart-of-accounts still prefix-matches the very much
 * still-alive "accounting" workspace even though that exact page is gone).
 *
 * Usage:
 *   node scripts/generate-known-routes.js
 *   import { buildKnownRoutesFile } from "./generate-known-routes.js"  // pure, for tests
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { walkPages } from "./generate-redirects.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(__dirname, "..", "app");
const OUTPUT_FILE = path.join(__dirname, "..", "lib", "workspace", "knownRoutes.generated.ts");

export function buildKnownRoutesFile(appDir) {
  const shapes = walkPages(appDir).sort((a, b) => a.join("/").localeCompare(b.join("/")));
  const lines = shapes.map((s) => `  ${JSON.stringify(s)},`).join("\n");
  return `// GENERATED FILE — do not hand-edit.
// Produced by scripts/generate-known-routes.js from the app/ route tree on
// every build (see package.json's "build"/"pages:build" scripts). A ":name"
// entry matches any single path segment (a Next.js dynamic route param).
// Consumed by lib/workspace/routeManifest.ts.
export const KNOWN_ROUTE_SHAPES: string[][] = [
${lines}
];
`;
}

function main() {
  fs.writeFileSync(OUTPUT_FILE, buildKnownRoutesFile(APP_DIR));
  console.log(`generate-known-routes: wrote ${OUTPUT_FILE}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main();
}
