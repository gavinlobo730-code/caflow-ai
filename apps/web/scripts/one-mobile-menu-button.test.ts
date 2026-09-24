// Two shells, two hamburgers, 2px apart.
//
// `AppShell` is the firm-level chrome and `ClientWorkspaceShell` is the client
// workspace's; they are mutually exclusive by route, and AppShell already knew
// that — its DESKTOP branch renders `ActivityRail` + `ContextPanel` only when
// `!isClientWorkspace`, with a comment explaining that failing to do so is the
// "two sidebars" bug. The MOBILE half was not gated. So at /clients/:id on a
// phone both triggers rendered:
//
//   AppShell            md:hidden fixed top-3   left-3   z-40  white, p-2
//   ClientContextPanel  md:hidden fixed top-2.5 left-2.5 z-50  navy,  w-8 h-8
//
// Different size, different colour, 2px apart, one on top of the other — so
// the white one showed as a rim along two edges of the navy one, and tapping
// that rim opened the FIRM drawer on top of the client workspace. `ClientHeader`
// reserves the space with `pl-12 md:px-4`, sized for exactly one trigger.
//
// THE RULE THIS ASSERTS IS NOT "the hamburger is gated". It is the one the
// file already made for the desktop rails, stated for every viewport: NOTHING
// IN AppShell's CHROME RENDERS INSIDE THE CLIENT WORKSPACE. Written that way
// because the next thing added to this shell — a bottom bar, a floating action
// button, a second drawer — collides the same way and would pass a guard that
// only knew about `<Menu>`.
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
const APP_SHELL = path.join(WEB, "components/AppShell.tsx");
const CLIENT_PANEL = path.join(WEB, "components/ClientContextPanel.tsx");

/** The character ranges of every `{!isClientWorkspace && ( … )}` block, found
 * by matching parentheses from the opener rather than by regex — the body
 * holds JSX with its own brackets and a lazy match stops at the first `)`. */
function gatedRanges(src: string): Array<[number, number]> {
  const OPENER = "{!isClientWorkspace && (";
  const out: Array<[number, number]> = [];
  let from = 0;
  for (;;) {
    const start = src.indexOf(OPENER, from);
    if (start === -1) return out;
    let depth = 0;
    let i = start + OPENER.length - 1; // on the "("
    for (; i < src.length; i++) {
      if (src[i] === "(") depth++;
      else if (src[i] === ")") {
        depth--;
        if (depth === 0) break;
      }
    }
    out.push([start, i]);
    from = i + 1;
  }
}

const SHELL = stripComments(fs.readFileSync(APP_SHELL, "utf8"));
const RANGES = gatedRanges(SHELL);
const isGated = (at: number) => RANGES.some(([a, b]) => at > a && at < b);

/** Every occurrence of `needle`, with whether it sits inside a gate. */
function sites(needle: string) {
  const out: Array<{ at: number; gated: boolean }> = [];
  for (let i = SHELL.indexOf(needle); i !== -1; i = SHELL.indexOf(needle, i + 1))
    out.push({ at: i, gated: isGated(i) });
  return out;
}

test("the parser found the gates it is meant to reason about", () => {
  // Without this, every assertion below passes by finding nothing — four
  // guards in this repository's history went inert exactly that way.
  assert.ok(SHELL.length > 2_000, `AppShell.tsx read as ${SHELL.length} chars`);
  assert.ok(
    RANGES.length >= 2,
    `found ${RANGES.length} !isClientWorkspace blocks in AppShell.tsx, expected ` +
      "at least two (the desktop rails and the mobile drawer). If the shell was " +
      "restructured, this guard needs restating — not deleting."
  );
  // The matcher must span a real block, not stop at the first ")".
  const [a, b] = RANGES[0];
  assert.ok(b - a > 40, "a gate matched as a near-empty range — paren matching is broken");
});

test("no firm-level chrome renders inside the client workspace, at any width", () => {
  // `md:hidden` is how this file spells "mobile only"; ActivityRail and
  // ContextPanel are the rails themselves. Every one of them must be inside a
  // gate, because the client workspace renders its own.
  const ungated: string[] = [];
  for (const needle of ["md:hidden", "<ActivityRail", "<ContextPanel"]) {
    const bad = sites(needle).filter((s) => !s.gated).length;
    if (bad) ungated.push(`${needle} × ${bad}`);
  }
  assert.deepEqual(
    ungated,
    [],
    "AppShell renders firm-level chrome outside its `!isClientWorkspace` gate:\n  " +
      ungated.join("\n  ") +
      "\n\nAt /clients/:id that draws on top of ClientWorkspaceShell's own. The " +
      "client drawer already carries the way out (a `/clients` back link in its " +
      "header), so gating loses nothing."
  );
});

test("the client workspace still has a mobile way in, and exactly one", () => {
  // The other half: gating AppShell would be a regression if it left the
  // client workspace with no trigger at all.
  const panel = stripComments(fs.readFileSync(CLIENT_PANEL, "utf8"));
  const triggers = panel.match(/aria-label="Open navigation"/g) ?? [];
  assert.equal(triggers.length, 1,
    `ClientContextPanel has ${triggers.length} mobile nav triggers, expected 1`);
  assert.ok(panel.includes('href="/clients"'),
    "the client drawer no longer carries a way back to the client list — " +
      "gating AppShell's drawer now strands a phone user inside one client");
});

test("the client header still reserves room for exactly one trigger", () => {
  // `pl-12` is what stops the fixed trigger sitting on top of the client's
  // name. It is sized for one button; it was never the reason two fitted.
  const header = stripComments(fs.readFileSync(path.join(WEB, "components/ClientHeader.tsx"), "utf8"));
  assert.ok(/pl-12[^"]*md:px-4/.test(header),
    "ClientHeader no longer reserves mobile space for its nav trigger " +
      "(`pl-12 ... md:px-4`) — the trigger will overlap the client name");
});
