// A FULL-SCREEN OVERLAY IS THE SHARED DIALOG, OR IT IS ON THE FROZEN LIST. Run with:
//   node --experimental-strip-types --test scripts/an-overlay-is-the-shared-dialog-or-on-the-frozen-list.test.ts
//
// THE DEFECT (frontend_ux-14, POST-A-130)
//   147 hand-built overlays (`fixed inset-0`) lived in 85 files against a handful of uses of the shared `Modal` and `Drawer`. The shared
//   ones give a dialog its name, close it on Escape, move focus in and give it back and, since this change, keep Tab inside and the page
//   behind it still; a hand-built one has to do each of those itself and almost none does. Migrating them is months of work, file by
//   file, and each migration is a screen to read and drive. What this holds is the direction: NO NEW OVERLAY, and a migrated file leaves
//   the list.
//
// THE RULE
//   Outside `components/ui/` (which is where the primitives live), no source file builds a full-screen fixed overlay unless it is listed
//   below with exactly the number it holds. The list is asserted as an EQUALITY, in both directions: a new overlay fails, and so does a
//   migration that leaves its entry behind, so the list can only shrink.
//
//   An overlay is found as the RULE, not as one spelling: a class string (a JSX attribute, a plain string, a template, an argument of
//   `cn(...)`) that carries the word `fixed` and either `inset-0` or all four of `top-0 right-0 bottom-0 left-0`, in any order, with any
//   other classes. Found with the TypeScript parser, not a regex over the text, so a comment that quotes the class and a different
//   utility (`absolute inset-0`, `fixed bottom-4`) are not overlays.
//
// WHAT THIS DOES NOT SEE
//   An overlay built from class names assembled at run time (`["fixed", "inset-0"].join(" ")`), and one styled in CSS. A `fixed` panel that
//   does not cover the screen (a toast, the sidebar) is deliberately not an overlay. It says nothing about whether a listed file's overlay
//   is accessible; that is the migration it is waiting for.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "out") continue;
      walk(rel, out);
    } else if (/\.tsx$/.test(e.name) && !/\.test\.tsx$/.test(e.name)) {
      out.push(rel);
    }
  }
  return out;
}

/** The product's own components and pages, less the primitives. */
const SOURCES = ["app", "components", "lib"].flatMap((d) => walk(d)).filter((f) => !f.startsWith("components/ui/")).sort();

const CORNERS = ["top-0", "right-0", "bottom-0", "left-0"];

/** Does this class string cover the screen with a fixed layer? */
export function isOverlayClass(classes: string): boolean {
  const tokens = new Set(classes.split(/\s+/).filter(Boolean));
  if (!tokens.has("fixed")) return false;
  return tokens.has("inset-0") || CORNERS.every((c) => tokens.has(c));
}

/** Every overlay in the source, as the line it starts on. */
export function overlays(src: string, name = "x.tsx"): number[] {
  const sf = ts.createSourceFile(name, src, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
  const lines: number[] = [];
  const at = (n: ts.Node) => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
  (function visit(node: ts.Node) {
    // A string, or a template with no holes, is one class string.
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      if (isOverlayClass(node.text)) lines.push(at(node));
    }
    // A template with holes: the parts that are written out are one class string together (`fixed inset-0 ${tone}`).
    if (ts.isTemplateExpression(node)) {
      const written = [node.head.text, ...node.templateSpans.map((s) => s.literal.text)].join(" ");
      if (isOverlayClass(written)) lines.push(at(node));
      // The pieces were judged together; judge nothing inside them twice, but do visit the expressions in the holes.
      for (const span of node.templateSpans) visit(span.expression);
      return;
    }
    ts.forEachChild(node, visit);
  })(sf);
  return lines;
}

function foundInTree(): Record<string, number> {
  const found: Record<string, number> = {};
  for (const rel of SOURCES) {
    const n = overlays(fs.readFileSync(path.join(WEB, rel), "utf8"), rel).length;
    if (n > 0) found[rel] = n;
  }
  return found;
}

/** Every difference between what the tree holds and what the list says. */
export function problems(found: Record<string, number>, frozen: Record<string, number>): string[] {
  const out: string[] = [];
  for (const [file, n] of Object.entries(found)) {
    const listed = frozen[file] ?? 0;
    if (n > listed) {
      out.push(`${file}: ${n} full-screen overlay(s), ${listed} listed. Use the shared Modal or Drawer (components/ui), which name the dialog, close on Escape, trap Tab and give focus back. The list never grows.`);
    }
  }
  for (const [file, listed] of Object.entries(frozen)) {
    const n = found[file] ?? 0;
    if (n < listed) {
      out.push(`${file}: ${n} overlay(s) found and ${listed} listed. The list can only shrink: lower the count or delete the entry.`);
    }
  }
  return out;
}

/**
 * THE FROZEN LIST: file -> the number of hand-built overlays it still holds. Each is waiting to move onto `Modal` or `Drawer`, one file at
 * a time (POST-A-130). It never gains a file or a count.
 */
const FROZEN: Record<string, number> = {
  "app/accounting/account-groups/page.tsx": 1,
  "app/accounting/loans/page.tsx": 2,
  "app/accounting/lock-year/page.tsx": 1,
  "app/accounting/recurring/page.tsx": 1,
  "app/accounting/retainer/page.tsx": 1,
  "app/accounting/suppliers/page.tsx": 1,
  "app/billing/page.tsx": 2,
  "app/client-portal/page.tsx": 1,
  "app/clients/[id]/accounting/page.tsx": 3,
  "app/clients/[id]/compliance/gst/page.tsx": 1,
  "app/clients/[id]/documents/page.tsx": 3,
  "app/clients/[id]/fixed-assets/page.tsx": 3,
  "app/clients/[id]/health/page.tsx": 1,
  "app/clients/[id]/inventory/page.tsx": 3,
  "app/clients/[id]/lifecycle/page.tsx": 1,
  "app/clients/[id]/portal/page.tsx": 1,
  "app/clients/[id]/purchases/page.tsx": 7,
  "app/clients/[id]/relationships/page.tsx": 1,
  "app/clients/[id]/sales/page.tsx": 15,
  "app/clients/documents/page.tsx": 1,
  "app/clients/page.tsx": 3,
  "app/documents/page.tsx": 1,
  "app/engagements/page.tsx": 3,
  "app/gst/gstr1/page.tsx": 1,
  "app/gst/gstr3b/page.tsx": 1,
  "app/gst/page.tsx": 5,
  "app/health/[client_id]/HealthDetailClient.tsx": 1,
  "app/income-tax/capital-gains/page.tsx": 2,
  "app/income-tax/notices/page.tsx": 1,
  "app/income-tax/page.tsx": 3,
  "app/income-tax/section-32/page.tsx": 1,
  "app/income-tax/tax-audit/page.tsx": 1,
  "app/mca/page.tsx": 3,
  "app/payroll/page.tsx": 1,
  "app/pipeline/page.tsx": 2,
  "app/platform/page.tsx": 2,
  "app/relationships/[entity_id]/EntityDetailClient.tsx": 1,
  "app/relationships/page.tsx": 1,
  "app/settings/dsc-tracker/page.tsx": 3,
  "app/settings/firm-hsn-library/page.tsx": 1,
  "app/settings/invoice-templates/page.tsx": 1,
  "app/settings/scheduled-reports/page.tsx": 1,
  "app/settings/statutory-values/page.tsx": 1,
  "app/tasks/page.tsx": 1,
  "app/tasks/templates/page.tsx": 2,
  "app/tds/page.tsx": 2,
  "app/tds/returns/page.tsx": 1,
  "app/team/page.tsx": 5,
  "app/team/workload/page.tsx": 1,
  "app/time/page.tsx": 2,
  "components/ClientFormModal.tsx": 1,
  "components/CsvImportModal.tsx": 1,
  "components/FilingDemoWizard.tsx": 1,
  "components/LazyCsvImportModal.tsx": 1,
  "components/SearchModal.tsx": 1,
  "components/TaskFormModal.tsx": 1,
  "components/accounting/OpeningBalancesTab.tsx": 1,
  "components/banking/AccountsPanel.tsx": 2,
  "components/banking/EntriesTab.tsx": 2,
  "components/banking/EntryDetailModal.tsx": 1,
  "components/banking/FindMatchModal.tsx": 1,
  "components/banking/ReconcileTab.tsx": 1,
  "components/banking/SettleDocumentsModal.tsx": 1,
  "components/banking/SplitAcrossLedgersModal.tsx": 1,
  "components/catalogue/ProductServiceManagerPanel.tsx": 1,
  "components/fixed-assets/CwipTab.tsx": 1,
  "components/gst/RegistrationsTab.tsx": 1,
  "components/inventory/LocationsAndBatches.tsx": 2,
  "components/inventory/StockCountSheet.tsx": 1,
  "components/payroll/AddEmployeeModal.tsx": 1,
  "components/payroll/ApplyStructureModal.tsx": 1,
  "components/payroll/DisburseModal.tsx": 1,
  "components/payroll/EmployeeDrawer.tsx": 1,
  "components/payroll/PortalAccessModal.tsx": 1,
  "components/purchases/AllocatePaymentModal.tsx": 1,
  "components/purchases/BillsOfEntryTab.tsx": 1,
  "components/purchases/LandedCostPanel.tsx": 1,
  "components/purchases/RcmDocumentPanel.tsx": 1,
  "components/purchases/RecurringBills.tsx": 2,
  "components/sales/AllocateReceiptModal.tsx": 1,
  "components/shell/ClientTopBar.tsx": 1,
  "components/shell/UtilityCluster.tsx": 1,
  "components/shell/WorkspaceTopBar.tsx": 1,
  "components/team/MemberAccessDrawer.tsx": 1,
  "components/team/OpenWorkPanel.tsx": 1,
};

test("no source file builds a full-screen overlay that is not on the frozen list", () => {
  assert.deepEqual(problems(foundInTree(), FROZEN), [],
    "A new overlay is a Modal or a Drawer from components/ui; a migrated file lowers its count here.");
});

test("the detector finds an overlay in every spelling and spares what is not one", () => {
  const found: Record<string, string> = {
    "a JSX attribute": `const A = () => <div className="fixed inset-0 z-50 flex" />;`,
    "the other order": `const A = () => <div className="z-50 inset-0 fixed" />;`,
    "a braced string": `const A = () => <div className={"fixed inset-0"} />;`,
    "a template with holes": "const A = ({t}) => <div className={`fixed inset-0 ${t}`} />;",
    "a template with no hole": "const A = () => <div className={`fixed inset-0`} />;",
    "cn()": `const A = () => <div className={cn("flex", "fixed inset-0 bg-black/40")} />;`,
    "a conditional": `const A = ({a}) => <div className={a ? "fixed inset-0 z-50" : "hidden"} />;`,
    "four corners": `const A = () => <div className="fixed top-0 right-0 bottom-0 left-0" />;`,
    "extra classes": `const A = () => <div className="print:hidden fixed inset-0 z-[80] flex items-center" />;`,
  };
  for (const [why, src] of Object.entries(found)) assert.equal(overlays(src).length, 1, `${why} must be found`);
  const spared: Record<string, string> = {
    "absolute, not fixed": `const A = () => <div className="absolute inset-0 bg-black/30" />;`,
    "fixed but not covering": `const A = () => <div className="fixed bottom-4 right-4" />;`,
    "inset on one axis": `const A = () => <div className="fixed inset-x-0 top-0" />;`,
    "three corners": `const A = () => <div className="fixed top-0 right-0 bottom-0" />;`,
    "a comment that quotes it": `// className="fixed inset-0"\nconst A = () => <div className="p-2" />;`,
    "a word that contains it": `const A = () => <div className="prefixed inset-0" />;`,
    "text, not a class": `const A = () => <p>fixed inset-0</p>;`,
  };
  for (const [why, src] of Object.entries(spared)) assert.equal(overlays(src).length, 0, `${why} is not an overlay`);
});

test("the equality fails both ways: a new overlay, and a migration that left its entry behind", () => {
  const found = foundInTree();
  const withNew = problems({ ...found, "app/new-screen/page.tsx": 1 }, FROZEN);
  assert.equal(withNew.length, 1);
  assert.match(withNew[0], /app\/new-screen\/page\.tsx: 1 full-screen overlay/);
  const [first] = Object.keys(found);
  if (first) assert.equal(problems({ ...found, [first]: found[first] + 1 }, FROZEN).length, 1, "one more in a file already listed");
  const [listed] = Object.keys(FROZEN);
  if (listed) {
    const { [listed]: _gone, ...without } = found;
    const stale = problems(without, FROZEN);
    assert.equal(stale.length, 1);
    assert.match(stale[0], /can only shrink/);
  }
});

test("the frozen list is honest: positive integers for files that exist, and never the primitives", () => {
  for (const [file, n] of Object.entries(FROZEN)) {
    assert.ok(SOURCES.includes(file), `${file} is listed but is not a source file`);
    assert.ok(Number.isInteger(n) && n > 0, `${file}: count must be a positive integer`);
    assert.ok(!file.startsWith("components/ui/"), `${file}: the primitives are not on the list`);
  }
});

test("the shared Modal and Drawer are overlays that trap Tab", () => {
  for (const rel of ["components/ui/modal.tsx", "components/ui/drawer.tsx"]) {
    const src = fs.readFileSync(path.join(WEB, rel), "utf8");
    assert.equal(overlays(src, rel).length >= 1, true, `${rel} is an overlay`);
    assert.match(src, /trapTabKey\(/, `${rel} must keep Tab inside the dialog it declares modal`);
    assert.match(src, /lockBodyScroll\(\)/, `${rel} must stop the page behind it from scrolling`);
  }
});

if (process.env.PRINT_FROZEN) {
  const sorted = Object.fromEntries(Object.entries(foundInTree()).sort(([a], [b]) => a.localeCompare(b)));
  console.log("FROZEN " + JSON.stringify(sorted));
}
