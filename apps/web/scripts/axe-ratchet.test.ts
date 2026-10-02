// THE ACCESSIBILITY SCAN'S RULES AND ITS RATCHET (frontend_ux-03).
//   node --experimental-strip-types --test scripts/axe-ratchet.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// There was no automated accessibility test of any kind: no axe, no testing library. Contrast, labels and
// focus were audited by hand once and then held as SOURCE rules, which prove a property is written and not that
// the page a person gets passes.
//
// ─────────────────────────────────────────────────────────────────────────────
// WHAT THIS HOLDS
// ─────────────────────────────────────────────────────────────────────────────
// The scan itself needs Chromium and `@axe-core/playwright`, so it runs in the smoke walk (`scripts/smoke-walk.mjs`,
// nightly, `.github/workflows/smoke-walk.yml`). Everything it DECIDES is in `axeAudit.mjs`, with no browser, and
// is held here: which screens are the six that fail outright, what counts as a failure, how the ratchet
// compares what was found with `axe-baseline.json`, and that the walk never reports a clean run it did not earn.
//
// THE BASELINE FILE is held to its own rules: it parses, it is sorted, it may not name a screen that fails
// outright, and every route in it is a route the app still has — so a screen that is deleted cannot leave a
// line behind that nothing will ever judge again.
//
// WHAT IT DOES NOT PROVE: that any page is accessible. That is the walk's result, and the walk's result is
// only as good as the pages it was asked about (the six, and the routes it can render with no data).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  AXE_PACKAGE, AXE_PACKAGE_VERSION, AXE_TAGS, FAILING_IMPACTS, NAMED_ROUTE_PATHS, NAMED_SCREENS,
  auditPage, axeMode, compareToBaseline, describeFailure, failingFindings, initialBaseline, loadAxeBuilder,
  parseBaseline, resolveNamedRoute, serialiseBaseline, settleVerdict, shrinkBaseline, summaryMarkdown,
} from "./axeAudit.mjs";
import { screenRoutes } from "./refresh-screen-snapshot.js";

const WEB = join(import.meta.dirname, "..");

type Finding = { rule: string; impact: string; nodes: number; help: string; targets: string[] };
const finding = (rule: string, nodes = 1, impact = "serious"): Finding => ({ rule, impact, nodes, help: `${rule} help`, targets: [`#${rule}`] });
const found = (obj: Record<string, Finding[]>) => new Map(Object.entries(obj));
const text = (entries: { route: string; rule: string; nodes: number }[]) => JSON.stringify({ entries });

// ═════════════════════════════════════════════════════════════════════════════
// WHAT COUNTS
// ═════════════════════════════════════════════════════════════════════════════

test("only serious and critical violations count, one row per rule, with where to look", () => {
  const rows = failingFindings([
    { id: "label", impact: "critical", help: "Form elements must have labels", nodes: [{ target: ["#email"] }, { target: ["#pw"] }] },
    { id: "color-contrast", impact: "serious", help: "Contrast", nodes: [{ target: ["main", ".hint"] }] },
    { id: "region", impact: "moderate", help: "Landmarks", nodes: [{ target: ["div"] }] },
    { id: "tabindex", impact: "minor", help: "x", nodes: [] },
  ]);
  assert.deepEqual(rows.map((r) => [r.rule, r.impact, r.nodes]), [["color-contrast", "serious", 1], ["label", "critical", 2]]);
  assert.deepEqual(rows[0].targets, ["main .hint"], "a selector path is joined, so a person can find the element");
  assert.deepEqual(FAILING_IMPACTS, ["serious", "critical"]);
  assert.deepEqual(AXE_TAGS, ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);
});

test("a contrast failure names the measured pair, so a person reads a number and not a guess", () => {
  const [row] = failingFindings([{
    id: "color-contrast", impact: "serious", help: "Contrast",
    nodes: [{ target: [".badge"], any: [{ data: { contrastRatio: 3.57, fgColor: "#059669", bgColor: "#ecfdf5", expectedContrastRatio: "4.5:1" } }] }],
  }]);
  assert.deepEqual(row.targets, [".badge [3.57:1, #059669 on #ecfdf5, needs 4.5:1]"]);
  const [plain] = failingFindings([{ id: "label", impact: "critical", help: "", nodes: [{ target: ["#e"], any: [{ data: {} }] }] }]);
  assert.deepEqual(plain.targets, ["#e"], "another rule's data carries no pair and adds nothing");
});

test("a result with nothing usable in it is no findings, not a crash", () => {
  for (const odd of [undefined, null, [], [null], [{}], [{ id: "x" }], "no"]) {
    assert.deepEqual(failingFindings(odd as never), []);
  }
});

test("at most three selectors are kept per rule", () => {
  const nodes = Array.from({ length: 9 }, (_, i) => ({ target: [`#n${i}`] }));
  const [row] = failingFindings([{ id: "label", impact: "critical", help: "", nodes }]);
  assert.equal(row.nodes, 9);
  assert.equal(row.targets.length, 3);
});

// ═════════════════════════════════════════════════════════════════════════════
// THE SIX NAMED SCREENS
// ═════════════════════════════════════════════════════════════════════════════

test("the six named screens are exactly the six the audit named", () => {
  assert.deepEqual(NAMED_SCREENS.map((s) => s.id),
    ["login", "signup", "dashboard", "client-sales", "journal-editor", "firm-menu"]);
});

test("sign in and sign up are scanned signed OUT, because a signed-in visitor is bounced from them", () => {
  const signedOut = NAMED_SCREENS.filter((s) => !s.signedIn).map((s) => s.id);
  assert.deepEqual(signedOut, ["login", "signup"]);
});

test("the firm menu is the dashboard with the menu opened, and the client screens take a client id", () => {
  const menu = NAMED_SCREENS.find((s) => s.id === "firm-menu");
  assert.equal(menu?.route, "/");
  assert.equal(menu?.opens, "firm-menu");
  assert.equal(resolveNamedRoute(NAMED_SCREENS.find((s) => s.id === "client-sales")!, "abc"), "/clients/abc/sales");
  assert.equal(resolveNamedRoute(NAMED_SCREENS.find((s) => s.id === "journal-editor")!, "abc"),
    "/clients/abc/accounting/journal/new/edit", "entryId=new is the create-mode sentinel, so the editor renders instead of 'not found'");
});

test("the routes the baseline may not hold are the named ones that need no client id", () => {
  assert.deepEqual([...NAMED_ROUTE_PATHS].sort(), ["/", "/login", "/signup"]);
});

test("a serious finding on a named screen fails with no allowlist to hide behind", () => {
  const verdict = settleVerdict({
    named: [{ id: "login", label: "Sign in", route: "/login", findings: [finding("label", 1, "critical")] }],
    comparison: { added: [], grew: [], stale: [], lowerable: [] }, auditedRoutes: 3, unaudited: [], partial: false,
  });
  assert.equal(verdict.ok, false);
  assert.equal(verdict.failures[0].kind, "named");
  assert.match(describeFailure(verdict.failures[0]), /Sign in \(\/login\): critical label on 1 element/);
  assert.match(describeFailure(verdict.failures[0]), /no allowlist/);
});

test("a named screen that could not be scanned or landed elsewhere is a failure, not a clean row", () => {
  const verdict = settleVerdict({
    named: [{ id: "login", label: "Sign in", route: "/login", findings: [], error: "landed on /, not /login" }],
    comparison: null, auditedRoutes: 5, unaudited: [], partial: false,
  });
  assert.equal(verdict.ok, false);
  assert.equal(verdict.failures[0].kind, "named_unaudited");
});

// ═════════════════════════════════════════════════════════════════════════════
// THE RATCHET
// ═════════════════════════════════════════════════════════════════════════════

const BASE = [
  { route: "/gst", rule: "color-contrast", nodes: 4 },
  { route: "/tasks", rule: "label", nodes: 1 },
];

test("a pair that is not in the baseline is NEW and fails", () => {
  const c = compareToBaseline(found({ "/gst": [finding("color-contrast", 4), finding("button-name", 2)] }), BASE);
  assert.deepEqual(c.added.map((a) => [a.route, a.rule, a.nodes]), [["/gst", "button-name", 2]]);
});

test("a count above its baseline figure has GROWN and fails", () => {
  const c = compareToBaseline(found({ "/gst": [finding("color-contrast", 5)] }), BASE);
  assert.deepEqual(c.grew.map((g) => [g.route, g.rule, g.from, g.to]), [["/gst", "color-contrast", 4, 5]]);
});

test("a line whose violation has gone is STALE, and says to delete it", () => {
  const c = compareToBaseline(found({ "/gst": [], "/tasks": [finding("label", 1)] }), BASE);
  assert.deepEqual(c.stale, [{ route: "/gst", rule: "color-contrast", nodes: 4 }]);
  const v = settleVerdict({ named: [], comparison: c, auditedRoutes: 2, unaudited: [], partial: false });
  assert.equal(v.ok, false);
  assert.match(describeFailure(v.failures[0]), /no longer fires — delete that line/);
});

test("a count that has FALLEN passes and is reported as one that can be lowered", () => {
  const c = compareToBaseline(found({ "/gst": [finding("color-contrast", 1)], "/tasks": [finding("label", 1)] }), BASE);
  assert.deepEqual(c.added, []); assert.deepEqual(c.grew, []); assert.deepEqual(c.stale, []);
  assert.deepEqual(c.lowerable, [{ route: "/gst", rule: "color-contrast", from: 4, to: 1 }]);
  const v = settleVerdict({ named: [], comparison: c, auditedRoutes: 2, unaudited: [], partial: false });
  assert.equal(v.ok, true, "a ceiling, not an equality: a renderer's patch release must not turn a night red");
  assert.equal(v.lowerable.length, 1);
});

test("a route that was not audited is neither judged nor called stale", () => {
  const c = compareToBaseline(found({ "/gst": [finding("color-contrast", 4)] }), BASE);
  assert.deepEqual(c.stale, [], "/tasks was not asked about, so its line says nothing");
  assert.deepEqual(c.added, []);
});

test("an unchanged page is clean", () => {
  const c = compareToBaseline(found({ "/gst": [finding("color-contrast", 4)], "/tasks": [finding("label", 1)] }), BASE);
  assert.deepEqual([c.added, c.grew, c.stale, c.lowerable], [[], [], [], []]);
});

test("--axe-shrink lowers and deletes, and never adds or raises", () => {
  const out = shrinkBaseline(found({
    "/gst": [finding("color-contrast", 2), finding("button-name", 9)],   // lower one, and a NEW rule that must not be added
    "/tasks": [finding("label", 7)],                                      // grew: must not be raised
  }), BASE);
  assert.deepEqual(out, [{ route: "/gst", rule: "color-contrast", nodes: 2 }, { route: "/tasks", rule: "label", nodes: 1 }]);
  const gone = shrinkBaseline(found({ "/gst": [], "/tasks": [finding("label", 1)] }), BASE);
  assert.deepEqual(gone, [{ route: "/tasks", rule: "label", nodes: 1 }], "a fixed line is deleted");
});

test("--axe-shrink keeps the lines of routes it did not audit exactly as they were", () => {
  const out = shrinkBaseline(found({ "/gst": [] }), BASE);
  assert.deepEqual(out, [{ route: "/tasks", rule: "label", nodes: 1 }]);
});

test("the first baseline never includes a named screen's route", () => {
  const entries = initialBaseline(found({
    "/": [finding("color-contrast", 2)], "/login": [finding("label", 1)],
    "/gst": [finding("color-contrast", 4)],
  }));
  assert.deepEqual(entries, [{ route: "/gst", rule: "color-contrast", nodes: 4 }]);
});

// ═════════════════════════════════════════════════════════════════════════════
// THE BASELINE FILE'S FORMAT
// ═════════════════════════════════════════════════════════════════════════════

test("parseBaseline accepts a well-formed file", () => {
  assert.deepEqual(parseBaseline(text(BASE)), BASE);
});

test("parseBaseline refuses what would let a screen hide", () => {
  assert.throws(() => parseBaseline("nope"), /not JSON/);
  assert.throws(() => parseBaseline("{}"), /entries/);
  assert.throws(() => parseBaseline(text([{ route: "gst", rule: "x", nodes: 1 }])), /route must be a path/);
  assert.throws(() => parseBaseline(text([{ route: "/gst", rule: "", nodes: 1 }])), /rule/);
  assert.throws(() => parseBaseline(text([{ route: "/gst", rule: "x", nodes: 0 }])), /delete the line/);
  assert.throws(() => parseBaseline(text([{ route: "/gst", rule: "x", nodes: 1.5 }])), /whole number/);
  assert.throws(() => parseBaseline(text([BASE[0], BASE[0]])), /listed twice/);
  for (const named of NAMED_ROUTE_PATHS) {
    assert.throws(() => parseBaseline(text([{ route: named, rule: "label", nodes: 1 }])), /six named screens/, named);
  }
});

test("serialiseBaseline sorts, so a diff shows what changed and nothing else, and it round-trips", () => {
  const shuffled = [BASE[1], { route: "/gst", rule: "button-name", nodes: 2 }, BASE[0]];
  const out = serialiseBaseline(shuffled);
  assert.deepEqual(parseBaseline(out).map((e) => `${e.route} ${e.rule}`), ["/gst button-name", "/gst color-contrast", "/tasks label"]);
  assert.equal(out.endsWith("\n"), true);
});

test("the committed baseline file is valid, sorted, and names only routes the app still has", () => {
  const raw = readFileSync(join(WEB, "scripts/axe-baseline.json"), "utf8");
  const entries = parseBaseline(raw);
  assert.equal(raw, serialiseBaseline(entries), "the file must be exactly what --axe-shrink would write: sorted, one format");
  const real = new Set(screenRoutes(join(WEB, "app")).map((r: string) => r.replace(/:[^/]+/g, "_placeholder")));
  const gone = entries.filter((e) => !real.has(e.route)).map((e) => e.route);
  assert.deepEqual([...new Set(gone)], [], "a screen that was deleted must take its baseline lines with it");
  const doc = JSON.parse(raw) as { tags: string[]; impacts: string[] };
  assert.deepEqual(doc.tags, AXE_TAGS);
  assert.deepEqual(doc.impacts, FAILING_IMPACTS);
});

// ═════════════════════════════════════════════════════════════════════════════
// A WALK THAT AUDITED NOTHING IS NOT CLEAN, AND AN ABSENT SCAN SAYS SO
// ═════════════════════════════════════════════════════════════════════════════

test("a run in which no page was audited is not ok, whatever it found", () => {
  const v = settleVerdict({ named: [], comparison: { added: [], grew: [], stale: [], lowerable: [] }, auditedRoutes: 0, unaudited: [], partial: false });
  assert.equal(v.ok, false);
  assert.equal(v.nothingAudited, true);
  assert.equal(v.audited, 0);
  assert.match(summaryMarkdown(v, "x"), /No page was audited/);
});

test("a page axe could not scan is a failure naming it", () => {
  const v = settleVerdict({ named: [], comparison: { added: [], grew: [], stale: [], lowerable: [] }, auditedRoutes: 4, unaudited: [{ route: "/gst", error: "boom" }], partial: false });
  assert.equal(v.ok, false);
  assert.match(describeFailure(v.failures[0]), /\/gst: axe could not scan this page — boom/);
});

test("a clean, honest run is ok and counts the pages it scanned", () => {
  const v = settleVerdict({
    named: NAMED_SCREENS.map((s) => ({ id: s.id, label: s.label, route: s.route, findings: [] })),
    comparison: { added: [], grew: [], stale: [], lowerable: [] }, auditedRoutes: 160, unaudited: [], partial: false,
  });
  assert.equal(v.ok, true);
  assert.equal(v.audited, 166);
});

test("the mode: disabled, missing here (loud), missing in CI (fatal), or running", () => {
  const off = axeMode({ disabled: true, loaded: false, ci: false });
  assert.deepEqual([off.run, off.fatal], [false, false]);
  assert.match(off.line, /NOT RUN \(--no-axe/);

  const local = axeMode({ disabled: false, loaded: false, ci: false });
  assert.deepEqual([local.run, local.fatal], [false, false]);
  assert.match(local.line, /NOT RUN/);
  assert.ok(local.line.includes(AXE_PACKAGE) && local.line.includes(AXE_PACKAGE_VERSION), "it says what to install, at which version");

  const ci = axeMode({ disabled: false, loaded: false, ci: true });
  assert.deepEqual([ci.run, ci.fatal], [false, true], "in CI the workflow installs it, so absent means broken");
  assert.match(ci.line, /FAILED/);

  const on = axeMode({ disabled: false, loaded: true, ci: true });
  assert.deepEqual([on.run, on.fatal], [true, false]);
});

// ═════════════════════════════════════════════════════════════════════════════
// THE TWO THINGS THAT TOUCH THE OUTSIDE
// ═════════════════════════════════════════════════════════════════════════════

test("loadAxeBuilder: the default export, a missing package, and a package that exports nothing usable", async () => {
  class FakeBuilder {}
  assert.equal((await loadAxeBuilder(async () => ({ default: FakeBuilder }))).AxeBuilder, FakeBuilder);
  assert.equal((await loadAxeBuilder(async () => ({ AxeBuilder: FakeBuilder }))).AxeBuilder, FakeBuilder);
  const missing = await loadAxeBuilder(async () => { throw new Error("Cannot find package '@axe-core/playwright'\nmore"); });
  assert.equal(missing.AxeBuilder, undefined);
  assert.match(String(missing.error), /Cannot find package/);
  assert.doesNotMatch(String(missing.error), /\n/, "one line, for a log");
  assert.match(String((await loadAxeBuilder(async () => ({}))).error), /exports no AxeBuilder/);
});

test("auditPage scans with the A/AA tags and reduces to the failing findings", async () => {
  const seen: { tags?: string[]; page?: unknown } = {};
  class FakeBuilder {
    constructor(opts: { page: unknown }) { seen.page = opts.page; }
    withTags(tags: string[]) { seen.tags = tags; return this; }
    async analyze() {
      return { violations: [
        { id: "label", impact: "critical", help: "h", nodes: [{ target: ["#email"] }] },
        { id: "region", impact: "moderate", help: "h", nodes: [{ target: ["div"] }] },
      ] };
    }
  }
  const page = { name: "page" };
  const out = await auditPage(FakeBuilder, page);
  assert.equal(seen.page, page);
  assert.deepEqual(seen.tags, AXE_TAGS);
  assert.deepEqual(out.findings.map((f: Finding) => f.rule), ["label"]);
  assert.equal(out.error, undefined);
});

test("auditPage never throws: a page it could not scan comes back as an error, with no findings", async () => {
  class Boom {
    withTags() { return this; }
    async analyze() { throw new Error("Execution context was destroyed\n   at somewhere"); }
  }
  const out = await auditPage(Boom, {});
  assert.deepEqual(out.findings, []);
  assert.equal(out.error, "Execution context was destroyed");
});

// ═════════════════════════════════════════════════════════════════════════════
// THE WORKFLOW INSTALLS WHAT THE WALK PINS
// ═════════════════════════════════════════════════════════════════════════════

test("the workflow installs the exact version the walk pins, in the walk's own job, never in package.json", () => {
  const wf = readFileSync(join(WEB, "../../.github/workflows/smoke-walk.yml"), "utf8");
  const pinned = /AXE_PLAYWRIGHT_VERSION:\s*"([^"]+)"/.exec(wf)?.[1];
  assert.equal(pinned, AXE_PACKAGE_VERSION, "the workflow and scripts/axeAudit.mjs must name one version");
  assert.match(pinned ?? "", /^\d+\.\d+\.\d+$/, "exact, not a range");
  assert.match(wf, /pnpm add --save-dev[\s\S]*?"@axe-core\/playwright@\$\{AXE_PLAYWRIGHT_VERSION\}"/);
  assert.match(wf, /"playwright-core@\$\{PLAYWRIGHT_VERSION\}"/, "the peer is named at the walk's own Playwright version");
  const pkg = JSON.parse(readFileSync(join(WEB, "package.json"), "utf8")) as Record<string, Record<string, string> | undefined>;
  for (const section of ["dependencies", "devDependencies"]) {
    assert.equal(pkg[section]?.["@axe-core/playwright"], undefined, "the product must not depend on the scanner");
    assert.equal(pkg[section]?.["axe-core"], undefined);
  }
  assert.doesNotMatch(wf, /--no-axe/, "the nightly runs the scan");
});
