// Route ids must come from window.location, never from useParams(). Run with:
//   node --experimental-strip-types --test scripts/ids-come-from-location.test.ts
//
// THE MISTAKE THIS EXISTS TO CATCH
//     apps/web is a static export (`output: "export"`). Every dynamic route is
//     pre-rendered ONCE, with scripts/generate-redirects.js substituting the
//     literal string "_placeholder" for each dynamic segment, and Cloudflare
//     serves that one shell for every real URL behind a 200-rewrite. So the
//     App Router's params are anchored to the build-time shell:
//
//         /clients/eac1c949-.../year-end     ->  useParams().id === "_placeholder"
//         /health/eac1c949-...               ->  useParams().client_id === "_placeholder"
//
//     window.location.pathname is the only thing that carries the real id.
//
//     The failure is invisible in development. `next dev` renders dynamic
//     routes for real, so useParams() returns the true segment and every page
//     works perfectly on a developer's machine. It breaks only once exported
//     and served — which is to say, only in front of a user.
//
//     And it breaks quietly, in three different disguises, all of which shipped:
//
//       1. A permanent skeleton. The page guards with
//          `if (!id || id === "_placeholder") return;` and that early return
//          never clears a loading flag initialised to true. Year End sat on
//          three skeleton rows forever; so did ITR Preparation, Tax
//          Computation, 26AS and the XBRL engine.
//       2. An honest-looking lie. The id reaches a query, matches nothing, and
//          the page renders its empty or not-found state. /relationships/{id}
//          said "Entity not found" for every entity that existed; /health/{id}
//          said "Failed to load" for every client.
//       3. A dead link. Navigation built from the id pushes to
//          /clients/_placeholder/... — a URL with no asset behind it, so
//          Cloudflare serves 404.html. Every card on the Income Tax screen did
//          this, and the workspace rail persisted "/health/_placeholder" into
//          localStorage so it survived into later sessions.
//
//     Three symptoms, one cause, and none of them look like the same bug — which
//     is why this is a test and not a note in a doc. The repo already carries the
//     workaround in three places (lib/workspace/ClientNavContext.tsx's
//     useClientNav, components/AppShell.tsx's getRealPathname, and the
//     useEngagementId hook under year-end/[engagementId]); what it lacked was
//     anything stopping the next page from being written the obvious way.
//
// THE RULE
//     No live useParams() call anywhere in app/ or components/. It is absolute
//     rather than "only where the value is an id" on purpose: deciding whether a
//     given param is load-bearing is exactly the judgement call that keeps
//     getting made wrong, and the correct sources — useClientNav() under
//     /clients/[id]/**, a window.location reader elsewhere — are available
//     everywhere and cost nothing.
//
//     Mentions inside comments are fine and in fact wanted; every current one
//     documents why the hook is being avoided.
//
// WHAT IT DOES NOT DO
//     It cannot tell you a window.location reader parses the right segment, or
//     that a guard clears its loading flag. It closes the one door that has
//     been walked through repeatedly.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const ROOTS = ["app", "components"];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === ".next") continue;
      walk(full, out);
    } else if (/\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

const FILES = ROOTS.flatMap((r) => walk(path.join(WEB, r)));

/**
 * Strip comments so a line that only NAMES useParams (to explain why it is not
 * used) does not read as a call. Deliberately not a TypeScript parser: the
 * quote handling below keeps "//" inside a string literal from truncating a
 * real line, and the vacuity guard at the end fails loudly if this ever stops
 * seeing the code at all.
 */
function stripComments(src: string): string {
  let out = "";
  let i = 0;
  let inBlock = false;
  let inLine = false;
  let quote: string | null = null;
  while (i < src.length) {
    const c = src[i];
    const next = src[i + 1];
    if (inLine) {
      if (c === "\n") { inLine = false; out += c; }
      i++;
      continue;
    }
    if (inBlock) {
      if (c === "*" && next === "/") { inBlock = false; i += 2; continue; }
      if (c === "\n") out += c;
      i++;
      continue;
    }
    if (quote) {
      if (c === "\\") { out += src.slice(i, i + 2); i += 2; continue; }
      if (c === quote) quote = null;
      out += c;
      i++;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; out += c; i++; continue; }
    if (c === "/" && next === "/") { inLine = true; i += 2; continue; }
    if (c === "/" && next === "*") { inBlock = true; i += 2; continue; }
    out += c;
    i++;
  }
  return out;
}

test("no page or component reads a route id from useParams()", () => {
  const offenders: string[] = [];
  for (const file of FILES) {
    const code = stripComments(fs.readFileSync(file, "utf8"));
    if (!/\buseParams\b/.test(code)) continue;
    const rel = path.relative(WEB, file);
    const line =
      code.split("\n").findIndex((l) => /\buseParams\b/.test(l)) + 1;
    offenders.push(`${rel}:${line}`);
  }
  assert.deepEqual(
    offenders,
    [],
    "these files call useParams(), which returns the literal \"_placeholder\" " +
      "on the deployed static export — not the real id:\n  " +
      offenders.join("\n  ") +
      "\n\nUse useClientNav() (lib/workspace/ClientNavContext.tsx) for a client " +
      "id under /clients/[id]/**. For any other dynamic segment, read " +
      "window.location.pathname with usePathname() as the re-run trigger only — " +
      "see app/clients/[id]/year-end/[engagementId]/_engagementId.ts.",
  );
});

test("the scan actually reads the app (vacuity guard)", () => {
  assert.ok(
    FILES.length > 200,
    `expected to scan the whole app, found only ${FILES.length} files — the ` +
      "walk is broken and the rule above is passing on an empty set",
  );
  // The comments that explain the ban must survive stripping as comments, and
  // the code around them must survive as code. If either half of stripComments
  // breaks, this catches it before the rule silently stops matching.
  const known = path.join(WEB, "lib/workspace/ClientNavContext.tsx");
  const raw = fs.readFileSync(known, "utf8");
  assert.match(raw, /useParams\(\) would return "_placeholder"/,
    "ClientNavContext's doc comment is the canonical statement of this hazard");
  assert.doesNotMatch(stripComments(raw), /\buseParams\b/,
    "that mention is a comment and must not survive stripping");
  assert.match(stripComments(raw), /export function useClientNav/,
    "the code around it must survive stripping");
});
