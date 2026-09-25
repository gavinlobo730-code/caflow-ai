// A CLIENT SCREEN WHOSE SUBJECT CANNOT BE RESOLVED SAYS SO, AND SAYS WHICH
// KIND OF "CANNOT" IT IS.
//
// WHAT MADE THIS NECESSARY. Every one of the forty routes under
// `app/clients/[id]/**` opens its loader with some spelling of
//
//     if (!clientId || clientId === "_placeholder") return;
//
// inside a `useEffect`. The early return skips `setLoading(false)`, so the
// page renders its skeleton for ever — and that is also what a CA sees from a
// stale bookmark or a deleted client. `pnpm smoke` could see the shape of it
// but not the cause: six of those routes rendered one identical body, which is
// what its duplicate-body check exists to fail on, and it did.
//
// ⚠️ THE FIX'S OWN RISK IS THE THING THIS GUARD IS FOR. STUCK.md §3 names it:
// "the risk is conflating still loading with not found". A gate that refuses
// while the lookup is in flight would replace a spinner with a false statement
// about the firm's data, which is worse. So the decision lives in
// `lib/workspace/clientGate.ts` — no imports, so it can be loaded here — and
// this exercises it as BEHAVIOUR. The three states that must never collapse
// are asserted one by one.
//
// The structural half is written as REACHABILITY rather than as a list of
// files: the layout must reach a module that reads the resolution, so moving
// the gate a component deeper still passes and deleting it still fails. That
// is this repository's most-repeated lesson — write the rule, not a spelling
// of it.
//
// Run with: node --experimental-strip-types --test scripts/a-client-screen-says-when-there-is-no-such-client.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";
import {
  PLACEHOLDER_CLIENT_ID,
  clientSectionSegment,
  gateVerdict,
  isClientFrontDoor,
  refusalAddress,
  type ClientResolution,
} from "../lib/workspace/clientGate.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const LAYOUT = "app/clients/[id]/layout.tsx";

function read(rel: string): string {
  const p = path.join(WEB, rel);
  assert.ok(
    fs.existsSync(p),
    `${rel} not found — the client workspace has moved and this guard needs restating, not deleting`,
  );
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
    for (const ext of ["", ".tsx", ".ts", "/index.tsx", "/index.ts"]) {
      if (fs.existsSync(base + ext) && fs.statSync(base + ext).isFile()) {
        out.push(path.relative(WEB, base + ext).split("\\").join("/"));
        break;
      }
    }
  }
  return out;
}

/** Everything reachable from `rel` by import, `rel` included. */
function reachable(rel: string, seen = new Set<string>()): Set<string> {
  if (seen.has(rel)) return seen;
  seen.add(rel);
  for (const next of localImports(rel)) reachable(next, seen);
  return seen;
}

// ── THE DECISION ───────────────────────────────────────────────────────────

test("a lookup in flight renders the screen, it does not refuse it", () => {
  for (const p of ["/clients/abc", "/clients/abc/sales", "/clients/abc/reports/ageing"]) {
    assert.equal(
      gateVerdict("resolving", p),
      "render",
      `${p} refused while the lookup was still in flight — that is the false ` +
        `"no such client" STUCK.md §3 warns about`,
    );
  }
});

test("the states that have a client render the screen", () => {
  for (const r of ["off-route", "resolved"] as ClientResolution[]) {
    assert.equal(gateVerdict(r, "/clients/abc/sales"), "render");
  }
});

test("a lookup that FAILED is not a client that does not EXIST", () => {
  assert.equal(gateVerdict("unavailable", "/clients/abc/sales"), "unavailable");
  assert.equal(gateVerdict("absent", "/clients/abc/sales"), "absent");
  assert.notEqual(
    gateVerdict("unavailable", "/clients/abc/sales"),
    gateVerdict("absent", "/clients/abc/sales"),
    "a network failure and a deleted client reached the same verdict — a CA " +
      "would be told their client does not exist because a request timed out",
  );
});

test("a real id naming no client is refused on the front door too", () => {
  // A module grid over a client that is not there is the same defect one level
  // up, so `absent` does not get an exemption for being at the top.
  assert.equal(gateVerdict("absent", "/clients/abc"), "absent");
  assert.equal(gateVerdict("unavailable", "/clients/abc"), "unavailable");
});

test("the front door keeps its redirect for an unnamed id, and a module does not", () => {
  // `/clients/<id>` returns to the list, which the smoke walk pins as correct;
  // refusing there would replace a working redirect with a dead end.
  assert.ok(isClientFrontDoor(`/clients/${PLACEHOLDER_CLIENT_ID}`));
  assert.equal(gateVerdict("unnamed", `/clients/${PLACEHOLDER_CLIENT_ID}`), "render");
  assert.ok(!isClientFrontDoor(`/clients/${PLACEHOLDER_CLIENT_ID}/sales`));
  assert.equal(gateVerdict("unnamed", `/clients/${PLACEHOLDER_CLIENT_ID}/sales`), "unnamed");
});

// ── WHAT THE REFUSAL SAYS ──────────────────────────────────────────────────

test("the address is the one the visitor asked for, not the one the build was made under", () => {
  // Under Cloudflare's 200-rewrite the router holds the placeholder in the ID
  // segment and the real thing after it; `clientId` is already the real id.
  assert.equal(
    refusalAddress("7f3c", `/clients/${PLACEHOLDER_CLIENT_ID}/reports/ageing`),
    "/clients/7f3c/reports/ageing",
  );
  assert.equal(refusalAddress("7f3c", `/clients/${PLACEHOLDER_CLIENT_ID}`), "/clients/7f3c");
});

test("two routes under one module produce two different refusals", () => {
  // Not the point of showing the address, but it is what keeps `pnpm smoke`'s
  // duplicate-body check meaningful without moving its threshold.
  const a = refusalAddress("x", "/clients/x/reports/ageing");
  const b = refusalAddress("x", "/clients/x/reports/ratios");
  assert.notEqual(a, b);
  assert.equal(clientSectionSegment(a), clientSectionSegment(b), "same module, as expected");
});

test("the module is read at position 3, and the front door has none", () => {
  assert.equal(clientSectionSegment("/clients/x/fixed-assets"), "fixed-assets");
  assert.equal(
    clientSectionSegment("/clients/x"),
    "",
    'the front door resolved a module — naming one there describes a screen ' +
      'the visitor is not standing on',
  );
});

// ── THE STRUCTURE ──────────────────────────────────────────────────────────

test("the client layout reaches the gate, wherever the gate lives", () => {
  const reach = reachable(LAYOUT);
  assert.ok(
    [...reach].some((f) => stripComments(fs.readFileSync(path.join(WEB, f), "utf8")).includes("gateVerdict(")),
    `nothing reachable from ${LAYOUT} asks gateVerdict() — every screen under ` +
      `it is back to holding its skeleton for ever on an unresolvable client`,
  );
});

test("the layout keeps its static param, which is why the gate is a child", () => {
  // `output: "export"` needs `generateStaticParams`, and a file carrying
  // "use client" may not have one — so the layout must stay a server component.
  const src = read(LAYOUT);
  assert.ok(src.includes("generateStaticParams"));
  assert.ok(
    !src.includes('"use client"'),
    "the layout became a client component, which drops generateStaticParams " +
      "and with it the whole pre-rendered client workspace",
  );
});

test("the shell asks for the client once", () => {
  // ONE LOOKUP, TWO READERS. `ClientTopBar` used to run its own query and keep
  // the answer private, which is how the bar could know a client did not exist
  // while every screen under it spun. Two lookups would be two answers.
  const shell = path.join(WEB, "components/shell");
  const offenders = fs
    .readdirSync(shell)
    .filter((f) => f.endsWith(".tsx") || f.endsWith(".ts"))
    .filter((f) => stripComments(fs.readFileSync(path.join(shell, f), "utf8")).includes('.from("clients")'));
  assert.deepEqual(
    offenders,
    [],
    "a shell component runs its own clients lookup again — the resolution " +
      "belongs to ClientNavProvider, which the gate and the bar both read",
  );
});

// ── THE NEGATIVE CONTROL ───────────────────────────────────────────────────
//
// An absence-asserting guard needs a probe proving it catches its own positive
// case. These two run the checks above against deliberately wrong inputs.

test("negative control: a gate that refused while resolving would fail this", () => {
  const wrong = (r: ClientResolution) => (r === "resolving" ? "absent" : gateVerdict(r, "/clients/x/sales"));
  assert.notEqual(wrong("resolving"), "render");
});

test("premise: the import walk actually walks", () => {
  // If `reachable()` silently returned only its own argument, the layout test
  // above would be vacuous — it would be asserting that the layout FILE
  // mentions gateVerdict, which is the spelling and not the rule.
  const reach = reachable(LAYOUT);
  assert.ok(reach.size > 1, "the import walk found nothing beyond the layout itself");
  assert.ok(
    [...reach].some((f) => f.startsWith("lib/workspace/")),
    "the walk did not reach lib/workspace — it is not following imports",
  );
});
