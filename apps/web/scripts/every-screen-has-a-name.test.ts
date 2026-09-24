/**
 * Every route is named, and every name is a route.
 *
 * TWO DIRECTIONS, AND THE SECOND IS THE ONE THAT CATCHES TYPOS. A route on
 * disk that appears in neither `ALL_SCREENS` nor `UNLISTED` fails, so a screen
 * added next year cannot be orphaned by silence — somebody has to either name
 * it or say why it is not named. And a named route that does NOT exist on disk
 * fails too: 2.2b's href guard found four hand-typed paths that did not
 * resolve, which is exactly the mistake an inventory invites.
 *
 * `UNLISTED` is checked the same way round. An exemption for a route that has
 * since been deleted is an exemption nobody re-reads, which CLAUDE.md records
 * as how one outlives its reason.
 *
 * WHAT IT DOES NOT ASSERT is that a name is GOOD. No test can. What it can do
 * is make the absence of one visible, and make the list the single place the
 * names live, so improving them is one edit rather than a hunt.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";

import { ALL_SCREENS, UNLISTED, matchScreens, screenHref } from "../lib/navigation/screens.ts";

const WEB = join(import.meta.dirname, "..");
const APP = join(WEB, "app");

/** Every route with a page, as a leading-slash path (`/` for the root). */
function routes(dir = APP, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) routes(p, out);
    else if (name === "page.tsx") {
      const rel = "/" + relative(APP, dir).split("\\").join("/");
      out.push(rel === "/." ? "/" : rel);
    }
  }
  return out;
}

const ROUTES = routes().sort();

/** A screen's route as it appears on disk. */
function onDisk(href: string, scope: string): string {
  return scope === "firm" ? href : `/clients/[id]/${href}`;
}

test("the walk still finds the app", () => {
  assert.ok(ROUTES.length >= 100, `only ${ROUTES.length} routes found — the walk has stopped working`);
});

test("every route on disk is named, or is unlisted with a reason", () => {
  const named = new Set(ALL_SCREENS.map((s) => onDisk(s.href, s.scope)));
  const orphans = ROUTES.filter((r) => !named.has(r) && !(r in UNLISTED));
  assert.deepEqual(
    orphans,
    [],
    "These routes are in neither ALL_SCREENS nor UNLISTED, so nobody can reach " +
      "them by typing and nothing says why:\n  " + orphans.join("\n  "),
  );
});

test("every named screen is a route that exists", () => {
  const onDiskSet = new Set(ROUTES);
  const missing = ALL_SCREENS
    .map((s) => onDisk(s.href, s.scope))
    .filter((r) => !onDiskSet.has(r));
  assert.deepEqual(
    missing,
    [],
    "Named in the inventory, absent from app/ — a palette entry that goes " +
      "nowhere is worse than none, because the name says it works:\n  " + missing.join("\n  "),
  );
});

test("every unlisted route still exists", () => {
  const onDiskSet = new Set(ROUTES);
  const stale = Object.keys(UNLISTED).filter((r) => !onDiskSet.has(r));
  assert.deepEqual(stale, [], "Exempted, but no longer on disk — delete the line:\n  " + stale.join("\n  "));
});

test("no two screens claim the same route", () => {
  const seen = new Map<string, string>();
  const clashes: string[] = [];
  for (const s of ALL_SCREENS) {
    const r = onDisk(s.href, s.scope);
    const prev = seen.get(r);
    if (prev) clashes.push(`${r}: "${prev}" and "${s.name}"`);
    else seen.set(r, s.name);
  }
  assert.deepEqual(clashes, [], clashes.join("\n  "));
});

test("a client screen without a client resolves to nothing, not to a broken path", () => {
  const anyClient = ALL_SCREENS.find((s) => s.scope === "client")!;
  assert.equal(screenHref(anyClient, null), null,
    "with no client open there is no href — the palette must say so rather than " +
    "build `/clients//sales/`");
  assert.equal(screenHref(anyClient, "abc"), `/clients/abc/${anyClient.href}/`);
});

test("the statutory vocabulary is what finds these screens", () => {
  // The whole reason for `synonyms`: none of these words is in its route.
  const cases: [string, string][] = [
    ["43bh", "MSME payments"],
    ["gstr1", "GSTR-1"],
    ["24q", "TDS returns"],
    ["44ab", "Tax audit"],
    ["dtaa", "DTAA treaty rates"],
    ["rule 46(b)", "Invoice numbering"],
    ["as-3", "Cash flow"],
    ["12bb", "Investment declarations"],
  ];
  for (const [typed, expected] of cases) {
    const hits = matchScreens(typed, null).map((s) => s.name);
    assert.ok(hits.includes(expected),
      `typing "${typed}" should find "${expected}" — got ${JSON.stringify(hits)}`);
  }
});

test("client screens are offered only inside a client workspace", () => {
  const atFirm = matchScreens("bank", null).map((s) => s.scope);
  assert.ok(!atFirm.includes("client"),
    "a client screen has no href at firm level, so offering it would send a CA " +
    "to a path with no id in it");
  const inside = matchScreens("bank", "c1").map((s) => s.name);
  assert.ok(inside.includes("Bank"));
});

test("the screens-only prefix does not stop a screen matching", () => {
  // `>` restricts the palette; it must not become part of the query.
  assert.deepEqual(
    matchScreens("> gstr1", null).map((s) => s.name),
    matchScreens("gstr1", null).map((s) => s.name),
  );
});

test("the inventory has not quietly shrunk", () => {
  // 138 named on 24-09-2026. A floor, not an equality: adding screens is
  // ordinary, losing them silently is the failure.
  assert.ok(ALL_SCREENS.length >= 130,
    `only ${ALL_SCREENS.length} screens named — entries have gone missing`);
});
