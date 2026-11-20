// POST-A-530: where a screen sits on the page and what it draws while it waits are MEASURED in a browser
// (scripts/walkAudits.mjs `measureFrame`, run by `smoke-walk.mjs --frame`), and the screens not yet right are a committed list
// that only shrinks (scripts/frame-baseline.json). This file holds what can be held without a browser: the two verdicts, the
// judge that compares a run with the list, the list's own shape, and that the screens converted so far stay converted.
// Run with: node --experimental-strip-types --test scripts/a-screen-sits-in-the-page-frame-and-waits-with-a-shape.test.ts
//
// WHAT IS NOT TESTED HERE. That a screen really is centred or really draws a placeholder is a fact about a browser; the walk
// measures it and fails on a screen that is newly wrong or a line of the list nobody deleted. This file would stay green if
// every screen on the list were still broken, which is what the list says they are.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { frameBaselineFrom, judgeFrame, layoutVerdict, waitingVerdict, HUGS_LEFT_BY } from "./walkAudits.mjs";
import { walkPages } from "./generate-redirects.js";

const web = path.join(import.meta.dirname, "..");
const baseline = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, "frame-baseline.json"), "utf8"));
const waiting = (over: object) => ({ pulses: 0, status: 0, spinners: 0, bare: [], inStatus: [], text: "", asked: 3, ...over });

test("what a screen draws while it waits is read as a shape, words, the screen itself, or nothing", () => {
  assert.equal(waitingVerdict(waiting({ pulses: 12, status: 1 })), "placeholders");
  assert.equal(waitingVerdict(waiting({ pulses: 4, bare: ["Loading…"] })), "placeholders, and bare words");
  assert.equal(waitingVerdict(waiting({ bare: ["Loading billing…"], text: "Loading billing…" })), "bare words");
  // A status region that holds only words (the line Billing Schedules drew) is not a shape.
  assert.equal(waitingVerdict(waiting({ status: 1, inStatus: ["Loading billing…"], text: "Loading billing…" })), "words or a spinner, no shape");
  assert.equal(waitingVerdict(waiting({ spinners: 1 })), "words or a spinner, no shape");
  // A screen that draws its own title and pickers at once has nothing to wait for until a person chooses.
  assert.equal(waitingVerdict(waiting({ text: "GSTR-1 Review Select a client" })), "the screen itself");
  assert.equal(waitingVerdict(waiting({})), "nothing");
  assert.equal(waitingVerdict(waiting({ asked: 0 })), "static");
  assert.equal(waitingVerdict(null), "unread");
});

test("a container with far more room on its right than its left hugs the left, and a centred or full one does not", () => {
  const box = (left: number, right: number) => ({ main: 1920, width: 1920 - left - right, left, right, cap: "none", depth: 1, cls: "" });
  assert.equal(layoutVerdict(box(0, 1024)), "hugs the left");            // p-6 max-w-4xl, no mx-auto, at the wide window
  assert.equal(layoutVerdict(box(160, 160)), "centred");                 // max-w-ps-data mx-auto
  assert.equal(layoutVerdict(box(0, 0)), "full width");
  assert.equal(layoutVerdict(box(100, 100 + HUGS_LEFT_BY)), "centred");  // at the limit, not past it
  assert.equal(layoutVerdict(box(100, 101 + HUGS_LEFT_BY)), "hugs the left");
  assert.equal(layoutVerdict(null), "outside the shell");
});

test("the judge fails a screen that is newly wrong and a line a run has cleared, and leaves an unmeasured line alone", () => {
  const list = { hugs_left: ["/a", "/unmeasured"], no_placeholder: ["/b"] };
  const rows = [
    { route: "/a", layout: "centred", waiting: "placeholders" },                      // cleared: its line must go
    { route: "/b", layout: "centred", waiting: "words or a spinner, no shape" },      // still on the list, still wrong: silent
    { route: "/c", layout: "hugs the left", waiting: "nothing" },                     // wrong twice, on neither list
    { route: "/d", layout: "full width", waiting: "the screen itself" },              // right
  ];
  const verdict = judgeFrame(rows, list);
  assert.deepEqual(verdict.stale, [{ list: "hugs_left", route: "/a" }]);
  assert.deepEqual(verdict.fresh.map((f) => `${f.list} ${f.route}`), ["hugs_left /c", "no_placeholder /c"]);
  // The list a run writes keeps what it did not measure and names what it found.
  assert.deepEqual(frameBaselineFrom(rows, list), { hugs_left: ["/c", "/unmeasured"], no_placeholder: ["/b", "/c"] });
  // A client's screen is judged under its key, not under the stub client's id.
  assert.deepEqual(judgeFrame([{ route: "/clients/0000/x", key: "/clients/{client}/x", layout: "hugs the left", waiting: "static" }],
    { hugs_left: ["/clients/{client}/x"], no_placeholder: [] }), { fresh: [], stale: [] });
});

test("the committed list is sorted, has no line twice, and names only screens that exist", () => {
  const routes = new Set<string>((walkPages(path.join(web, "app")) as string[][]).map((segments) => "/" + segments.join("/")));
  const toRoute = (key: string) => key.replace("/clients/{client}", "/clients/:id").replace(/_placeholder/g, ":x");
  const shape = (r: string) => r.replace(/:[A-Za-z_]+/g, ":x");
  const known = new Set([...routes].map(shape));
  for (const name of ["hugs_left", "no_placeholder"] as const) {
    const lines: string[] = baseline[name];
    assert.deepEqual(lines, [...lines].sort(), `${name} is not sorted`);
    assert.equal(lines.length, new Set(lines).size, `${name} names a screen twice`);
    const unknown = lines.filter((k) => !known.has(shape(toRoute(k))));
    assert.deepEqual(unknown, [], `${name} names a screen that is not in app/ (deleted or renamed: delete its line)`);
  }
  assert.deepEqual(Object.keys(baseline).sort(), ["hugs_left", "no_placeholder"]);
});

test("the list only shrinks: it is no longer than it was when it was written", () => {
  // 20-11-2026: 6 and 55 after the Practice menu; 0 and 50 after Approvals, E-Invoice, Knowledge, Data Migration and the Team
  // menu. No screen hugs the left any more, so that list stays EMPTY. Lower the second when a pull request shortens the list.
  assert.deepEqual(baseline.hugs_left, [], "a screen hugs the left again: put it in the page frame");
  // 29 after the one-line word loaders (the hub worklists, Payroll, Settings, Insights and others) took a shape; EMPTY after
  // the hand-made spinners, the count subtitles, the calendar and the last single loaders did. Both lists stay empty: a
  // screen that is newly wrong is fixed, not listed.
  assert.deepEqual(baseline.no_placeholder, [], "a screen waits without a shape again: give it a placeholder");
});

test("the Practice menu's screens use the one frame and are on neither list", () => {
  const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
  const pages = ["", "ar/", "benchmark/", "billing/", "collections/", "compliance/", "instructions/", "profitability/", "revenue/"];
  for (const p of pages) {
    const src = strip(fs.readFileSync(path.join(web, "app/practice", p, "page.tsx"), "utf8"));
    assert.match(src, /pageFrameClass\("(data|form)"/, `app/practice/${p}page.tsx types its own wrapper`);
    assert.doesNotMatch(src, /className="p-(4|6|8)[^"]*max-w-/, `app/practice/${p}page.tsx caps a padded wrapper by hand`);
    assert.doesNotMatch(src, />\s*Loading[^<{]*…?\s*<\/LoadingRegion>/, `app/practice/${p}page.tsx waits as words`);
  }
  const listed = [...baseline.hugs_left, ...baseline.no_placeholder].filter((k: string) => k.startsWith("/practice"));
  assert.deepEqual(listed, []);
});

test("the frame centres whatever it caps, and the placeholder is a loading region in the frame", () => {
  const src = fs.readFileSync(path.join(web, "components/ui/page-frame.tsx"), "utf8");
  assert.match(src, /cn\("mx-auto w-full p-6", WIDTH\[width\], className\)/);
  assert.match(src, /data: "max-w-ps-data"/);
  assert.match(src, /<LoadingRegion label=\{label\} className=\{pageFrameClass\(width,/);
});
