// A link written as a literal path points at a page (or a public file) that exists. Run with:
//   node --experimental-strip-types --test scripts/a-link-to-a-page-points-at-a-page-that-exists.test.ts
//
// WHAT WAS WRONG
//     Driving the trial-balance import to its last step in a browser showed a 404 in the console: the success screen's "View Trial Balance" button
//     linked to `/reports/trial-balance`, a page that has never existed (the trial balance is a tab of a client's accounting page), and the recurring
//     journals' history linked every generated entry to `/accounting/journal`, which does not exist either. Both were found by a stray request, not by
//     any check: the static export serves a missing route as a 404 and nothing in CI ever followed a link.
//
// THE RULE (stated by what is linked, not by a list of files)
//     Every internal path written as a string in `app/` and `components/` (an `href="/…"`, an `href={"/…"}` or an `href={`/…`}`, an `href: "/…"`
//     in a link table, and the argument of `router.push`, `replace`, `prefetch` and `redirect`) is a route that `app/` has a page for, or a file in
//     `public/`. A dynamic segment `[id]` matches any one segment, and in the other direction a `${…}` that is a WHOLE segment of the written path
//     matches any route segment. The query string and the hash are not part of the path.
//
// WHAT THIS CANNOT SEE, AND SAYS SO
//     A link built from a variable or by concatenation, a `${…}` that is only PART of a segment, and a `?tab=` value: whether the tab a link names
//     exists on the page it opens is not read here. Those are checked only by the routes the generator knows (`generate-known-routes.test.ts`) when
//     they are followed.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function* walk(dir: string, ext: RegExp): Generator<string> {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (["node_modules", ".next", "out"].includes(e.name)) continue;
      yield* walk(rel, ext);
    } else if (ext.test(e.name) && !/\.test\./.test(e.name)) {
      yield rel;
    }
  }
}

/** The pages of `app/`, as route shapes: `/`, `/clients/[id]/gst`, … */
function pageRoutes(): string[][] {
  const out: string[][] = [];
  for (const rel of walk("app", /^page\.tsx$/)) {
    const dir = path.posix.dirname(rel).replace(/^app\/?/, "");
    out.push(dir === "" ? [] : dir.split("/"));
  }
  return out;
}

/** What a `${…}` that is a whole segment of a written path stands for. */
const ANY = "\u0000";

export function isARoute(href: string, routes: string[][], publicFiles: Set<string>): boolean {
  const clean = href.split("#")[0].split("?")[0];
  if (publicFiles.has(clean.replace(/^\//, ""))) return true;
  const segs = clean.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  return routes.some((r) => r.length === segs.length && r.every((seg, i) => (seg.startsWith("[") && seg.endsWith("]")) || segs[i] === ANY || seg === segs[i]));
}

/** The paths a source file writes as internal links, each with a whole-segment `${…}` turned into ANY. A path with a `${…}` that is only part of a
 *  segment, or nested code in one, is left out: it names no page this rule can look up. */
export function linksWritten(source: string): string[] {
  const out: string[] = [];
  const CONTEXT = /(?:\bhref\s*[=:]\s*\{?\s*|\b(?:push|replace|prefetch|redirect)\(\s*)(["'`])(\/[^"'`\n]*)\1/g;
  for (const m of source.matchAll(CONTEXT)) {
    const written = m[2];
    if (/\$\{[^}]*[`{]/.test(written)) continue;
    const pathPart = written.split("?")[0].split("#")[0];
    const segments = pathPart.split("/");
    if (segments.some((seg) => seg.includes("${") && !/^\$\{[^}]*\}$/.test(seg))) continue;
    out.push(written.replace(/\$\{[^}]*\}/g, (hit, offset: number, whole: string) => (whole.slice(0, offset).includes("?") ? "x" : ANY)));
  }
  return out;
}

test("every literal internal link points at a page or a public file that exists", () => {
  const routes = pageRoutes();
  const publicFiles = new Set(fs.readdirSync(path.join(WEB, "public")));
  const dead: string[] = [];
  let seen = 0;
  for (const dir of ["app", "components"]) {
    for (const rel of walk(dir, /\.tsx?$/)) {
      for (const href of linksWritten(stripComments(fs.readFileSync(path.join(WEB, rel), "utf8")))) {
        seen += 1;
        if (!isARoute(href, routes, publicFiles)) dead.push(`${rel}: ${href.replaceAll(ANY, "${…}")}`);
      }
    }
  }
  assert.ok(seen > 150, `the scan saw only ${seen} links, so it held nothing`);
  assert.deepEqual(dead, [], "a link to a page that is not there is a 404 the person meets after the work is done");
});

test("the scan reads a template literal, a link table and router.push, and leaves a partly dynamic segment alone", () => {
  assert.deepEqual(linksWritten("<Link href={`/clients/${id}/accounting?tab=journal`}>"), [`/clients/${ANY}/accounting?tab=journal`]);
  assert.deepEqual(linksWritten('{ label: "Trial", href: "/reports/trial-balance" }'), ["/reports/trial-balance"]);
  assert.deepEqual(linksWritten("router.push(`/clients/${clientId}/gst`)"), [`/clients/${ANY}/gst`]);
  assert.deepEqual(linksWritten('router.replace("/login")'), ["/login"]);
  assert.deepEqual(linksWritten("<a href={`/clients/${id}/gst?client=${id}`}>"), [`/clients/${ANY}/gst?client=x`]);
  assert.deepEqual(linksWritten("<a href={`/files/report-${id}.pdf`}>"), []);
  assert.deepEqual(linksWritten("<a href={base + `/x`}>"), []);
  // An empty id in the middle of a path is not a wildcard that hides a missing page: `/clients//accounting` has an empty segment and matches nothing.
  assert.equal(isARoute("/clients//accounting", [["clients", "[id]", "accounting"]], new Set()), false);
  assert.equal(isARoute(`/clients/${ANY}/accounting`, [["clients", "[id]", "accounting"]], new Set()), true);
  assert.equal(isARoute(`/clients/${ANY}/trial`, [["clients", "[id]", "accounting"]], new Set()), false);
});

test("the matcher knows a dynamic segment, a query, a hash and a public file, and refuses a missing page", () => {
  const routes = [["clients", "[id]", "accounting"], ["reports", "cash-flow"], []];
  const files = new Set(["logo.svg"]);
  assert.equal(isARoute("/clients/abc/accounting?tab=trial", routes, files), true);
  assert.equal(isARoute("/reports/cash-flow/#top", routes, files), true);
  assert.equal(isARoute("/", routes, files), true);
  assert.equal(isARoute("/logo.svg", routes, files), true);
  assert.equal(isARoute("/reports/trial-balance", routes, files), false);
  assert.equal(isARoute("/accounting/journal", routes, files), false);
});
