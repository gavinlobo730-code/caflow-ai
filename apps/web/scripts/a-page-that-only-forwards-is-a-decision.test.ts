// A page whose only job is to send the visitor to another address is a
// decision, and this file is the list of them. Run with:
//   node --experimental-strip-types --test scripts/a-page-that-only-forwards-is-a-decision.test.ts
//
// WHY THIS EXISTS (POST-A-562, 26-11-2026)
//     The app is a static export, so an address that moved cannot be answered
//     by the server with a redirect; the old address keeps a page that renders
//     nothing and calls `router.replace`. Three such pages had built up, each
//     "kept for old bookmarks". Two (/onboarding/checklist and
//     /team/work-allocation) were linked from nothing in the product, its mail
//     or its documents, and were deleted. One stays, for the reason given
//     below. A new forwarding page fails here until it is added to the list
//     with its reason, and a page on the list that is deleted (or becomes a
//     real screen) must leave it: the list only shrinks.
//
// THE RULE, NOT A SPELLING OF IT
//     A forwarding page is a `page.tsx` under `app/` that calls
//     `router.replace(` and renders no element at all (no JSX tag survives
//     once comments are stripped). A page that forwards only in one branch and
//     otherwise renders a screen (the client workspace's front door, which
//     sends an unresolved client back to the list) is a screen, not this.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const ROOT = path.join(import.meta.dirname, "..");
const APP = path.join(ROOT, "app");

/** Every forwarding-only page, by its address, with why it stays. Shrink only. */
const FORWARDING_PAGES: Record<string, string> = {
  "/portal":
    "the client portal's old landing address; it forwards to /portal/dashboard and " +
    "carries an invitation's ?invite= along. Kept because the server's PORTAL_BASE_URL " +
    "setting (read on Render, which this repository cannot see) may still point a sent " +
    "invitation here; delete it only after that setting has been read (POST-A-562)",
};

function pages(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) pages(full, out);
    else if (e.name === "page.tsx") out.push(full);
  }
  return out;
}

function addressOf(file: string): string {
  const rel = path.relative(APP, path.dirname(file)).split(path.sep).join("/");
  return rel === "" ? "/" : `/${rel}`;
}

function isForwardingOnly(src: string): boolean {
  const code = stripComments(src);
  return /\brouter\.replace\(/.test(code) && !/<[A-Za-z]/.test(code);
}

const ALL = pages(APP);
const FORWARDING = ALL.filter((f) => isForwardingOnly(fs.readFileSync(f, "utf8"))).map(addressOf).sort();

test("the scan reads the whole tree", () => {
  assert.ok(ALL.length > 150, `only ${ALL.length} pages were found under app/`);
});

test("every forwarding-only page is on the list, with its reason", () => {
  const unlisted = FORWARDING.filter((a) => !(a in FORWARDING_PAGES));
  assert.deepEqual(unlisted, [],
    "a page that only forwards is kept only by a decision: search the app, the mail the " +
    "server sends and the documents for a link to the old address, delete the page if " +
    "nothing needs it, or add it to FORWARDING_PAGES with the reason it stays");
});

test("the list only names pages that still forward, so it shrinks when one goes", () => {
  const stale = Object.keys(FORWARDING_PAGES).filter((a) => !FORWARDING.includes(a));
  assert.deepEqual(stale, [], "remove these from FORWARDING_PAGES: they are gone or are real screens now");
});

test("the rule tells a forwarding page from a screen that forwards in one branch", () => {
  const stub = `"use client";\nexport default function R() {\n  useEffect(() => { router.replace("/x"); }, []);\n  return null;\n}\n`;
  const screen = `export default function S() {\n  if (!id) { router.replace("/clients"); return null; }\n  return <Grid id={id} />;\n}\n`;
  const comment = `// once rendered <Old /> here\nexport default function R() { router.replace("/x"); return null; }\n`;
  assert.equal(isForwardingOnly(stub), true);
  assert.equal(isForwardingOnly(screen), false);
  assert.equal(isForwardingOnly(comment), true, "a tag named in a comment is not an element");
  assert.equal(isForwardingOnly(`export default function P() { return <main />; }`), false);
});
