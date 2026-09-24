// The premise `switchClientPath` rests on, asserted against the route tree.
//
// The client switcher carries exactly ONE segment from the old path — the
// section — and drops everything after it, because everything after it is
// (or contains) a document id belonging to the client you are LEAVING.
// `lib/workspace/clientPath.test.ts` pins that arithmetic. What it cannot pin,
// being a pure unit test, is the fact that makes the arithmetic SAFE:
//
//     every first segment under /clients/:id/ is itself a page
//
// If one were not, switching from `/clients/A/<section>/<sub>` would land on
// `/clients/B/<section>/`, a 404. The switcher would then need a list of which
// sections have landing pages — a second vocabulary beside CLIENT_SECTIONS,
// which is exactly the shape this codebase keeps having to delete.
//
// Measured 24-09-2026: 40 sub-routes, 21 distinct first segments, 0 without a
// landing page. Reusing generate-redirects.js's walker rather than a second
// one, for the reason generate-known-routes.js gives: one piece of code knows
// how to enumerate the route tree.
//
// Run with: node --experimental-strip-types --test scripts/a-client-switch-lands-on-the-same-section.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { walkPages } from "./generate-redirects.js";
import { switchClientPath } from "../lib/workspace/clientPath.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROUTES = walkPages(path.join(__dirname, "..", "app")).map((s: string[]) => s.join("/"));
const UNDER_CLIENT = ROUTES.filter((r) => r.startsWith("clients/:id/"));
const FIRST_SEGMENTS = [...new Set(UNDER_CLIENT.map((r) => r.split("/")[2]))].sort();

const A = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
const B = "11111111-2222-3333-4444-555555555555";

test("the walk found the client workspace", () => {
  assert.ok(UNDER_CLIENT.length > 30,
    `only ${UNDER_CLIENT.length} routes under clients/:id/ — the walker has stopped matching`);
  assert.ok(FIRST_SEGMENTS.length > 15,
    `only ${FIRST_SEGMENTS.length} distinct sections found`);
  assert.ok(FIRST_SEGMENTS.includes("sales") && FIRST_SEGMENTS.includes("bank"));
});

test("every section a switch can land on is itself a page", () => {
  const orphaned = FIRST_SEGMENTS.filter((s) => !ROUTES.includes(`clients/:id/${s}`));
  assert.deepEqual(
    orphaned,
    [],
    "these sections have sub-pages but no landing page of their own:\n  " +
      orphaned.join("\n  ") +
      "\n\nSwitching client from one of their sub-pages would 404. Either give " +
      "the section a page, or teach switchClientPath which sections are " +
      "landable — the second is a vocabulary beside CLIENT_SECTIONS and is the " +
      "worse answer."
  );
});

test("switching from every real client route lands on a route that exists", () => {
  // The end-to-end version of the two tests above: run the real function over
  // the real route tree. This is what would have caught a section without a
  // landing page even if the first-segment reasoning were wrong.
  const bad: string[] = [];
  for (const shape of UNDER_CLIENT) {
    // Build a concrete path from the shape, substituting A for every :param.
    const concrete = "/" + shape.split("/").map((s) => (s.startsWith(":") ? A : s)).join("/");
    const landed = switchClientPath(concrete, B);
    const asShape = landed.replace(`/${B}/`, "/:id/").replace(/^\/|\/$/g, "");
    if (!ROUTES.includes(asShape)) bad.push(`${concrete}  ->  ${landed}`);
  }
  assert.deepEqual(bad, [], "a switch landed on a route that does not exist:\n  " + bad.join("\n  "));
});

test("no switch ever carries a document id through", () => {
  // The defect the function exists to prevent, stated over the whole tree:
  // the destination must never contain the id of anything from the old path.
  const carried: string[] = [];
  for (const shape of UNDER_CLIENT) {
    const concrete = "/" + shape.split("/").map((s) => (s.startsWith(":") ? A : s)).join("/");
    const landed = switchClientPath(concrete, B);
    if (landed.includes(A)) carried.push(`${concrete}  ->  ${landed}`);
  }
  assert.deepEqual(carried, [],
    "a switch carried the OLD client's id into the new path:\n  " + carried.join("\n  "));
});
