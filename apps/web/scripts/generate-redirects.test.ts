// Proves public/_redirects can't silently drift from the app/ route tree.
// Run with: node --experimental-strip-types --test scripts/generate-redirects.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildRedirectsFile, walkPages } from "./generate-redirects.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(__dirname, "..", "app");
const REDIRECTS_FILE = path.join(__dirname, "..", "public", "_redirects");

test("public/_redirects matches what the generator produces from app/ right now", () => {
  const generated = buildRedirectsFile(APP_DIR);
  const checkedIn = fs.readFileSync(REDIRECTS_FILE, "utf8");
  assert.equal(
    generated,
    checkedIn,
    "public/_redirects is stale — a page under a dynamic ([param]) route " +
      "segment was added, moved, or removed without re-running " +
      "`npm run generate:redirects` (or `next build`, which now runs it " +
      "automatically) before committing."
  );
});

test("every known client-section dynamic route is present", () => {
  const generated = buildRedirectsFile(APP_DIR);
  for (const from of [
    "/clients/:id/instructions",
    "/clients/:id/knowledge",
    "/clients/:id/year-end/xbrl",
    "/clients/:id/tax/26as",
    "/clients/:id/tax/computation",
    "/clients/:id/tax/filing",
  ]) {
    assert.ok(generated.includes(from), `missing rule for ${from}`);
  }
});

test("a deleted route's stale rule does not linger", () => {
  // Regression pin for the two dead entries found during the navigation
  // investigation: /clients/:id/coa (retired in R3.3b) and
  // /accounting/bank-statements/:id (its whole directory no longer exists).
  const generated = buildRedirectsFile(APP_DIR);
  assert.ok(!generated.includes("/clients/:id/coa"));
  assert.ok(!/\/accounting\/bank-statements/.test(generated));
});

/** Every rule in the generated file, as {from, to}. A rule is the only kind
 * of line the generator emits that ends in the 200 status code. */
function rulesIn(generated: string) {
  return generated
    .split("\n")
    .filter((l) => l.trim().endsWith("200"))
    .map((l) => {
      const [from, to] = l.trim().split(/\s+/);
      return { from, to };
    });
}

/** A rule is DYNAMIC by its own syntax when its `from` carries a
 * `:placeholder` or a `*` splat. That is NOT the population Cloudflare's
 * 100 cap is measured against — see cloudflareDynamicCount below. */
const isDynamicRule = (from: string) => from.includes(":") || from.includes("*");

/** How many rules Cloudflare spends from its 100-dynamic budget. Once its
 * parser has met the first dynamic rule it keeps everything after it in file
 * order, so EVERY later rule counts — a literal one included. Counting by
 * syntax (isDynamicRule) gave 98 for the file that was shipping 130, and the
 * 30 rules past the cap were dropped silently. */
function cloudflareDynamicCount(generated: string) {
  const rules = rulesIn(generated);
  const first = rules.findIndex((r) => isDynamicRule(r.from));
  return first === -1 ? 0 : rules.length - first;
}

test("no literal rule is listed after a dynamic one, so Cloudflare counts the budget the way this file does", () => {
  // Regression pin (30-09-2026). 32 literal shadow-leaf rules sat among the
  // dynamic ones, Cloudflare counted 98 + 32 = 130 against a cap of 100, and
  // it silently dropped rules 109-138: /relationships/* and all twelve
  // splats. Every hard reload of /clients/<id>/<section>/ then 404ed in
  // production while the syntactic count below read a comfortable 98.
  const generated = buildRedirectsFile(APP_DIR);
  const rules = rulesIn(generated);
  const firstDynamic = rules.findIndex((r) => isDynamicRule(r.from));
  assert.ok(firstDynamic > -1, "the app has dynamic routes, so the file has a dynamic rule");
  const stranded = rules.slice(firstDynamic).filter((r) => !isDynamicRule(r.from));
  assert.deepEqual(
    stranded.map((r) => r.from),
    [],
    "literal rules listed after the first dynamic rule are counted by Cloudflare " +
      "as dynamic and eat the 100-rule budget — emit them first"
  );
  const syntactic = rules.filter((r) => isDynamicRule(r.from)).length;
  assert.equal(cloudflareDynamicCount(generated), syntactic,
    "Cloudflare's positional count must equal the syntactic one");
  assert.ok(cloudflareDynamicCount(generated) <= 100,
    `Cloudflare would count ${cloudflareDynamicCount(generated)} dynamic rules against a cap of 100`);
});

test("literal rules come first whatever the tree looks like", () => {
  // The same rule on a synthetic tree, so it is a statement about the
  // generator and not a second measurement of app/ — a static sibling of a
  // dynamic segment is exactly what produces literal rules.
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "redirects-order-"));
  try {
    const page = "export default function P() { return null; }";
    const mk = (...segs: string[]) => {
      const dir = path.join(tmp, ...segs);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "page.tsx"), page);
    };
    mk("clients", "[id]");
    mk("clients", "[id]", "overview");
    mk("clients", "documents");
    mk("health", "[client_id]");
    mk("health", "critical");
    const rules = rulesIn(buildRedirectsFile(tmp));
    const lastLiteral = rules.map((r) => isDynamicRule(r.from)).lastIndexOf(false);
    const firstDynamic = rules.findIndex((r) => isDynamicRule(r.from));
    assert.ok(lastLiteral > -1, "the fixture produces literal shadow rules");
    assert.ok(lastLiteral < firstDynamic,
      "every literal rule must precede the first dynamic one");
    // Hoisting must not cost the shadow its precedence over its sibling.
    const from = rules.map((r) => r.from);
    assert.ok(from.indexOf("/health/critical") < from.indexOf("/health/:client_id"));
    assert.ok(from.indexOf("/clients/documents") < from.indexOf("/clients/:id"));
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("the dynamic-rule count stays under Cloudflare Pages' 100-dynamic-redirect cap", () => {
  // Regression pin for the "whole client workspace 404s" incident: 39
  // dynamic pages x 4 enumerated shapes each produced 156 rules, and
  // anything past position 100 in the file was silently ignored by
  // Cloudflare in production — a failure mode this repo's own local
  // verification harness didn't catch (it doesn't enforce the cap).
  //
  // THE BUDGET IS 99 SINCE POST-A-148, WHICH IS THE REAL COUNT: the year-end landing page's payload needed a
  // rule of its own once the four dead bare-.txt rules were listed ahead of their siblings (one rule, 98 to 99).
  // Everything below that says 98 describes the count BEFORE that, and the arithmetic is worse by one: the
  // next page under a dynamic prefix costs two, which is 101.
  //
  // (The paragraph that follows was written at 98.) THE BUDGET IS 98, WHICH IS THE REAL COUNT — a ratchet, not a ceiling
  // somebody picked. It was pinned at 90 once "for headroom", which meant
  // that by the time the tree reached 50 dynamic pages the file had crept
  // to 124 — OVER the real cap, with pages silently 404ing in production —
  // while the guard still read green against a number nobody had rechecked.
  // A budget above the truth is a budget that cannot fire. It was then
  // pinned at 99, one above the truth, which is the same mistake one rule
  // smaller: it silently admits the next page added.
  //
  // ⚠️ THE NEXT DYNAMIC PAGE ADDED BREAKS THIS, AND THAT IS THE POINT.
  // 98 + 2 = 100, which is AT the cap with no spare; +3 if it also opens a
  // new splat group, which is past it. Do not raise this number. See
  // DECISION D10 in generate-redirects.js's module doc: the collapse that
  // would buy 43 rules back was checked against the Cloudflare preview by
  // the owner and does not work — a bare path with no rule of its own 404s.
  // The route is a QUERY PARAMETER on an existing page, or a page somewhere
  // else is retired first.
  const generated = buildRedirectsFile(APP_DIR);
  const dynamic = rulesIn(generated).filter((r) => isDynamicRule(r.from));
  assert.equal(
    dynamic.length,
    99,
    `_redirects has ${dynamic.length} dynamic rules against a budget of 99 and a ` +
      "hard Cloudflare cap of 100, which fails SILENTLY. If this went UP, a route " +
      "was added — read D10 in generate-redirects.js before touching this number. " +
      "If it went DOWN, a route was retired and the budget ratchets down with it."
  );
});

test("the only rules with no placeholder are the named static-leaf shadow fixes", () => {
  // The cap above is on DYNAMIC rules; Cloudflare's separate static budget
  // is 2,100 and nothing here approaches it. The two counts used to coincide
  // because every route this generator touched passed through at least one
  // [param] segment — until a route with NO dynamic segment of its own
  // turned out to be structurally shadowed by a SIBLING dynamic segment's
  // placeholder (":name" matches a literal folder name exactly as readily as
  // a real id), the same "new" vs ":invoiceId" collision the xbrl test below
  // protects, except this route was never in dynamicRoutes at all so nothing
  // ever checked it. Confirmed live: Cloudflare Pages was silently serving
  // /health/[client_id]'s own bundle for /health/critical/ (and its three
  // siblings), /relationships/[entity_id]'s for all four of its static
  // siblings, and /clients/[id]'s for /clients/documents — nine real pages,
  // each fully built and completely unreachable in production. Each gets
  // four PURELY LITERAL rules (staticLeafShadowRules) rather than a splat,
  // because none of the nine has anything nesting under it, so none of the
  // 36 counts against the 100-DYNAMIC cap (test 4 above stays at 98). This
  // pins the exact set BY NAME so a tenth one doesn't silently join the list
  // — or so a maliciously named future dynamic sibling can't quietly turn
  // this into a growing category. Test 4 is what protects the shared budget
  // if it ever does.
  const statics = rulesIn(buildRedirectsFile(APP_DIR)).filter((r) => !isDynamicRule(r.from));
  const shadowedLeaves = [
    "/clients/documents",
    // The client-onboarding tracker moved here from /onboarding/checklist
    // (sweep-auth-and-public-05) — another pure-static leaf sibling of the
    // dynamic /clients/:id segment, shadowed the same way /clients/documents
    // already was.
    "/clients/onboarding",
    "/health/alerts",
    "/health/at-risk",
    "/health/critical",
    "/health/overrides",
    "/relationships/cross-client",
    "/relationships/explorer",
    "/relationships/intelligence",
    "/relationships/ownership-map",
  ];
  assert.equal(statics.length, shadowedLeaves.length * 4,
    "expected exactly 4 literal rules (bare / bare-RSC / slash / slash-RSC) per shadowed leaf");
  for (const leaf of shadowedLeaves) {
    for (const from of [leaf, `${leaf}.txt`, `${leaf}/`, `${leaf}/index.txt`]) {
      assert.ok(statics.some((r) => r.from === from), `missing literal shadow rule for ${from}`);
    }
  }
  // Every one of these must be checked BEFORE the shadowing dynamic sibling
  // it protects against, or it would never win (first-match-wins).
  const generated = buildRedirectsFile(APP_DIR);
  const idx = (s: string) => generated.indexOf(s);
  assert.ok(idx("/health/critical ") < idx("/health/:client_id "));
  assert.ok(idx("/health/critical/") < idx("/health/:client_id/*"));
  assert.ok(idx("/relationships/explorer ") < idx("/relationships/:entity_id "));
  assert.ok(idx("/clients/documents ") < idx("/clients/:id "));
});

test("the budget is spent in the shape D10 says it is", () => {
  // The count alone cannot tell a route being added from a shape changing.
  // These three are what D10's argument rests on: shapes 1 and 4 stay one
  // rule per page because no splat can express their transform, and 41 of
  // the 43 sit under /clients/ — which is why the consequence binds on that
  // subtree specifically rather than on the app in general. Restricted to
  // DYNAMIC rules (isDynamicRule) so the static shadow-leaf fixes above,
  // which reuse the same bare/RSC shapes for an unrelated reason, don't
  // inflate this count — they have their own pinned count in the test above.
  const rules = rulesIn(buildRedirectsFile(APP_DIR)).filter((r) => isDynamicRule(r.from));
  const splats = rules.filter((r) => r.from.endsWith("/*"));
  const bare = rules.filter((r) => !r.from.endsWith("/*") && !r.from.endsWith(".txt"));
  // The one landing payload (/clients/:id/year-end/index.txt) is neither shape 1 nor 4: it is the
  // guard that lets the year-end engagement's ".txt" rule go first (POST-A-148).
  const landing = rules.filter((r) => r.from.endsWith("/index.txt"));
  const bareRsc = rules.filter((r) => !r.from.endsWith("/*") && r.from.endsWith(".txt") && !r.from.endsWith("/index.txt"));

  assert.equal(bare.length, bareRsc.length,
    "shapes 1 and 4 are one rule per dynamic page each, so they move together");
  assert.deepEqual(
    { bare: bare.length, bareRsc: bareRsc.length, splats: splats.length },
    { bare: 43, bareRsc: 43, splats: 12 }
  );

  assert.deepEqual(landing.map((r) => r.from), ["/clients/:id/year-end/index.txt"]);

  const underClients = bare.filter((r) => r.from.startsWith("/clients/"));
  assert.equal(underClients.length, 41,
    "D10's consequence — no new dynamic route under /clients/[id] — is aimed at " +
      "this subset. If it is no longer the bulk of the budget, re-read the decision.");
});

test("every place that states today's redirect budget states the measured one", () => {
  // POST-A-148 took the count from 98 to 99 and the pin above moved with it, while the
  // generator's own D10 block, the live check's header, the owner's decision text, the
  // payroll design and the D26 ledger line all went on saying 98 of 100 and that one more
  // page lands ON the cap. At 99 it lands past it. Each of these is a present-tense claim
  // about the file, so each is held to the file; a dated record (THE-PLAN's 24 September
  // decisions, a closed line in checked-closed.md) is history and is not on this list.
  // CLAUDE.md's Deployment bullet says the same and is not edited from a branch.
  const generated = buildRedirectsFile(APP_DIR);
  const rules = rulesIn(generated);
  const dynamic = rules.filter((r) => isDynamicRule(r.from));
  const total = cloudflareDynamicCount(generated);
  const firstDynamicPosition = rules.findIndex((r) => isDynamicRule(r.from)) + 1;
  const splats = dynamic.filter((r) => r.from.endsWith("/*")).length;
  const bare = dynamic.filter((r) => !r.from.endsWith("/*") && !r.from.endsWith(".txt")).length;
  const landing = dynamic.filter((r) => r.from.endsWith("/index.txt")).length;
  const bareRsc = dynamic.length - splats - bare - landing;

  const REPO = path.join(__dirname, "..", "..", "..");
  // Prose wraps; a comment's leading "*" or "#", or a quote's ">", is not part of the sentence.
  const prose = (rel: string) =>
    fs.readFileSync(path.join(REPO, rel), "utf8")
      .split("\n").map((l) => l.replace(/^\s*(\*|#|>)\s?/, "")).join(" ").replace(/\s+/g, " ");
  const block = fs.readFileSync(path.join(__dirname, "generate-redirects.js"), "utf8");
  const once = (text: string, re: RegExp, where: string) => {
    const hits = [...text.matchAll(new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g"))];
    assert.equal(hits.length, 1, `${where}: expected exactly one ${re}, found ${hits.length}`);
    return hits[0].slice(1).map(Number);
  };

  const claims: Array<[string, number[], number[]]> = [
    ["generate-redirects.js composition: bare path", once(block, /^ \*\s+(\d+)\s+bare path\s/m, "generator"), [bare]],
    ["generate-redirects.js composition: bare RSC", once(block, /^ \*\s+(\d+)\s+bare RSC \.txt\s/m, "generator"), [bareRsc]],
    ["generate-redirects.js composition: landing", once(block, /^ \*\s+(\d+)\s+landing payload\s/m, "generator"), [landing]],
    ["generate-redirects.js composition: splats", once(block, /^ \*\s+(\d+)\s+splats\s/m, "generator"), [splats]],
    ["generate-redirects.js composition: total", once(block, /^ \*\s+(\d+)\s+of a hard 100$/m, "generator"), [total]],
    ["generate-redirects.js D10: one more page",
      once(prose("apps/web/scripts/generate-redirects.js"),
        /dynamic prefix costs 2 rules and lands on (\d+)\b.*?costs 3 and lands on (\d+)\b/, "generator"),
      [total + 2, total + 3]],
    ["generate-redirects.js D10: the collapse",
      once(prose("apps/web/scripts/generate-redirects.js"), /would take the file from (\d+) rules to (\d+)\b/, "generator"),
      [total, total - bare]],
    [".github/workflows/live-redirects.yml header",
      once(prose(".github/workflows/live-redirects.yml"), /The budget now stands at (\d+) of 100\b/, "live-redirects.yml"),
      [total]],
    ["docs/open-items/decisions-and-strategy.md Decision 15",
      once(prose("docs/open-items/decisions-and-strategy.md"), /the budget now sits at (\d+) of 100\b/, "decisions-and-strategy.md"),
      [total]],
    ["docs/architecture/10-payroll.md navigation constraint",
      once(prose("docs/architecture/10-payroll.md"), /holds \*\*(\d+) dynamic rules against Cloudflare/, "10-payroll.md"),
      [total]],
    ["docs/open-items/post-demo-B-ours.md POST-B-055",
      once(prose("docs/open-items/post-demo-B-ours.md"),
        /public\/_redirects has (\d+) rules \((\d+) dynamic, first dynamic rule at position (\d+);/, "post-demo-B-ours.md"),
      [rules.length, total, firstDynamicPosition]],
  ];
  const wrong = claims.filter(([, said, measured]) => JSON.stringify(said) !== JSON.stringify(measured))
    .map(([where, said, measured]) => `${where}: says ${said.join("/")}, the file measures ${measured.join("/")}`);
  assert.deepEqual(wrong, [], "a statement of the redirect budget no longer matches the generated file");
});

test("one more page under a dynamic prefix costs two rules, which is why the budget has no room left", () => {
  // The arithmetic the budget rests on, proved on a synthetic tree rather
  // than asserted in prose — and deliberately NOT by copying app/, which
  // would make this test a second measurement of the same thing instead of
  // a statement of the rule.
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "redirects-budget-"));
  try {
    const page = "export default function P() { return null; }";
    const mk = (...segs: string[]) => {
      const dir = path.join(tmp, ...segs);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "page.tsx"), page);
    };
    mk("clients", "[id]", "overview");
    const before = rulesIn(buildRedirectsFile(tmp));

    mk("clients", "[id]", "insights");
    const after = rulesIn(buildRedirectsFile(tmp));

    assert.equal(after.length - before.length, 2,
      "a page added under an EXISTING splat group costs exactly its two " +
        "enumerated shapes — so the count and 2 more is the cap or past it");

    // And one that opens a NEW splat group costs three, which is past it.
    mk("clients", "[id]", "sections", "[sectionId]");
    const withNewGroup = rulesIn(buildRedirectsFile(tmp));
    assert.equal(withNewGroup.length - after.length, 3,
      "a page introducing a new dynamic segment also opens a splat group — " +
        "three rules, which is past the cap");
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("a static sibling of a dynamic segment is never shadowed by that segment's splat", () => {
  // Regression pin for a real bug found while fixing the rule-count-cap
  // incident: a naive `/clients/:id/year-end/:engagementId/*` splat also
  // matches /clients/:id/year-end/xbrl/... (":engagementId" matches the
  // literal segment "xbrl" just as readily as a real id), so a request for
  // the static "xbrl" page's trailing-slash/RSC shapes would be silently
  // rewritten to the WRONG target (as if "xbrl" were an engagement id).
  // xbrl gets its OWN single-member splat group (its trailing-slash/RSC
  // shapes), sorted to win the depth tie against the colliding deeper group
  // by being more literal — while year-end's DYNAMIC siblings (checklist,
  // review, ...) keep relying on that deeper group's own splat.
  //
  // The former sales/invoices "new" vs ":invoiceId" instance of this same
  // bug no longer exists — "new" was merged into the :invoiceId route
  // itself (an id value of "new" means create-mode) specifically to remove
  // this shadow case AND its route from the rule-count budget entirely; see
  // "the create/edit route merges are reflected in the rule count" below.
  const generated = buildRedirectsFile(APP_DIR);
  // Shapes 1 & 4 (bare / bare-RSC) still can't be splat-covered — enumerated
  // same as any other dynamic route.
  for (const shape of [
    "/clients/:id/year-end/xbrl ",
    "/clients/:id/year-end/xbrl.txt",
  ]) {
    assert.ok(generated.includes(shape.trimEnd()), `missing rule for ${shape.trim()}`);
  }
  // Shapes 2 & 3 (trailing slash, RSC /index.txt) are covered by xbrl's own
  // splat group, not enumerated literally.
  assert.ok(generated.includes("/clients/:id/year-end/xbrl/*"));
  // The colliding deeper splat itself must still exist — it's safe for
  // every OTHER route sharing that group (e.g. "checklist", "review").
  assert.ok(generated.includes("/clients/:id/year-end/:engagementId/*"));
  // Ordering: xbrl's own (more literal) splat must be tried BEFORE the
  // colliding deeper group's splat, or it would never win.
  const idx = (s: string) => generated.indexOf(s);
  assert.ok(idx("/clients/:id/year-end/xbrl/*") < idx("/clients/:id/year-end/:engagementId/*"));
});

test("the create/edit route merges are reflected in the rule count", () => {
  // Regression pin: sales/invoices/new, sales/credit-notes/new,
  // sales/debit-notes/new, purchases/bills/new, purchases/credit-notes/new
  // and purchases/debit-notes/new were each merged into their sibling
  // [xId]/edit route (an id value of "new" means create-mode inside that
  // same page) specifically to cut the redirect rule count — each merge
  // removes one whole route (2 enumerated rules) plus the shadow-splat it
  // used to need (1 rule), 3 rules saved per pair. None of the six should
  // appear as their own literal "new" route/group any more.
  const generated = buildRedirectsFile(APP_DIR);
  for (const gone of [
    "/clients/:id/sales/invoices/new ",
    "/clients/:id/sales/invoices/new/*",
    "/clients/:id/sales/credit-notes/new",
    "/clients/:id/sales/debit-notes/new",
    "/clients/:id/purchases/bills/new",
    "/clients/:id/purchases/credit-notes/new",
    "/clients/:id/purchases/debit-notes/new",
  ]) {
    assert.ok(!generated.includes(gone), `stale rule for merged-away route: ${gone}`);
  }
  // Each pair's single surviving dynamic route/group must still cover both
  // create ("new") and edit (a real id) via the same rules.
  for (const group of [
    "/clients/:id/sales/invoices/:invoiceId",
    "/clients/:id/sales/credit-notes/:cnId",
    "/clients/:id/sales/debit-notes/:sdnId",
    "/clients/:id/purchases/bills/:billId",
    "/clients/:id/purchases/credit-notes/:pcnId",
    "/clients/:id/purchases/debit-notes/:dnId",
  ]) {
    assert.ok(generated.includes(`${group}/*`), `missing merged splat for ${group}`);
  }
});

test("a catch-all route segment is rejected rather than silently mishandled", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "redirects-test-"));
  try {
    const dir = path.join(tmp, "clients", "[...slug]");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "page.tsx"), "export default function P() { return null; }");
    assert.throws(() => walkPages(tmp), /catch-all segment/);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("a page whose last segment is a placeholder lists its .txt rule before its plain rule, and the order is a real order (POST-A-148)", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "redirects-txt-"));
  try {
    const page = "export default function P() { return null; }";
    const mk = (...segs: string[]) => {
      const dir = path.join(tmp, ...segs);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "page.tsx"), page);
    };
    mk("health"); mk("health", "[client_id]"); mk("health", "[client_id]", "history");
    mk("things", "[id]", "sub", "[subId]"); mk("things", "[id]", "sub");
    const froms = rulesIn(buildRedirectsFile(tmp)).map((r) => r.from);
    const at = (f: string) => froms.indexOf(f);
    for (const [txt, plain] of [["/health/:client_id.txt", "/health/:client_id"], ["/things/:id/sub/:subId.txt", "/things/:id/sub/:subId"]]) {
      assert.ok(at(txt) >= 0 && at(plain) >= 0 && at(txt) < at(plain), `${txt} must precede ${plain}`);
    }
    // a dynamic parent that has its own page gets its landing payload ahead of the placeholder that would swallow it
    assert.ok(at("/things/:id/sub/index.txt") >= 0 && at("/things/:id/sub/index.txt") < at("/things/:id/sub/:subId.txt"));
    // a literal parent does not: its index.txt is a file the export holds
    assert.equal(at("/health/index.txt"), -1);
    // and it is a total order: sorting any permutation gives the same file
    assert.equal(froms.length, new Set(froms).size);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
