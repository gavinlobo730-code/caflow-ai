#!/usr/bin/env node
/**
 * Rewrites scripts/screens.snapshot.json from the real app/ route tree.
 *
 * Deliberately NOT run by the build, unlike generate-known-routes.js.
 * knownRoutes.generated.ts is a CACHE of the tree and must track it
 * automatically; this snapshot is a RECORD of the screens the product had
 * when somebody last looked, and its whole value is that it does not move on
 * its own. See the-redesign-cannot-lose-a-screen.test.ts.
 *
 *   node scripts/refresh-screen-snapshot.js
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { walkPages } from "./generate-redirects.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(__dirname, "..", "app");
const SNAPSHOT = path.join(__dirname, "screens.snapshot.json");

/** Every page's route as a URL path — "/" for app/page.tsx, ":id" for [id]. */
export function screenRoutes(appDir) {
  return [...new Set(walkPages(appDir).map((s) => "/" + s.join("/")))].sort();
}

function main() {
  const routes = screenRoutes(APP_DIR);
  fs.writeFileSync(SNAPSHOT, JSON.stringify(routes, null, 1) + "\n");
  console.log(`refresh-screen-snapshot: wrote ${routes.length} screens to ${SNAPSHOT}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main();
}
