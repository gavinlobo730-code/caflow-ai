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
// THE RULE, STATED SO IT SURVIVES THE NEXT RESTRUCTURING: however many shells,
// layouts or panels exist, a phone shows exactly ONE navigation trigger and
// opens exactly ONE drawer. That is strictly stronger than the gate check —
// two triggers now fail wherever they are declared, not only in AppShell — and
// it is what a CA actually experiences.
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
    FILES.some((f) => f.rel === "components/shell/NavShell.tsx"),
    "components/shell/NavShell.tsx was not walked — the shell has moved and " +
      "this guard needs restating, not deleting",
  );
});

test("exactly one mobile navigation trigger exists in the product", () => {
  const triggers = sitesOf(/aria-label="Open navigation"/g);
  assert.deepEqual(
    triggers,
    ["components/shell/NavShell.tsx"],
    "A phone must show ONE hamburger. Two render on top of each other — which " +
      "is what happened at /clients/:id before 2.6, 2px apart and differing in " +
      "size, so one showed as a rim around the other and tapping it opened the " +
      "wrong drawer. The shell owns the trigger; a layout or panel must not " +
      "add its own.\n  found in: " + triggers.join(", "),
  );
});

test("exactly one mobile drawer and one backdrop", () => {
  // `md:hidden fixed` is how this product spells "mobile-only chrome pinned to
  // the viewport" — a drawer, a backdrop, a bottom bar, a floating button. Any
  // of them declared outside the shell collides with the shell's own, which is
  // why this counts the CLASS rather than the element: the next thing added
  // collides the same way and would pass a guard that only knew about <Menu>.
  const fixedMobile = sitesOf(/md:hidden fixed/g);
  const outside = fixedMobile.filter((f) => f !== "components/shell/NavShell.tsx");
  assert.deepEqual(
    outside,
    [],
    "Mobile-only fixed chrome outside the one shell:\n  " + outside.join("\n  "),
  );
  assert.equal(
    fixedMobile.length,
    3,
    `NavShell declares ${fixedMobile.length} pieces of mobile fixed chrome, ` +
      "expected 3 (trigger, backdrop, drawer). If it genuinely needs another, " +
      "change this number and say what it is — the point is that the count is " +
      "read rather than assumed.",
  );
});

test("the client header still reserves room for exactly one trigger", () => {
  // `pl-12` is what stops the fixed trigger sitting on top of the client's
  // name. It is sized for one button; it was never the reason two fitted.
  const header = FILES.find((f) => f.rel === "components/ClientHeader.tsx");
  assert.ok(header, "components/ClientHeader.tsx not found");
  assert.ok(
    /pl-12[^"]*md:px-4/.test(header!.src),
    "ClientHeader no longer reserves mobile space for the nav trigger " +
      "(`pl-12 ... md:px-4`) — the trigger will overlap the client name",
  );
});

test("the client workspace still carries a way back to the client list", () => {
  // The other half. Before 2.6 this lived in ClientContextPanel's own drawer
  // header; it is in the section list now, which the one shell renders as its
  // panel inside a client.
  const sections = FILES.find((f) => f.rel === "components/shell/ClientSections.tsx");
  assert.ok(sections, "components/shell/ClientSections.tsx not found");
  assert.ok(
    sections!.src.includes('href="/clients"'),
    "the client panel no longer carries a way back to the client list",
  );
});

test("the three retired shell components are gone, not merely unused", () => {
  // `ActivityRail` and `ClientContextPanel` were the two rails; leaving either
  // on disk invites a future layout to render one again, which is exactly the
  // collision above. `ClientWorkspaceShell` survives — it is the client HEADER
  // now, which is content rather than chrome.
  for (const gone of ["components/ActivityRail.tsx", "components/ClientContextPanel.tsx"]) {
    assert.ok(!fs.existsSync(path.join(WEB, gone)), `${gone} is back`);
  }
});
