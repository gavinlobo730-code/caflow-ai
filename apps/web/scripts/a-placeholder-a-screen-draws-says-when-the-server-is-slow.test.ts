// A PLACEHOLDER A SCREEN DRAWS ITSELF SAYS WHEN THE SERVER IS SLOW, AS THE SHARED SKELETONS DO (POST-A-147).
//   node --experimental-strip-types --test scripts/a-placeholder-a-screen-draws-says-when-the-server-is-slow.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// The API sleeps on a free tier and a cold start takes up to a minute. frontend_ux-05 put a sentence ("The server
// is waking up …", after three seconds) into every shared loading primitive in `components/ui/skeleton.tsx` and
// `AsyncBoundary`, and `a-loading-region-says-when-the-server-is-slow.test.ts` holds those. But a screen that drew
// its own placeholder (a block of `Skeleton` pieces, a spinner with "Loading…", a hand-made pulsing block) said
// nothing however long it waited: on 16-11-2026 that was 218 marks in 79 files, the home dashboard's lists, the hub,
// the client workspace's overview, health and year-end pages, every document drawer and the report screens among
// them, which is most of what a demo opens first.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE
// ─────────────────────────────────────────────────────────────────────────────
// Every placeholder mark drawn outside the two files that own the notice sits inside a `LoadingRegion` (the shared
// region for a placeholder a screen composes itself, which carries the notice) or is named below with its reason.
// A MARK is a `Skeleton` piece (`Skeleton`, `SkeletonText`, `MetricCardSkeleton`, `ClientHeaderSkeleton`), a spinner
// (`Loader2`, `Spinner`, anything classed `animate-spin`) or a hand-made placeholder (classed `animate-pulse` or
// `skeleton-shimmer`). It is judged by what the file draws and not by a list of today's screens:
//   * a mark inside a `LoadingRegion`, or handed to `AsyncBoundary` as its `skeleton`, is covered;
//   * a mark inside a component function of the same file is covered when every place that file draws that
//     component is covered (the invoice editor's `FieldSkeleton` is drawn only inside its `LoadingRegion`);
//   * a SPINNER inside a control (a button, a link, a menu item, a tab, or an `icon` handed to one) is that
//     control's own work, very often a save, and the notice must never sit there: a Retry beside a save would
//     send it twice. It is not counted, by rule;
//   * everything else is on NOT_A_READ_WAIT below, each mark named by the component it is drawn in and its kind, with
//     why it waits on no read; the list is exact, so a new uncovered mark in a listed file fails too.
//
// WHAT IT DOES NOT PROVE: that the sentence is painted where it reads well on each screen (the drive does that for
// the screens it opens: `scripts/drive/scenarios/slowServer.mjs`), or that a read listed as covered is a read and
// not a write. A `LoadingRegion` offers no Retry, so a mistaken one says a true sentence and sends nothing.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { loadModule, requireFromWeb } from "./tsxHarness.ts";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

/** Files that own the notice and draw the shared primitives; their own rule is the other test. */
const OWNERS = new Set(["components/ui/skeleton.tsx", "components/ui/states.tsx"]);

/**
 * The marks that are not a wait on a read, by file: how many, and why. A reason names what the mark waits on.
 * Shrink it; a line added here is a decision that a placeholder says nothing however long it waits. Each mark is named by the
 * component it is drawn in and its kind, so a listed mark taken away cannot make room for a new bare one somewhere else.
 */
const NOT_A_READ_WAIT: Record<string, { marks: string[]; why: string }> = {
  "app/DashboardContent.tsx": { marks: Array(4).fill("DashboardContent:Skeleton"), why: "the four KPI tiles' figures load with the Recent Clients and Pending Tasks lists below (one `loading` flag), whose regions speak for the same read" },
  "app/auth/reset-password/page.tsx": { marks: ["ResetPasswordPage:spinner"], why: "waits on the sign-in service reading the reset link, not on this product's server" },
  "app/clients/[id]/accounting/page.tsx": { marks: ["LedgerDrillDown:spinner"], why: "a busy mark beside the ledger's date filters; the ledger below draws a TableSkeleton while it reads (the same `loading` flag)" },
  "app/clients/[id]/inventory/page.tsx": { marks: ["StockLedgerDrillDown:spinner"], why: "a busy mark beside the stock register's date filters; the register below draws a TableSkeleton while it reads (the same `loading` flag)" },
  "app/clients/[id]/page.tsx": { marks: ["ClientRootPage:spinner"], why: "a redirect in the browser to the client's overview; nothing is read" },
  "app/clients/[id]/reports/ageing/page.tsx": { marks: ["MsmeSelect:spinner"], why: "a supplier's MSME status being saved, shown inside its picker: a change" },
  "app/clients/[id]/tax/26as/page.tsx": { marks: ["Form26ASPage:spinner"], why: "an uploaded file's row status (still being read on the server), not a wait of this screen" },
  "app/clients/[id]/year-end/[engagementId]/_workspace.tsx": { marks: [...Array(5).fill("YearEndWorkspaceInner:Skeleton"), "YearEndWorkspace:Skeleton"], why: "three header chips that wait on the engagement read (the stage page drawn below them waits on the same server and its own region speaks); two blocks shown while the engagement is read from the address's own query string; and the Suspense fallback for that query string, which waits on no server" },
  "app/clients/[id]/year-end/[engagementId]/adjustments/_page.tsx": { marks: ["AdjustmentsPage:spinner"], why: "an adjustment row's action in progress, which is a change" },
  "app/engagements/page.tsx": { marks: ["EngagementsPage:spinner"], why: "the Suspense fallback for the address's query string; it waits on no server" },
  "app/migration/page.tsx": { marks: ["MigrationPage:spinner"], why: "an import running on the server, which is a change" },
  "app/not-found.tsx": { marks: ["NotFound:spinner"], why: "a redirect in the browser to the client page the address names; nothing is read" },
  "app/portal/activate/page.tsx": { marks: ["PortalActivatePage:spinner"], why: "the wait includes accepting the invitation, which is a change" },
  "app/portal/employee/activate/page.tsx": { marks: ["EmployeeActivatePage:spinner"], why: "the wait includes accepting the invitation, which is a change" },
  "app/settings/security/page.tsx": { marks: ["MfaCard:spinner"], why: "waits on the sign-in service listing the second factors, not on this product's server, so the sentence would not be true" },
  "app/time/page.tsx": { marks: ["TimeTrackingPage:placeholder"], why: "the running timer's pulsing dot; nothing is loading" },
  "components/banking/AccountsPanel.tsx": { marks: ["BankAccounts:spinner"], why: "a busy mark in the Transactions heading; the region under the heading speaks for the same read (the same `txnsLoading` flag)" },
  "components/banking/EntriesTab.tsx": { marks: ["EntriesTab:spinner"], why: "the progress of a bulk action on bank lines, which is a change" },
  "components/invoices/InvoiceEditorSkeleton.tsx": { marks: Array(4).fill("InvoiceToolbarSkeleton:Skeleton"), why: "the toolbar's stand-in buttons, drawn beside the editor's own region, which speaks for the same read" },
  "components/ui/combobox.tsx": { marks: Array(2).fill("ComboboxInner:spinner"), why: "a busy mark inside the field while its options load; the field is the control" },
};

const PIECES = new Set(["Skeleton", "SkeletonText", "MetricCardSkeleton", "ClientHeaderSkeleton"]);
const SPINNERS = new Set(["Loader2", "Spinner"]);
const CONTROLS = /^(button|Button|a|Link|DropdownMenuItem|Action|TabsTrigger|SelectTrigger)$/;
const PLACEHOLDER_CLASS = /\banimate-pulse\b|\bskeleton-shimmer\b/;
const SPIN_CLASS = /\banimate-spin\b/;

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(join(WEB, dir))) {
    if (name === "node_modules" || name === ".next" || name === "out" || name.startsWith(".")) continue;
    const rel = `${dir}/${name}`;
    if (statSync(join(WEB, rel)).isDirectory()) out.push(...sourceFiles(rel));
    else if (rel.endsWith(".tsx") && !/\.test\.tsx?$/.test(rel)) out.push(rel);
  }
  return out;
}

const tagOf = (n: ts.Node): string | null =>
  ts.isJsxSelfClosingElement(n) || ts.isJsxOpeningElement(n) ? n.tagName.getText() : null;

function classText(n: ts.JsxSelfClosingElement | ts.JsxOpeningElement): string {
  const attr = n.attributes.properties.find((p) => ts.isJsxAttribute(p) && p.name.getText() === "className");
  return attr ? attr.getText() : "";
}

/** The JSX tag of the element that contains `n` (not `n` itself), walking up through expressions. */
function enclosingTags(n: ts.Node): { tag: string; via?: string }[] {
  const out: { tag: string; via?: string }[] = [];
  let attr: string | undefined;
  for (let p = n.parent; p; p = p.parent) {
    if (ts.isJsxAttribute(p)) attr = p.name.getText();
    if (ts.isJsxElement(p) && p.openingElement !== n) { out.push({ tag: p.openingElement.tagName.getText() }); attr = undefined; }
    if ((ts.isJsxSelfClosingElement(p) || ts.isJsxOpeningElement(p)) && attr) { out.push({ tag: p.tagName.getText(), via: attr }); attr = undefined; }
  }
  return out;
}

/** The top-level function (or const arrow) a node sits in, by name. */
function ownerFunction(n: ts.Node): string | null {
  let name: string | null = null;
  for (let p: ts.Node | undefined = n; p; p = p.parent) {
    if (ts.isFunctionDeclaration(p) && p.name && ts.isSourceFile(p.parent)) name = p.name.text;
    if (ts.isVariableDeclaration(p) && ts.isIdentifier(p.name) && p.initializer
      && (ts.isArrowFunction(p.initializer) || ts.isFunctionExpression(p.initializer))
      && ts.isVariableDeclarationList(p.parent) && ts.isVariableStatement(p.parent.parent) && ts.isSourceFile(p.parent.parent.parent)) {
      name = p.name.text;
    }
  }
  return name;
}

type Mark = { line: number; kind: string; covered: boolean; inControl: boolean; owner: string | null; node: ts.Node };

/** Every mark a file draws and whether it is covered, with one level of same-file indirection resolved to a fixed point. */
export function marksOf(rel: string, text: string): Mark[] {
  const sf = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const marks: Mark[] = [];
  const uses = new Map<string, ts.Node[]>(); // component name -> JSX opening/self-closing nodes that draw it
  const directlyCovered = (n: ts.Node) =>
    enclosingTags(n).some((e) => e.tag === "LoadingRegion" || (e.tag === "AsyncBoundary" && e.via === "skeleton"));
  const references = new Map<string, number>(); // identifier -> how many times it is referred to, its declaration aside
  const countRefs = (n: ts.Node) => {
    if (ts.isIdentifier(n) && !(n.parent && (ts.isFunctionDeclaration(n.parent) || ts.isVariableDeclaration(n.parent)) && (n.parent as ts.NamedDeclaration).name === n)
      && !(n.parent && ts.isJsxClosingElement(n.parent))) {
      references.set(n.text, (references.get(n.text) ?? 0) + 1);
    }
    ts.forEachChild(n, countRefs);
  };
  countRefs(sf);
  const visit = (n: ts.Node) => {
    const tag = tagOf(n);
    if (tag) {
      (uses.get(tag) ?? uses.set(tag, []).get(tag)!).push(n);
      const el = n as ts.JsxSelfClosingElement | ts.JsxOpeningElement;
      const cls = classText(el);
      const kind = PIECES.has(tag) ? tag : SPINNERS.has(tag) || SPIN_CLASS.test(cls) ? "spinner" : PLACEHOLDER_CLASS.test(cls) ? "placeholder" : null;
      if (kind) {
        const inControl = kind === "spinner" && enclosingTags(n).some((e) => CONTROLS.test(e.tag) || e.via === "icon" || e.via === "leftIcon");
        marks.push({ line: sf.getLineAndCharacterOfPosition(n.getStart()).line + 1, kind, covered: directlyCovered(n), inControl, owner: ownerFunction(n), node: n });
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  // A component drawn only inside covered places covers what it draws. A function that is itself a piece's
  // definition (a file's own `Skeleton`) is judged by its uses the same way.
  const coveredFns = new Set<string>();
  for (let changed = true; changed;) {
    changed = false;
    for (const [name, nodes] of uses) {
      if (coveredFns.has(name) || !/^[A-Z]/.test(name)) continue;
      const decl = sf.statements.find((s) => (ts.isFunctionDeclaration(s) && s.name?.text === name)
        || (ts.isVariableStatement(s) && s.declarationList.declarations.some((d) => ts.isIdentifier(d.name) && d.name.text === name)));
      if (!decl) continue;
      // Exported, or referred to as a value (`fallback={Row}`, `Row()`), it may be drawn where this file cannot see.
      if (ts.canHaveModifiers(decl) && ts.getModifiers(decl)?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) continue;
      if (references.get(name) !== nodes.length) continue;
      if (nodes.every((u) => directlyCovered(u) || (ownerFunction(u) !== null && coveredFns.has(ownerFunction(u)!)))) {
        coveredFns.add(name); changed = true;
      }
    }
  }
  for (const m of marks) if (!m.covered && m.owner && coveredFns.has(m.owner)) m.covered = true;
  // A file's own piece definition is not itself a mark: its uses are.
  return marks.filter((m) => !(m.owner && PIECES.has(m.owner) && uses.has(m.owner) && sf.statements.some((s) => ts.isFunctionDeclaration(s) && s.name?.text === m.owner)));
}

const uncovered = (rel: string, text = read(rel)) => marksOf(rel, text).filter((m) => !m.covered && !m.inControl);

const FILES = ["app", "components", "lib"].flatMap(sourceFiles).filter((f) => !OWNERS.has(f));

test("every placeholder a screen draws is inside a LoadingRegion, or is named with why it waits on no read", () => {
  const found: Record<string, Mark[]> = {};
  for (const f of FILES) {
    const marks = uncovered(f);
    if (marks.length) found[f] = marks;
  }
  const named = (m: Mark) => `${m.owner ?? "(module)"}:${m.kind}`;
  const problems: string[] = [];
  for (const [f, marks] of Object.entries(found)) {
    const listed = NOT_A_READ_WAIT[f];
    const at = marks.map((m) => `${named(m)} at line ${m.line}`).join(", ");
    if (!listed) problems.push(`${f}: ${marks.length} placeholder(s) say nothing however long they wait (${at}): put them in a LoadingRegion`);
    else if (JSON.stringify(marks.map(named).sort()) !== JSON.stringify([...listed.marks].sort())) {
      problems.push(`${f}: the uncovered marks are ${at}; the list names ${listed.marks.join(", ")}`);
    }
  }
  for (const f of Object.keys(NOT_A_READ_WAIT)) {
    if (!found[f]) problems.push(`${f} is on the list and draws no uncovered mark any more: take it off`);
  }
  assert.deepEqual(problems, []);
});

test("the walk is not vacuous: it finds the marks and the regions that cover them", () => {
  let marks = 0, covered = 0, controls = 0;
  for (const f of FILES) for (const m of marksOf(f, read(f))) { marks++; if (m.covered) covered++; if (m.inControl) controls++; }
  assert.ok(marks > 200, `found only ${marks} marks`);
  assert.ok(covered > 100, `found only ${covered} covered marks`);
  assert.ok(controls > 20, `found only ${controls} spinners inside a control`);
});

test("every reason on the list says what the mark waits on", () => {
  for (const [f, { marks, why }] of Object.entries(NOT_A_READ_WAIT)) {
    assert.ok(marks.length > 0, `${f}: a list of nothing`);
    assert.ok(why.length > 30, `${f}: the reason is too short to say anything`);
  }
});

test("self-test: a bare placeholder, one in a region, one drawn through a component, a spinner in a button and one beside it", () => {
  const sample = `
    import { Skeleton, LoadingRegion } from "@/components/ui/skeleton";
    function Row() { return <div><Skeleton className="h-3" /></div>; }
    function Stray() { return <Skeleton className="h-3" />; }
    export default function Page({ loading, saving }: { loading: boolean; saving: boolean }) {
      if (loading) return <LoadingRegion label="Loading"><Row /><Row /></LoadingRegion>;
      return (
        <div>
          <Stray />
          <div className="h-9 animate-pulse" />
          <button>{saving ? <Loader2 className="animate-spin" /> : "Save"}</button>
          {saving && <Loader2 className="animate-spin" />}
          <AsyncBoundary loading={loading} skeleton={<Skeleton className="h-4" />}>x</AsyncBoundary>
        </div>
      );
    }`;
  const marks = marksOf("Sample.tsx", sample);
  const byLine = (l: number) => marks.find((m) => m.line === l)!;
  assert.equal(byLine(3).covered, true, "Row is drawn only inside the region");
  assert.equal(byLine(4).covered, false, "Stray is drawn outside one");
  assert.equal(byLine(10).covered, false, "a hand-made pulse block outside a region");
  assert.equal(byLine(11).inControl, true, "a spinner in a button is the button's own work");
  assert.equal(byLine(12).inControl, false, "a spinner beside it is not");
  assert.equal(byLine(13).covered, true, "AsyncBoundary's skeleton is covered by the boundary's notice");
  assert.deepEqual(uncovered("Sample.tsx", sample).map((m) => m.line), [4, 10, 12]);
});

test("self-test: a component that is exported, or handed on as a value, is not trusted to be drawn only inside a region", () => {
  const sample = `
    import { Skeleton, LoadingRegion } from "@/components/ui/skeleton";
    export function Exported() { return <Skeleton className="h-3" />; }
    function AsValue() { return <Skeleton className="h-3" />; }
    export const ExportedConst = () => <Skeleton className="h-3" />;
    export default function Page() {
      return <LoadingRegion label="x"><Exported /><AsValue /><ExportedConst /><Suspense fallback={AsValue}>y</Suspense></LoadingRegion>;
    }`;
  assert.deepEqual(uncovered("Sample.tsx", sample).map((m) => m.line), [3, 4, 5]);
});

test("negative control: a listed mark taken away does not make room for a new bare one elsewhere in the file", () => {
  const rel = "components/banking/AccountsPanel.tsx";
  const text = read(rel);
  const moved = text.replace("{txnsLoading && <RefreshCw size={13} className=\"animate-spin text-ps-hint\" />}", "")
    + "\nexport function Stray() { return <Loader2 className=\"animate-spin\" />; }\n";
  assert.notEqual(moved, text, "premise: the busy mark was there to take away");
  const marks = uncovered(rel, moved).map((m) => `${m.owner}:${m.kind}`);
  assert.deepEqual(marks, ["Stray:spinner"], "the same count, a different mark");
  assert.notDeepEqual(marks, NOT_A_READ_WAIT[rel].marks);
});

test("negative control: the dashboard with its list region taken away names the placeholders it left bare", () => {
  const rel = "app/DashboardContent.tsx";
  const text = read(rel);
  const open = '<LoadingRegion label="Loading recent clients" noticeClassName="px-5">';
  const at = text.indexOf(open);
  const close = text.indexOf("</LoadingRegion>", at);
  assert.ok(at > 0 && close > at, "premise: the dashboard's Recent Clients region is where this test expects it");
  const broken = text.slice(0, at) + "<div>" + text.slice(at + open.length, close) + "</div>" + text.slice(close + "</LoadingRegion>".length);
  assert.notEqual(broken, text, "premise: the region was there to take away");
  assert.equal(uncovered(rel, broken).length - uncovered(rel).length, 3, "the three Skeleton pieces of each Recent Clients row");
});

// ── The region itself, rendered ─────────────────────────────────────────────────────────────────────────────────

const React = requireFromWeb("react") as typeof import("react");
const { renderToStaticMarkup } = requireFromWeb("react-dom/server") as typeof import("react-dom/server");
const h = React.createElement;
type Cmp = React.ComponentType<Record<string, unknown>>;
const skeletons = loadModule<Record<string, Cmp>>("components/ui/skeleton");
const states = loadModule<{ AsyncBoundary: Cmp }>("components/ui/states");
const noticesIn = (html: string) => (html.match(/data-slow-server-notice="/g) ?? []).length;

test("a LoadingRegion is a labelled status region with one notice, silent on first paint, and no Retry", () => {
  const html = renderToStaticMarkup(h(skeletons.LoadingRegion, { label: "Loading the hub", className: "grid" }, h("p", null, "Loading…")));
  assert.match(html, /^<div role="status" aria-label="Loading the hub" class="grid">/);
  assert.equal(noticesIn(html), 1);
  assert.match(html, /data-slow-server-notice="quiet"/);
  assert.doesNotMatch(html, /Retry/);
});

test("a shared skeleton inside a LoadingRegion does not say it a second time, and a LoadingRegion inside AsyncBoundary does not either", () => {
  const nested = renderToStaticMarkup(h(skeletons.LoadingRegion, { label: "Loading sales" }, h(skeletons.TableSkeleton, { rows: 3 })));
  assert.equal(noticesIn(nested), 1, "the region's scope covers the table's own notice");
  const inBoundary = renderToStaticMarkup(h(states.AsyncBoundary, { loading: true, skeleton: h(skeletons.LoadingRegion, { label: "x" }) }, h("p", null, "data")));
  assert.equal(noticesIn(inBoundary), 1, "the boundary's notice speaks; the region's is covered");
});
