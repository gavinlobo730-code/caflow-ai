// A DATE A PERSON TYPES GOES THROUGH ONE FIELD. Run with:
//   node --experimental-strip-types --test scripts/a-date-a-person-types-goes-through-one-field.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT (frontend_ux-19)
// ─────────────────────────────────────────────────────────────────────────────
// `<input type="date">` is drawn by the BROWSER, in the browser's locale:
// mm/dd/yyyy in a US-locale browser, a segmented mask that cannot be typed into
// in one go, a calendar popup everywhere — and an Indian clerk types 15/03/2026,
// or 15/3, or just 15, and expects the financial year to supply the rest. There
// were 177 of them in `app/`, `components/` and `lib/`, and no date component in
// `components/ui`. `components/ui/date-input.tsx` is that component; the reading
// rule it wires is `lib/dates/typedDate.ts`.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE, IN THREE PARTS
// ─────────────────────────────────────────────────────────────────────────────
//  1. NO NATIVE DATE INPUT, IN ANY SPELLING, OUTSIDE THE FROZEN LIST. The list is
//     a map file -> count, each entry with a CATEGORY and the reason it is still
//     there, asserted as an EQUALITY with what the tree holds, in both
//     directions: a new native input fails, and so does a conversion that leaves
//     its entry behind — the list can only shrink. It is found with the
//     TypeScript parser rather than a regex, because the defect has as many
//     spellings as there are ways to write the word `date` into a `type`: a
//     string attribute in either quote, a braced literal, a template, a
//     conditional (`type={wide ? "date" : "text"}`, which is how one screen of
//     this product wrote it), an object handed to `createElement`, a spread, a
//     `setAttribute` and an assignment. The detector is tested on each.
//  2. EVERY `<DateInput>` NAMES ITSELF. An id that a `<label htmlFor>` in the
//     same file points at, an `aria-label`/`aria-labelledby`, or an enclosing
//     `<label>`: a box with none of them is announced as "edit text" and nothing
//     else (frontend_ux-12's finding about the sign-in screen, again). A local
//     `Field` wrapper is NOT taken as naming it — whether such a wrapper ties its
//     label to its children is a fact about that file, and two of the three this
//     product has do not.
//  3. EVERY `<DateInput>` THAT A FORM SAVES REPORTS WHAT IT HOLDS. An unreadable
//     date is handed up as `""`, which for an OPTIONAL date is what a blank box
//     hands up — so a form that does not ask would save without the date and say
//     nothing. `onStateChange` (fed to `useDateProblems`) is how it asks. The one
//     kind of field that needs no gate is a FILTER, where blank means "no bound"
//     and the inline message under the box is the whole answer; those are in a
//     second frozen list, with the same equality in both directions.
//
// WHAT THIS CANNOT SEE, AND SAYS SO
//   A `type` held in a variable (`const t = "date"; <input type={t}>`) and a
//   spread of an object built elsewhere. A native month, week or datetime-local
//   picker is a different control and is not counted here (`type="month"` is
//   `YYYY-MM`, not a day). It says nothing about a screen's own VALIDATION of a
//   date: the period lock, a filed return, the financial-year window are the
//   server's, and this rule is only about which control a person types into.
//   There is no browser harness, so what the field DOES when somebody types is
//   held by `lib/dates/typedDate.test.ts`, the render test beside the component
//   and the browser run recorded in the commit message.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.resolve(import.meta.dirname, "..");
const COMPONENT = "components/ui/date-input.tsx";

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "out") continue;
      walk(rel, out);
    } else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name)) {
      out.push(rel);
    }
  }
  return out;
}

/** The product's own source. Not scripts/ (these tests quote the forms they ban)
 *  and not tests. */
const SOURCES = ["app", "components", "lib"].flatMap((d) => walk(d)).sort();

function parse(src: string, name = "x.tsx"): ts.SourceFile {
  return ts.createSourceFile(name, src, ts.ScriptTarget.ES2022, true, name.endsWith(".ts") ? ts.ScriptKind.TS : ts.ScriptKind.TSX);
}

// ── 1. Native date inputs, in every spelling ─────────────────────────────────

/** Is `text` the word that makes a native date picker? HTML's `type` is
 *  case-insensitive, so `DATE` is one too. */
const isDateWord = (text: string) => text.trim().toLowerCase() === "date";

/** Does an expression CAN evaluate to the literal `date` — a literal, a template
 *  without holes, or one of those anywhere in a conditional, a parenthesis, an
 *  `as const`, a `||`/`??` chain. */
function mayBeDate(node: ts.Node | undefined): boolean {
  if (!node) return false;
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return isDateWord(node.text);
  if (ts.isTemplateExpression(node)) return isDateWord(node.head.text) && node.templateSpans.length === 0;
  if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isSatisfiesExpression(node)
    || ts.isNonNullExpression(node) || ts.isTypeAssertionExpression(node)) return mayBeDate(node.expression);
  if (ts.isConditionalExpression(node)) return mayBeDate(node.whenTrue) || mayBeDate(node.whenFalse);
  if (ts.isBinaryExpression(node)) return mayBeDate(node.left) || mayBeDate(node.right);
  if (ts.isJsxExpression(node)) return mayBeDate(node.expression);
  return false;
}

const propName = (p: ts.ObjectLiteralElementLike): string | null =>
  p.name && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) ? p.name.text : null;

/** An object literal with a `type` property that may be `date`. */
function objectTypesDate(node: ts.Node | undefined): boolean {
  if (!node) return false;
  if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)) return objectTypesDate(node.expression);
  if (!ts.isObjectLiteralExpression(node)) return false;
  return node.properties.some((p) => {
    if (ts.isSpreadAssignment(p)) return objectTypesDate(p.expression);
    return ts.isPropertyAssignment(p) && propName(p) === "type" && mayBeDate(p.initializer);
  });
}

const ELEMENT_FACTORY = /(?:^|\.)(?:createElement|cloneElement|jsx|jsxs|jsxDEV|h)$/;

export interface Hit { line: number; how: string }

/** Every place the source makes a native date input, with how it spelled it. */
export function nativeDateInputs(src: string, name = "x.tsx"): Hit[] {
  const sf = parse(src, name);
  const hits: Hit[] = [];
  const at = (n: ts.Node) => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
  (function visit(node: ts.Node) {
    // <anything type="date" /> — a wrapper component that forwards `type` is as
    // native as the input it renders.
    if (ts.isJsxAttribute(node) && node.name.getText(sf) === "type" && mayBeDate(node.initializer)) {
      hits.push({ line: at(node), how: "jsx attribute" });
    }
    // {...{ type: "date" }}
    if (ts.isJsxSpreadAttribute(node) && objectTypesDate(node.expression)) {
      hits.push({ line: at(node), how: "jsx spread" });
    }
    if (ts.isCallExpression(node)) {
      const callee = node.expression.getText(sf);
      // createElement("input", { type: "date" }) and its relatives.
      if (ELEMENT_FACTORY.test(callee) && node.arguments.slice(1).some(objectTypesDate)) {
        hits.push({ line: at(node), how: "element factory" });
      }
      // el.setAttribute("type", "date")
      if (/\.setAttribute$/.test(callee) && node.arguments.length >= 2
        && ts.isStringLiteral(node.arguments[0]) && node.arguments[0].text === "type" && mayBeDate(node.arguments[1])) {
        hits.push({ line: at(node), how: "setAttribute" });
      }
    }
    // el.type = "date"
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
      && ts.isPropertyAccessExpression(node.left) && node.left.name.text === "type" && mayBeDate(node.right)) {
      hits.push({ line: at(node), how: "assignment" });
    }
    ts.forEachChild(node, visit);
  })(sf);
  return hits;
}

test("the detector sees every spelling it is meant to ban", () => {
  const spellings: Record<string, string> = {
    "double quotes": `<input type="date" value={x} />`,
    "single quotes": `<input type='date' value={x} />`,
    "upper case": `<input type="DATE" />`,
    "braced literal": `<input type={"date"} />`,
    "braced single": `<input type={'date'} />`,
    "template": "<input type={`date`} />",
    "conditional": `<input type={wide ? "date" : "text"} />`,
    "conditional, other branch": `<input type={wide ? "text" : "date"} />`,
    "as const": `<input type={"date" as const} />`,
    "fallback chain": `<input type={kind || "date"} />`,
    "a wrapper component": `<Field label="From" type="date" value={x} />`,
    "the product's Input": `<Input type="date" value={x} />`,
    "a spread": `<input {...{ type: "date" }} />`,
    "a spread, quoted key": `<input {...{ "type": "date" }} />`,
    "createElement": `createElement("input", { type: "date" })`,
    "React.createElement": `React.createElement(Input, { type: "date", value })`,
    "jsx()": `jsx("input", { type: "date" })`,
    "createElement with a spread": `createElement("input", { ...rest, type: "date" })`,
    "setAttribute": `el.setAttribute("type", "date")`,
    "assignment": `el.type = "date"`,
  };
  for (const [name, src] of Object.entries(spellings)) {
    assert.equal(nativeDateInputs(src).length, 1, `${name}: ${src}`);
  }
});

test("the detector leaves a different control, a comment and a column definition alone", () => {
  const innocent: Record<string, string> = {
    "a text box": `<input type="text" />`,
    "a native month picker is another control": `<input type="month" />`,
    "datetime-local": `<input type="datetime-local" />`,
    "the date component": `<DateInput value={x} onChange={setX} />`,
    "a placeholder that says date": `<input placeholder="date" />`,
    "a name that says date": `<input name="date" id="date" />`,
    "a comment": `// <input type="date" />\n/* type="date" */ const x = 1;`,
    "a string that mentions it": `const s = 'use <input type="date">';`,
    "a column definition": `const cols = [{ key: "d", type: "date" }];`,
    "a typed column": `type Col = { type?: "amount" | "text" | "date" };`,
    "a type that is not a literal": `<input type={t} />`,
    "a template with a hole": "<input type={`${a}date`} />",
    "the word date inside a longer one": `<input type="update" />`,
    "an unrelated setAttribute": `el.setAttribute("name", "date")`,
    "an unrelated assignment": `el.name = "date"`,
    "createElement of something else": `createElement("input", { name: "date" })`,
  };
  for (const [name, src] of Object.entries(innocent)) {
    assert.deepEqual(nativeDateInputs(src), [], `${name}: ${src}`);
  }
});

test("a native date input in a plain .ts file is found too", () => {
  assert.equal(nativeDateInputs(`export const make = () => createElement("input", { type: "date" });`, "lib/x.ts").length, 1);
});

/** file -> how many native date inputs are still there. */
function foundInTree(): Record<string, number> {
  const found: Record<string, number> = {};
  for (const rel of SOURCES) {
    const n = nativeDateInputs(fs.readFileSync(path.join(WEB, rel), "utf8"), rel).length;
    if (n > 0) found[rel] = n;
  }
  return found;
}

type Category = "needs-a-gate" | "acts-on-change" | "bank-editor";

/**
 * WHY A FILE IS STILL ON THE LIST. Every native input that was a FILTER, a report
 * period or an as-at date has been converted (they save nothing, so an unreadable
 * date costs a filter and the message under the box is the whole answer); what is
 * left is data entry that has to be given a gate, plus the bank screens.
 *
 *   needs-a-gate    a data-entry date whose form has not been given a validity
 *                   gate (part 3 of the rule above). Converting it without one would
 *                   let an unreadable OPTIONAL date save as blank. Each needs its
 *                   save path read — to find what a blank means there, and to add
 *                   `useDateProblems` — which is the work, not a regex.
 *   acts-on-change  a field whose CHANGE is the action: the box is uncontrolled and
 *                   picking a date writes. A field that hands its value up when the
 *                   person has finished is not a drop-in there; the action wants an
 *                   explicit button first.
 *   bank-editor     the bank screens (a register's range, a reconciliation period,
 *                   a cheque date). The spreadsheet-style keyboard-entry change
 *                   touches these files next, and converting them underneath it is a
 *                   merge for nobody's benefit.
 */
const CATEGORY_REASON: Record<Category, string> = {
  "needs-a-gate": "a data-entry date whose save path has not been read and gated",
  "acts-on-change": "its change is the write, so it is not a drop-in",
  "bank-editor": "the keyboard-entry change touches the bank editors next",
};

/**
 * THE FROZEN LIST. A file leaves it by being converted, and a file that is
 * converted while still listed fails the equality below. It never gains a file
 * or a count: a new date field is a `<DateInput>`.
 */
const FROZEN: Record<string, { count: number; category: Category; note: string }> = {
  "app/accounting/loans/page.tsx": { count: 4, category: "needs-a-gate", note: "loan disbursement and maturity, FD start and maturity" },
  "app/accounting/recurring/page.tsx": { count: 2, category: "needs-a-gate", note: "recurring journal template: start and an optional end" },
  "app/accounting/retainer/page.tsx": { count: 1, category: "needs-a-gate", note: "retainer next-run date" },
  "app/accounting/trial-balance-import/page.tsx": { count: 1, category: "needs-a-gate", note: "opening date of an imported trial balance" },
  "app/client-portal/page.tsx": { count: 1, category: "needs-a-gate", note: "due date on a document request to a client" },
  "app/clients/[id]/compliance/gst/page.tsx": { count: 2, category: "needs-a-gate", note: "GST filed-on dates, which lock a period" },
  "app/clients/[id]/compliance/mca/page.tsx": { count: 2, category: "needs-a-gate", note: "director appointment date, MCA filing date" },
  "app/clients/[id]/compliance/tds/page.tsx": { count: 2, category: "needs-a-gate", note: "lower-deduction certificate validity" },
  "app/clients/[id]/health/page.tsx": { count: 1, category: "needs-a-gate", note: "health override expiry" },
  "app/clients/[id]/lifecycle/page.tsx": { count: 1, category: "needs-a-gate", note: "renewal date" },
  "app/clients/[id]/purchases/page.tsx": { count: 1, category: "needs-a-gate", note: "no-PE declaration date on a vendor" },
  "app/clients/[id]/sales/page.tsx": { count: 2, category: "needs-a-gate", note: "recurring invoice: start and an optional end" },
  "app/clients/[id]/tax/computation/page.tsx": { count: 1, category: "needs-a-gate", note: "housing loan sanction date" },
  "app/clients/[id]/tax/filing/page.tsx": { count: 2, category: "needs-a-gate", note: "ITR acknowledgement dates" },
  "app/clients/[id]/year-end/[engagementId]/adjustments/_page.tsx": { count: 1, category: "needs-a-gate", note: "year-end adjustment date" },
  "app/clients/documents/page.tsx": { count: 1, category: "needs-a-gate", note: "document expiry date" },
  "app/einvoice/page.tsx": { count: 1, category: "needs-a-gate", note: "e-invoice date" },
  "app/engagements/page.tsx": { count: 2, category: "needs-a-gate", note: "engagement start and expiry" },
  "app/gst/page.tsx": { count: 3, category: "needs-a-gate", note: "GST due and filed dates, which lock a period" },
  "app/health/[client_id]/HealthDetailClient.tsx": { count: 1, category: "needs-a-gate", note: "health override expiry" },
  "app/income-tax/advance-tax/page.tsx": { count: 3, category: "needs-a-gate", note: "advance tax paid, furnished and deposit dates" },
  "app/income-tax/capital-gains/page.tsx": { count: 6, category: "needs-a-gate", note: "capital gains purchase, sale and claim dates" },
  "app/income-tax/notices/page.tsx": { count: 2, category: "needs-a-gate", note: "notice received and response due" },
  "app/income-tax/page.tsx": { count: 3, category: "needs-a-gate", note: "ITR due and filed dates" },
  "app/income-tax/tax-audit/page.tsx": { count: 2, category: "needs-a-gate", note: "audit report and filing dates" },
  "app/mca/page.tsx": { count: 3, category: "needs-a-gate", note: "MCA due and filed dates" },
  "app/pipeline/page.tsx": { count: 2, category: "needs-a-gate", note: "CRM last contact and next follow-up" },
  "app/settings/dsc-tracker/page.tsx": { count: 6, category: "needs-a-gate", note: "DSC issue and expiry dates" },
  "app/settings/statutory-values/page.tsx": { count: 2, category: "needs-a-gate", note: "statutory value effective and notified dates, through a wrapper that forwards `type`" },
  "app/tasks/page.tsx": { count: 1, category: "needs-a-gate", note: "task due date" },
  "app/tasks/templates/page.tsx": { count: 1, category: "needs-a-gate", note: "task template due date" },
  "components/TaskFormModal.tsx": { count: 1, category: "needs-a-gate", note: "task due date" },
  "components/banking/AccountsPanel.tsx": { count: 1, category: "bank-editor", note: "bank screen: filters, a period and a cheque date" },
  "components/banking/BankBook.tsx": { count: 2, category: "bank-editor", note: "bank screen: filters, a period and a cheque date" },
  "components/banking/FindMatchModal.tsx": { count: 2, category: "bank-editor", note: "bank screen: filters, a period and a cheque date" },
  "components/banking/PostDatedChequesPanel.tsx": { count: 2, category: "bank-editor", note: "bank screen: filters, a period and a cheque date" },
  "components/banking/ReconcileTab.tsx": { count: 2, category: "bank-editor", note: "bank screen: filters, a period and a cheque date" },
  "components/banking/WorthALookTab.tsx": { count: 2, category: "bank-editor", note: "bank screen: filters, a period and a cheque date" },
  "components/catalogue/ProductServiceFormModal.tsx": { count: 1, category: "needs-a-gate", note: "opening stock balance date" },
  "components/catalogue/ProductServiceManagerPanel.tsx": { count: 1, category: "needs-a-gate", note: "opening stock balance date for an import" },
  "components/currency/FxRatesPanel.tsx": { count: 1, category: "needs-a-gate", note: "date of a typed exchange rate" },
  "components/fixed-assets/CwipTab.tsx": { count: 5, category: "needs-a-gate", note: "CWIP project and tranche dates" },
  "components/gst/ExpiringEwayBills.tsx": { count: 1, category: "needs-a-gate", note: "e-way bill extension valid-upto" },
  "components/gst/Itc04Panel.tsx": { count: 2, category: "needs-a-gate", note: "job-work lot return dates" },
  "components/gst/RegistrationsTab.tsx": { count: 2, category: "needs-a-gate", note: "registration effective and closing dates" },
  "components/inventory/CostFormulaPanel.tsx": { count: 1, category: "needs-a-gate", note: "costing method effective date" },
  "components/inventory/LocationsAndBatches.tsx": { count: 3, category: "needs-a-gate", note: "transfer date, batch made and expiry" },
  "components/invoices/CompliancePanel.tsx": { count: 3, category: "needs-a-gate", note: "IRN acknowledgement date and e-way bill dates" },
  "components/payroll/AddEmployeeModal.tsx": { count: 3, category: "needs-a-gate", note: "date of birth, joining date, PF-on-actual-wages date" },
  "components/payroll/ApplyStructureModal.tsx": { count: 1, category: "needs-a-gate", note: "salary structure effective date" },
  "components/payroll/EmployeeDrawer.tsx": { count: 5, category: "needs-a-gate", note: "joining, leaving, payment, effective and start dates" },
  "components/payroll/StatutoryHandoff.tsx": { count: 1, category: "needs-a-gate", note: "statutory hand-off date" },
  "components/purchases/RecurringBills.tsx": { count: 2, category: "needs-a-gate", note: "recurring bill template: start and an optional end" },
  "components/sales/SalesCycleTab.tsx": { count: 1, category: "acts-on-change", note: "an uncontrolled field whose change IS the write: it records goods back on the date picked" },
  "components/tax/HousePropertyWorksheet.tsx": { count: 2, category: "needs-a-gate", note: "loan taken and completion dates" },
  "components/tax/UnforeseenIncomePanel.tsx": { count: 1, category: "needs-a-gate", note: "date an unforeseen income arose" },
};

/** Every problem between what the tree holds and what the list says. */
export function frozenProblems(
  found: Record<string, number>,
  frozen: Record<string, { count: number }>,
  what = "native date input(s)",
  fix = "use <DateInput> from components/ui/date-input",
): string[] {
  const problems: string[] = [];
  for (const [file, n] of Object.entries(found)) {
    const listed = frozen[file]?.count ?? 0;
    if (n > listed) problems.push(`${file}: ${n} ${what}, ${listed} allowed — ${fix}`);
  }
  for (const [file, { count }] of Object.entries(frozen)) {
    const n = found[file] ?? 0;
    if (n < count) {
      problems.push(`${file}: listed with ${count} but has ${n} — the list can only shrink, so lower or delete its entry`);
    }
  }
  return problems;
}

test("the scan reads the tree it claims to (not vacuous)", () => {
  assert.ok(SOURCES.length > 400, `only ${SOURCES.length} source files were scanned`);
  assert.ok(SOURCES.includes(COMPONENT), "the date component is outside the scan");
  assert.ok(SOURCES.includes("lib/dates/typedDate.ts"));
});

test("no screen, component or library makes a native date input outside the frozen list", () => {
  assert.deepEqual(frozenProblems(foundInTree(), FROZEN), [],
    "A date a person types goes through <DateInput> (components/ui/date-input.tsx). " +
    "The native control reads mm/dd/yyyy in a US-locale browser and cannot be typed into.");
});

test("the frozen list is honest: each entry has a known category, a note and a count", () => {
  for (const [file, e] of Object.entries(FROZEN)) {
    assert.ok(SOURCES.includes(file), `${file} is listed but is not a source file`);
    assert.ok(e.category in CATEGORY_REASON, `${file}: unknown category ${e.category}`);
    assert.ok(e.note.trim().length > 8, `${file}: a frozen entry says what its dates are`);
    assert.ok(Number.isInteger(e.count) && e.count > 0, `${file}: count must be a positive integer`);
  }
  // Nothing on the bank list is outside the bank screens, and nothing else claims
  // to be there: a category is a statement about the file, not a place to park it.
  for (const [file, e] of Object.entries(FROZEN)) {
    assert.equal(file.startsWith("components/banking/"), e.category === "bank-editor", `${file}: category ${e.category}`);
  }
});

test("a filter, a report period and an as-at date are not on the list: they were converted", () => {
  // The bank screens aside, none of what is left is read-only. If one of these
  // returns as a native input it fails the equality above; this names why.
  for (const file of [
    "components/PeriodPicker.tsx", "components/ui/data-table.tsx", "app/reports/page.tsx",
    "app/settings/audit-log/page.tsx", "app/time/page.tsx", "components/purchases/VendorStatementsTab.tsx",
    "components/sales/OverdueInterestPanel.tsx", "app/clients/[id]/reports/ageing/page.tsx",
    "app/portal/dashboard/page.tsx", "app/clients/[id]/accounting/page.tsx",
  ]) {
    assert.equal(FROZEN[file], undefined, `${file} is a filter or report period and is converted`);
  }
});

test("the equality fails both ways: a new native input, and a conversion that left its entry behind", () => {
  const found = foundInTree();
  // NEGATIVE CONTROL 1 — a new native date input anywhere.
  const withNew = frozenProblems({ ...found, "app/new-screen/page.tsx": 1 }, FROZEN);
  assert.equal(withNew.length, 1);
  assert.match(withNew[0], /app\/new-screen\/page\.tsx: 1 native date input/);
  // …and one MORE in a file that already has some.
  const [first] = Object.keys(found);
  if (first) {
    assert.equal(frozenProblems({ ...found, [first]: found[first] + 1 }, FROZEN).length, 1);
  }
  // NEGATIVE CONTROL 2 — a file converted while its entry is still listed.
  const [listed] = Object.keys(FROZEN);
  if (listed) {
    const { [listed]: _gone, ...without } = found;
    const stale = frozenProblems(without, FROZEN);
    assert.equal(stale.length, 1);
    assert.match(stale[0], /can only shrink/);
  }
});

// ── 2 and 3. Every <DateInput> names itself, and says what it holds ──────────

interface Use { line: number; id: string | null; named: boolean; gated: boolean }

/** Every `<DateInput …>` in a source, with whether it is named and whether it
 *  reports its state. */
export function dateInputUses(src: string, name = "x.tsx"): Use[] {
  const sf = parse(src, name);
  const uses: Use[] = [];
  const htmlFors = new Set<string>();
  (function collect(node: ts.Node) {
    if (ts.isJsxAttribute(node) && node.name.getText(sf) === "htmlFor" && node.initializer && ts.isStringLiteral(node.initializer)) {
      htmlFors.add(node.initializer.text);
    }
    ts.forEachChild(node, collect);
  })(sf);
  (function visit(node: ts.Node) {
    if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(sf) === "DateInput") {
      const attrs = node.attributes.properties.filter(ts.isJsxAttribute);
      const has = (n: string) => attrs.some((a) => a.name.getText(sf) === n);
      const id = attrs.find((a) => a.name.getText(sf) === "id");
      const idText = id?.initializer && ts.isStringLiteral(id.initializer) ? id.initializer.text : null;
      // An enclosing <label> — the one wrapper whose naming is visible in the
      // source. A local `Field` component may or may not render one around its
      // children (the fixed-assets screen's draws its label BESIDE them), so a
      // box inside one of those carries an aria-label of its own.
      let inLabel = false;
      for (let p: ts.Node | undefined = node.parent; p; p = p.parent) {
        if (ts.isJsxElement(p) && /^(?:label|Label)$/.test(p.openingElement.tagName.getText(sf))) { inLabel = true; break; }
      }
      uses.push({
        line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
        id: idText,
        named: has("aria-label") || has("aria-labelledby") || inLabel || (idText !== null && htmlFors.has(idText)),
        gated: has("onStateChange"),
      });
    }
    ts.forEachChild(node, visit);
  })(sf);
  return uses;
}

test("the DateInput detector tells a named field from a bare one, and a gated one from an ungated one", () => {
  const named = (src: string) => dateInputUses(src).map((u) => u.named);
  const gated = (src: string) => dateInputUses(src).map((u) => u.gated);
  assert.deepEqual(named(`<DateInput value={x} onChange={f} />`), [false]);
  assert.deepEqual(named(`<DateInput aria-label="From" value={x} onChange={f} />`), [true]);
  assert.deepEqual(named(`<DateInput aria-labelledby="h" value={x} onChange={f} />`), [true]);
  assert.deepEqual(named(`<><label htmlFor="d">Date</label><DateInput id="d" value={x} onChange={f} /></>`), [true]);
  assert.deepEqual(named(`<><label htmlFor="other">Date</label><DateInput id="d" value={x} onChange={f} /></>`), [false],
    "an id no label points at names nothing");
  assert.deepEqual(named(`<DateInput id="d" value={x} onChange={f} />`), [false], "an id alone names nothing");
  assert.deepEqual(named(`<label>Date <DateInput value={x} onChange={f} /></label>`), [true]);
  assert.deepEqual(named(`<Field label="Date"><DateInput value={x} onChange={f} /></Field>`), [false],
    "a wrapper component's label is not visible here: the box names itself");
  assert.deepEqual(named(`<Field label="Date"><DateInput aria-label="Date" value={x} onChange={f} /></Field>`), [true]);
  assert.deepEqual(named(`<div><DateInput value={x} onChange={f} /></div>`), [false]);
  assert.deepEqual(gated(`<DateInput value={x} onChange={f} />`), [false]);
  assert.deepEqual(gated(`<DateInput value={x} onChange={f} onStateChange={dates.watch("d", "Date")} />`), [true]);
  assert.equal(dateInputUses(`<input type="text" />`).length, 0);
});

function usesInTree(): Record<string, Use[]> {
  const out: Record<string, Use[]> = {};
  for (const rel of SOURCES) {
    if (rel === COMPONENT) continue;
    const src = fs.readFileSync(path.join(WEB, rel), "utf8");
    if (!src.includes("DateInput")) continue;
    const uses = dateInputUses(src, rel);
    if (uses.length) out[rel] = uses;
  }
  return out;
}

test("every <DateInput> in the product is named to a screen reader", () => {
  const uses = usesInTree();
  const total = Object.values(uses).reduce((n, u) => n + u.length, 0);
  assert.ok(total >= 19, `only ${total} DateInput uses were read — the scan is broken`);
  const bare = Object.entries(uses).flatMap(([file, us]) => us.filter((u) => !u.named).map((u) => `${file}:${u.line}`));
  assert.deepEqual(bare, [],
    "A box with no label, aria-label or aria-labelledby is announced as 'edit text'. Give it an id and a " +
    "<label htmlFor>, or an aria-label.");
});

/**
 * Part 3's second list: the DateInputs that do NOT report their state, file -> count.
 * Each is a FILTER (blank means no bound, so an unreadable date costs a filter,
 * and the message under the box is the whole answer). A form that saves a date
 * is gated with `useDateProblems` instead, and a file is never added here.
 */
const UNGATED: Record<string, { count: number; reason: string }> = {
  "app/clients/[id]/accounting/page.tsx": { count: 2, reason: "the ledger's from and to; blank is an unbounded ledger, nothing is saved" },
  "app/clients/[id]/inventory/page.tsx": { count: 3, reason: "stock as-at date and the stock ledger's range; nothing is saved" },
  "app/clients/[id]/reports/ageing/page.tsx": { count: 1, reason: "ageing as-at date; the screen declines a blank one" },
  "app/clients/[id]/sales/page.tsx": { count: 2, reason: "a customer statement's period; nothing is saved" },
  "app/portal/dashboard/page.tsx": { count: 2, reason: "the client portal's statement period; nothing is saved" },
  "app/reports/page.tsx": { count: 2, reason: "a report's custom period; nothing is saved" },
  "app/settings/audit-log/page.tsx": { count: 2, reason: "the audit log's date filter; nothing is saved" },
  "app/time/page.tsx": { count: 2, reason: "the time export's range; blank exports everything" },
  "components/PeriodPicker.tsx": { count: 2, reason: "the shared custom range; blank is unbounded" },
  "components/purchases/VendorStatementsTab.tsx": { count: 2, reason: "a vendor statement's period; nothing is saved" },
  "components/sales/OverdueInterestPanel.tsx": { count: 1, reason: "the as-at date of a preview; the panel declines a blank one" },
  "components/ui/data-table.tsx": { count: 2, reason: "every list's date-range filter; blank is no bound" },
};

test("every <DateInput> a form saves reports its state; the ones that do not are filters, listed", () => {
  const ungated: Record<string, number> = {};
  for (const [file, us] of Object.entries(usesInTree())) {
    const n = us.filter((u) => !u.gated).length;
    if (n > 0) ungated[file] = n;
  }
  assert.deepEqual(frozenProblems(ungated, UNGATED, "DateInput(s) with no onStateChange",
    "pass onStateChange={dates.watch(key, label)} and refuse the save on dates.first"), [],
    "Pass onStateChange={dates.watch(key, label)} from useDateProblems (lib/dates/useDateProblems.ts) and refuse the " +
    "save on `dates.first`: an unreadable date is handed up as \"\", which an optional date treats as blank.");
  for (const [file, e] of Object.entries(UNGATED)) {
    assert.ok(e.reason.trim().length > 10, `${file}: an ungated field says why it needs no gate`);
  }
});

// ── The five editors the finding names are on it, and gated ─────────────────

test("the voucher, invoice, purchase bill, receipt and payment editors use the field and are gated", () => {
  const uses = usesInTree();
  // file -> how many <DateInput> it must hold, and which of them (by id) are the
  // editor's own date. The receipt and payment forms live in pages that also hold
  // list filters, so the page as a whole is not all gated; the form's field is.
  const want: Record<string, { n: number; ids?: string[] }> = {
    "components/journal/JournalEditor.tsx": { n: 1 },
    "components/invoices/InvoiceEditor.tsx": { n: 3 },
    "components/purchases/PurchaseBillEditor.tsx": { n: 3 },
    "app/clients/[id]/sales/page.tsx": { n: 1, ids: ["receipt-date"] },
    "app/clients/[id]/purchases/page.tsx": { n: 1, ids: ["vendor-payment-date"] },
  };
  for (const [file, { n, ids }] of Object.entries(want)) {
    const us = uses[file] ?? [];
    assert.ok(us.length >= n, `${file}: expected at least ${n} <DateInput>, found ${us.length}`);
    const mine = ids ? us.filter((u) => u.id !== null && ids.includes(u.id)) : us;
    assert.equal(mine.length, ids ? ids.length : us.length, `${file}: the editor's own date field is missing`);
    assert.ok(mine.every((u) => u.gated), `${file}: a money document's date must report its state`);
    // …and the save is refused over it: `dates.first` is read where the save begins.
    assert.match(fs.readFileSync(path.join(WEB, file), "utf8"), /dates\.first/, `${file}: the save does not read dates.first`);
  }
});

test("no native date input remains in the voucher, invoice and purchase bill editors' own files", () => {
  const found = foundInTree();
  for (const file of [
    "components/journal/JournalEditor.tsx",
    "components/invoices/InvoiceEditor.tsx",
    "components/purchases/PurchaseBillEditor.tsx",
  ]) {
    assert.equal(found[file] ?? 0, 0, `${file} still has a native date input`);
  }
});

if (process.env.PRINT_DATE_INPUTS) {
  test("print", () => {
    const f = foundInTree();
    const u: Record<string, number> = {};
    for (const [file, us] of Object.entries(usesInTree())) {
      const n = us.filter((x) => !x.gated).length;
      if (n) u[file] = n;
    }
    console.log("FOUND " + JSON.stringify(f));
    console.log("UNGATED " + JSON.stringify(u));
    console.log("TOTAL " + Object.values(f).reduce((a, b) => a + b, 0));
  });
}
