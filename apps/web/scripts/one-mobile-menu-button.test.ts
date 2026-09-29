// ONE mobile navigation trigger, and ONE drawer, in the whole product.
//
// WHAT THIS GUARD USED TO SAY, AND WHY IT IS RESTATED RATHER THAN DELETED.
// There were two shells: `AppShell` (the firm chrome) and
// `ClientWorkspaceShell` (the client workspace's), mutually exclusive by
// route. AppShell's DESKTOP branch already hid its rails inside the client
// workspace; the MOBILE half did not, so at /clients/:id on a phone both
// triggers rendered:
//
//   AppShell            md:hidden fixed top-3   left-3   z-40  white, p-2
//   ClientContextPanel  md:hidden fixed top-2.5 left-2.5 z-50  navy,  w-8 h-8
//
// Different size, different colour, 2px apart, one on top of the other — so
// the white one showed as a rim along two edges of the navy one, and tapping
// that rim opened the FIRM drawer on top of the client workspace. This guard
// asserted the rule that fixed it: NOTHING IN AppShell'S CHROME RENDERS INSIDE
// THE CLIENT WORKSPACE.
//
// ⚠️ 2.6 DELIBERATELY REVERSED THAT RULE. There is one shell now
// (`components/shell/NavShell.tsx`) and the rail is CONSTANT — because
// `signOut` and the only `href="/settings"` outside the settings screens both
// live on it, so hiding it inside a client workspace meant a CA could not sign
// out or reach Settings from where they spend the day. The old assertions
// therefore fail on correct code, which is this repository's most-repeated
// lesson: they named a SPELLING of the rule (`!isClientWorkspace` gates in one
// named file) rather than the rule.
//
// ⚠️ AND 25-09 REVERSED IT AGAIN, HALFWAY. The rail is firm-level once more —
// inside a client `AppShell` returns `ClientShell`, a top bar and nothing
// else — so NOTHING in AppShell's mobile chrome renders there, which is the
// ORIGINAL rule restored by a different route. What is not restored is the
// reason 2.6 gave for reversing it: sign-out, Settings and ⌘K moved into
// `UtilityCluster`, which both shells render, so they survive the rail's
// absence. Twice now this guard has had to be restated because it named a
// spelling; the assertions below are written against the CONSEQUENCE a CA
// experiences, which is the only form that has survived either change.
//
// ⚠️ 29-09: THE FIRM-LEVEL RAIL IS GONE TOO, and with it the ONE hamburger
// this guard used to require. `WorkspaceShell` replaced `NavShell` (a 64px
// rail + a 220px panel, with its own mobile drawer for phones) with
// `WorkspaceTopBar` — one always-visible bar, at every viewport width, the
// same shape `ClientTopBar` already proved needs no dedicated mobile trigger
// at all. So the product-wide count this file polices moved from ONE to
// ZERO, not to a second one — the collision this guard exists to prevent is
// still exactly as prevented, on a lower number.
//
// THE RULE, STATED SO IT SURVIVES THE NEXT RESTRUCTURING: however many shells,
// layouts or panels exist, a phone shows at most one navigation trigger and
// opens at most one drawer — never two rendered on top of each other. That is
// strictly stronger than the gate check — two triggers now fail wherever they
// are declared, not only in AppShell — and it is what a CA actually
// experiences.
//
// Run with: node --experimental-strip-types --test scripts/one-mobile-menu-button.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", ".git", ".smoke", "scripts"]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of fs.readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const p = path.join(dir, name);
    if (fs.statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

/** Every source file, comments stripped — a rule about SOURCE must not be
 *  satisfied, or broken, by prose describing it. This file's own header names
 *  the two old class strings. */
const FILES = walk(WEB).map((f) => ({
  rel: path.relative(WEB, f).split("\\").join("/"),
  src: stripComments(fs.readFileSync(f, "utf8")),
}));

function sitesOf(re: RegExp): string[] {
  const out: string[] = [];
  for (const { rel, src } of FILES) {
    const n = (src.match(re) ?? []).length;
    for (let i = 0; i < n; i++) out.push(rel);
  }
  return out;
}

test("the walk sees the product, so the counts below are not vacuous", () => {
  // Four guards in this repository's history went inert by finding nothing.
  assert.ok(FILES.length > 200, `only ${FILES.length} source files walked`);
  assert.ok(
    FILES.some((f) => f.rel === "components/shell/WorkspaceTopBar.tsx"),
    "components/shell/WorkspaceTopBar.tsx was not walked — the shell has " +
      "moved and this guard needs restating, not deleting",
  );
});

test("no mobile navigation trigger exists anywhere in the product", () => {
  // Both shells are now an always-visible top bar at every viewport width
  // (WorkspaceTopBar since 29-09, ClientTopBar since 25-09) — neither needs a
  // dedicated hamburger, so the product-wide count is zero. Two would still be
  // the 2.6 collision; this asserts the stronger "not even one exists to
  // collide," so a hamburger reintroduced ANYWHERE fails here immediately
  // rather than only once a second one appears beside it.
  const triggers = sitesOf(/aria-label="Open navigation"/g);
  assert.deepEqual(
    triggers,
    [],
    "A hamburger exists where none should: both shells' navigation is an " +
      "always-visible bar, so a mobile trigger anywhere is either dead code " +
      "or the start of the 2.6 collision in a new place.\n  found in: " +
      triggers.join(", "),
  );
});

test("no mobile-only fixed drawer chrome exists anywhere in the product", () => {
  // `md:hidden fixed` is how this product spells "mobile-only chrome pinned to
  // the viewport" — a drawer, a backdrop, a bottom bar, a floating button. It
  // counts the CLASS rather than the element, so the next thing added collides
  // the same way and would pass a guard that only knew about <Menu>. With
  // NavShell gone (the only source of any) the count is zero.
  const fixedMobile = sitesOf(/md:hidden fixed/g);
  assert.deepEqual(
    fixedMobile,
    [],
    "Mobile-only fixed chrome exists where neither shell has one any more:\n  " +
      fixedMobile.join("\n  "),
  );
});

test("neither shell declares a mobile trigger of its own", () => {
  // THE `pl-12` ASSERTION THAT USED TO BE HERE WAS A SPELLING, AND THE
  // REDESIGN SHOWED IT. It required `ClientHeader` to reserve 48px on the left
  // for `NavShell`'s fixed trigger to sit in. Both shells' navigation is an
  // always-visible bar now, so there is nothing to open and nothing to
  // reserve room for, at either scope. Asserted as the absence of the trigger
  // rather than as padding that dodged it.
  const files = [
    "components/shell/ClientTopBar.tsx",
    "components/shell/ClientShell.tsx",
    "components/shell/WorkspaceTopBar.tsx",
    "components/shell/WorkspaceShell.tsx",
  ].map((rel) => {
    const f = FILES.find((file) => file.rel === rel);
    assert.ok(f, `${rel} not found`);
    return f!;
  });
  for (const f of files) {
    assert.ok(
      !/md:hidden[^"]*fixed/.test(f.src),
      `${f.rel} declares fixed mobile chrome — every shell's navigation is ` +
        "its always-visible bar, so a trigger there is the 2.8 collision in " +
        "a new place",
    );
  }
});

test("the client workspace still carries a way back to the client list", () => {
  // The other half, and the one control the owner asked for by name when the
  // rail came out: "we will give the exit the client workspace button". Before
  // 2.6 it lived in ClientContextPanel's drawer header, then in the section
  // list; it is on the top bar now. `a-client-workspace-still-has-a-way-out`
  // holds the stronger form — that the shell AppShell picks always has one.
  const bar = FILES.find((f) => f.rel === "components/shell/ClientTopBar.tsx");
  assert.ok(bar, "components/shell/ClientTopBar.tsx not found");
  assert.ok(
    bar!.src.includes('href="/clients"'),
    "the client top bar no longer carries a way back to the client list",
  );
});

test("the retired shell components are gone, not merely unused", () => {
  // Leaving any of these on disk invites a future layout to render one again,
  // which is exactly the collision this file exists for. The first two were
  // the two rails 2.6 collapsed. The next three are 25-09's: the client
  // workspace's second shell, its header and its 21-item section list, all
  // absorbed into `ClientTopBar` + `ClientModuleGrid`. The last two are
  // 29-09's: the firm-level rail + 220px panel, absorbed into
  // `WorkspaceTopBar` + `WorkspaceMegaMenu`.
  for (const gone of [
    "components/ActivityRail.tsx",
    "components/ClientContextPanel.tsx",
    "components/ClientWorkspaceShell.tsx",
    "components/ClientHeader.tsx",
    "components/shell/ClientSections.tsx",
    "components/shell/NavShell.tsx",
    "components/shell/WorkspaceRail.tsx",
  ]) {
    assert.ok(!fs.existsSync(path.join(WEB, gone)), `${gone} is back`);
  }
});
