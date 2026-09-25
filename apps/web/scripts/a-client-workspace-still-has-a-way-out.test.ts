// A SIGNED-IN CA ALWAYS HAS A SHELL, AND THE SHELL ALWAYS HAS THE FOUR WAYS OUT.
//
// WHAT MADE THIS NECESSARY. `AppShell` reads the path to decide what chrome a
// screen gets, and its own comment records the history: until 2.6 that answer
// decided whether chrome rendered AT ALL, and a wrong answer drew the firm
// rails alongside the client's — the "two sidebars" bug. 2.6 defused it by
// leaving the answer to choose only WHICH PANEL, so the worst a wrong answer
// could do was show the wrong list.
//
// 25-09 makes it decide again, because the owner's decision is that inside a
// client a CA sees only the client's own things. The failure mode is now worse
// than two sidebars: a wrong TRUE on a firm route would leave a page with NO
// navigation, and a CA with no way to sign out, reach Settings, search, or get
// back to the client list.
//
// SO THE MITIGATION IS STRUCTURAL AND THIS ASSERTS THE STRUCTURE. There are
// exactly two shells; `AppShell` returns one of them and never bare children;
// the three utilities 2.6 exists for are reachable from BOTH; and the client
// one carries the exit. None of that depends on the path test being right.
//
// ⚠️ WRITTEN AS REACHABILITY, NOT AS A LIST OF FILES. The first draft asserted
// that `ClientTopBar.tsx` contained the word "Settings" — which would pass on
// a file that mentioned it in a comment and fail the day the control moved one
// component deeper. This follows imports from each branch's root instead, so a
// refactor that moves the cluster another hop down still passes and a refactor
// that DROPS it still fails. That is this repository's most-repeated lesson:
// write the rule, not a spelling of it.
//
// Run with: node --experimental-strip-types --test scripts/a-client-workspace-still-has-a-way-out.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

function read(rel: string): string {
  const p = path.join(WEB, rel);
  assert.ok(fs.existsSync(p), `${rel} not found — the shell has moved and this guard needs restating, not deleting`);
  return stripComments(fs.readFileSync(p, "utf8"));
}

/** The local modules a file imports, as repo-relative paths that exist. */
function localImports(rel: string): string[] {
  const src = read(rel);
  const out: string[] = [];
  for (const m of src.matchAll(/from\s+"(@\/[^"]+|\.[^"]+)"/g)) {
    const spec = m[1];
    const base = spec.startsWith("@/")
      ? path.join(WEB, spec.slice(2))
      : path.resolve(path.join(WEB, path.dirname(rel)), spec);
    for (const ext of [".tsx", ".ts", "/index.tsx", "/index.ts"]) {
      if (fs.existsSync(base + ext)) {
        out.push(path.relative(WEB, base + ext).split("\\").join("/"));
        break;
      }
    }
  }
  return out;
}

/** Every local module reachable from `roots`, following imports. */
function reachable(roots: string[]): Set<string> {
  const seen = new Set<string>();
  const queue = [...roots];
  while (queue.length) {
    const rel = queue.pop()!;
    if (seen.has(rel)) continue;
    seen.add(rel);
    for (const next of localImports(rel)) queue.push(next);
  }
  return seen;
}

const APP_SHELL = "components/AppShell.tsx";
const CLUSTER = "components/shell/UtilityCluster.tsx";

/** The two shells a signed-in CA can be given, and the root each hangs off.
 *  The firm branch is rooted at the RAIL rather than at `NavShell`, because
 *  the rail is passed to the shell as a prop — an import walk from `NavShell`
 *  alone would never reach it, and would report a hole that is not there. */
const BRANCHES: Record<string, string[]> = {
  "firm level": ["components/shell/NavShell.tsx", "components/shell/WorkspaceRail.tsx"],
  "inside a client": ["components/shell/ClientShell.tsx"],
};

test("the walk resolves imports, so the reachability below is not vacuous", () => {
  // Four guards in this repository's history went inert by finding nothing.
  const fromAppShell = localImports(APP_SHELL);
  assert.ok(
    fromAppShell.length >= 5,
    `only ${fromAppShell.length} local imports resolved from ${APP_SHELL} — the resolver is broken`,
  );
  assert.ok(
    fromAppShell.includes("components/shell/ClientShell.tsx"),
    "AppShell no longer imports ClientShell",
  );
  // The negative control: a module that does NOT reach the cluster must come
  // back false, or "reachable" means "any file at all".
  assert.ok(
    !reachable(["components/shell/NavShell.tsx"]).has(CLUSTER),
    "NavShell alone reaches UtilityCluster — the walk is over-broad and the " +
      "per-branch assertions below prove nothing",
  );
});

test("AppShell offers exactly two shells and neither is 'no shell'", () => {
  const src = read(APP_SHELL);
  for (const shell of ["NavShell", "ClientShell"]) {
    assert.ok(src.includes(`<${shell}`), `AppShell no longer renders <${shell}`);
  }
  // `return <>{children}</>` is legitimate EXACTLY once — the signed-out and
  // non-staff surfaces listed in NO_SHELL_PREFIXES, which have no chrome by
  // design. A second one would be a route rendering with no navigation.
  const bare = (src.match(/return\s*<>\s*\{children\}\s*<\/>/g) ?? []).length;
  assert.equal(
    bare, 1,
    `AppShell returns bare children ${bare} times, expected exactly 1 (the ` +
      "NO_SHELL branch). Another means some signed-in route renders with no " +
      "navigation at all.",
  );
});

test("search, Settings and sign-out are reachable from BOTH shells", () => {
  // The three things `WorkspaceRail`'s header records as missing inside a
  // client workspace before 2.6 made the rail constant. The rail is firm-level
  // again, so what has to be constant is these — not the surface carrying them.
  for (const [name, roots] of Object.entries(BRANCHES)) {
    assert.ok(
      reachable(roots).has(CLUSTER),
      `${CLUSTER} is not reachable from the "${name}" shell — a CA there ` +
        "cannot sign out, reach Settings, or see that search exists",
    );
  }
});

test("the utility cluster actually offers all three", () => {
  // Reachability says the component is in the tree; this says the component is
  // still the thing the tree needs it to be.
  const src = read(CLUSTER);
  assert.ok(src.includes("signOut()"), "UtilityCluster no longer signs out");
  assert.ok(src.includes('href="/settings"'), "UtilityCluster no longer links to Settings");
  assert.ok(src.includes("onOpenSearch"), "UtilityCluster no longer opens search");
  // One modal, one open state: the cluster must not hold its own.
  assert.ok(
    !src.includes("<SearchModal"),
    "UtilityCluster renders its own SearchModal — AppShell owns the one instance",
  );
});

test("the client shell always carries the way out", () => {
  // The control the owner asked for by name on 25-09, when the rail came out:
  // "we will give the exit the client workspace button". Asserted across the
  // whole client branch rather than on one file, so moving it between the bar
  // and a child still passes.
  const files = [...reachable(BRANCHES["inside a client"])];
  const carriers = files.filter((rel) => read(rel).includes('href="/clients"'));
  assert.ok(
    carriers.length > 0,
    "nothing in the client shell links to /clients — a CA inside a client " +
      "workspace has no way back to the client list",
  );
});
