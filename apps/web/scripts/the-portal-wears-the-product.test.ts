/**
 * The portal is the same product, and the API does not advertise what it
 * cannot serve.
 *
 * ── WHY ─────────────────────────────────────────────────────────────────────
 * `apps/web/app/portal/` is the ONLY surface a CA's own client and their
 * employees ever see. It was rendered outside the staff shell with almost none
 * of the shared primitives — 62 raw `gray-*` classes, its own `Panel`, its own
 * `Table`, its own empty and error states, the product wordmark in
 * `text-blue-600` — so the product visibly had two designs and the outside
 * world saw the older one.
 *
 * And the worse half: `portal_self._DASHBOARD_SECTIONS` served SEVEN sections,
 * all `available: true`, while the dashboard kept its own
 * `DATA_SECTIONS = new Set([...])` of the four it knew how to load and
 * filtered the other three out of its own tab row. So the API told a client
 * Documents, Document Requests and Messages existed and the screen silently
 * disagreed.
 *
 * ── THE RULES, NOT A SPELLING OF THEM ───────────────────────────────────────
 * Three assertions, each about a mechanism:
 *
 *   1. Every page under `app/portal/` renders through `PortalShell` — so
 *      signing out exists on all of them, which the employee portal did not
 *      have at all.
 *   2. No page under `app/portal/` uses a raw Tailwind palette colour. The
 *      staff side has had this since G0/G1; the portal was simply never swept.
 *   3. The dashboard keeps NO list of which sections it can render. The
 *      backend owns that vocabulary — the Schedule III caption rule — and a
 *      browser-side set is exactly how three sections came to be hidden.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const PORTAL = join(process.cwd(), "app", "portal");

function pages(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...pages(full));
    else if (entry === "page.tsx") out.push(full);
  }
  return out;
}

/** Source with comment CONTENT blanked and the line structure kept.
 *
 *  Every rule below is about CODE, and the comments in the portal files
 *  deliberately quote the classes and the `DATA_SECTIONS` set that were
 *  removed — so a plain strip would fail them all. Newlines survive because a
 *  guard that reports a line number from a re-flowed copy sends the reader to
 *  the wrong line, which is what the first version of this did: it named
 *  `dashboard/page.tsx:290` for a class that is on 326. */
function code(path: string): string {
  return readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const PAGES = pages(PORTAL);

test("the sweep finds the portal pages at all", () => {
  // Vacuity control: a wrong path makes every assertion below pass over
  // nothing, which is how a guard goes blind on a directory rename.
  assert.ok(PAGES.length >= 5, `only ${PAGES.length} portal pages found — bad path?`);
});

test("every portal page renders through PortalShell", () => {
  // `app/portal/page.tsx` is a redirect that renders null — it has no chrome
  // to wear, and the redirect is the point. Named, with the reason, rather
  // than matched by a pattern that would also excuse a real page.
  // A page reached BEFORE there is a session has nothing to sign out of, and a
  // header offering it would be a control that cannot work. Each is named with
  // its reason rather than matched by a pattern — `/activate` and `/login` are
  // exempt because of what they are, not because of where they sit, and a
  // pattern over the path would also excuse a real page added beside them.
  const EXEMPT = new Map([
    [join(PORTAL, "page.tsx"),
     "the legacy landing route: it renders null and replaces the URL, so there " +
     "is no chrome to put a shell around"],
    [join(PORTAL, "login", "page.tsx"),
     "pre-authentication: there is no session to sign out of, and the page is " +
     "the thing that creates one"],
    [join(PORTAL, "activate", "page.tsx"),
     "pre-authentication: a client accepting an invite has no portal identity " +
     "until they do, so the shell's identity and sign-out have nothing to show"],
    [join(PORTAL, "employee", "activate", "page.tsx"),
     "the employee half of the same: an invite acceptance, before the binding " +
     "that makes them a portal principal exists"],
  ]);

  const missing = PAGES.filter(
    (p) => !EXEMPT.has(p) && !code(p).includes("PortalShell"),
  );
  assert.deepEqual(
    missing.map((p) => p.replace(process.cwd() + "/", "")),
    [],
    "a portal page with its own chrome has its own sign-out, or none at all — " +
      "the employee portal had none, so an employee on a shared phone could " +
      "not end the session",
  );
});

test("no portal page uses a raw Tailwind palette colour", () => {
  // The families the staff side retired in G0/G1. `gray` is here because
  // `border-gray-50` is 1.03:1 on white — invisible, not subtle.
  const RAW = /\b(?:bg|text|border|ring|from|to|via)-(gray|slate|zinc|neutral|stone|blue|indigo|red|green|amber|yellow)-\d{2,3}\b/;
  const offenders: string[] = [];
  for (const p of PAGES) {
    for (const [i, line] of code(p).split("\n").entries()) {
      const m = line.match(RAW);
      if (m) offenders.push(`${p.replace(process.cwd() + "/", "")}:${i + 1} ${m[0]}`);
    }
  }
  assert.deepEqual(offenders, [], "use the ps-* / state-* / brand tokens");
});

test("the dashboard keeps no list of which sections it can render", () => {
  const src = code(join(PORTAL, "dashboard", "page.tsx"));
  // The exact shape that hid three sections, and the general one: a Set or an
  // array literal of section keys anywhere in this file.
  assert.ok(!/DATA_SECTIONS/.test(src),
    "DATA_SECTIONS was the browser keeping the backend's vocabulary");
  const KEYS = ["documents", "requests", "messages", "invoices", "statements",
                "reminders", "compliance"];
  const literals = src.match(/new Set\(\[[^\]]*\]\)|(?:const|let)\s+\w+\s*(?::[^=]+)?=\s*\[[^\]]*\]/g) ?? [];
  const holdsKeys = literals.filter(
    (lit) => KEYS.filter((k) => lit.includes(`"${k}"`)).length >= 3,
  );
  assert.deepEqual(holdsKeys, [],
    "a literal naming three or more section keys is a second vocabulary; the " +
      "server sends the list and the screen renders it");
});

test("the dashboard renders the server's own per-section note", () => {
  // The THIRD state `_DASHBOARD_SECTIONS` grew: present, absent, or present
  // with something the client has to be told. Today that is Document
  // Requests, where uploading is not available — saying so beats a button
  // that 403s and beats hiding the section, which is what used to happen.
  const src = code(join(PORTAL, "dashboard", "page.tsx"));
  assert.ok(/activeSection\?\.note/.test(src),
    "the section's served note must reach the screen");
});
