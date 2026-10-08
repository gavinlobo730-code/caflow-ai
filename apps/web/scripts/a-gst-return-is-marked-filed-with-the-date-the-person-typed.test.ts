// A GST RETURN IS MARKED FILED WITH THE DATE THE CA TYPED, NEVER WITH ONE THE
// SCREEN OR THE SERVER WORKED OUT (PRE-A-007).
//   node --experimental-strip-types --test scripts/a-gst-return-is-marked-filed-with-the-date-the-person-typed.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// `markGSTR3BFiled` and `markGSTR1Filed` (lib/data/gst.ts) PATCHed the GST
// workspace status route with `{status, ca_approved, arn}` and no date, although
// the route has always accepted `filed_date`. The server then did
// `filed_date = filed_date or ist_today()`, so a return filed on the portal on
// the 11th and recorded here on the 14th was stamped the 14th. That column is
// what `journal_period_lock_reason` quotes in its lock message and what the
// s.37(3) / s.39(9) / s.16(4) correction window is measured from.
//
// The server now refuses a submit without a date (apps/api, test_a_gst_return_is_
// filed_on_the_date_the_ca_stated.py). This file is the browser half, and it
// states the RULE, not the two functions: nothing in apps/web may ask a GST
// status route to mark a return submitted without a date, and the date it sends
// is a thing a person stated and not a thing the code computed.
//
//   1. A call to either mark-filed function passes a date as its fourth argument,
//      and that argument is a plain identifier or property read — not a literal
//      and not a computation (`todayLocalISO()`, `new Date()`, `x ?? today`,
//      `x || today`, a conditional). A default dressed as an argument is the
//      server's old behaviour moved into the browser.
//   2. In the two pages, that identifier is React state that starts without a
//      call: the dialog is where the CA types it.
//   3. Any object that says `status: "submitted"` in a file that talks to a GST
//      status route carries `filed_date`; so does any call in such a file that
//      hands the literal "submitted" to a helper with an options object.
//   4. The two functions declare `filedDate: string` with no `?`, no default and
//      no clock in the body, and send it as `filed_date`.
//   5. The API client's `GSTStatusUpdate` type makes `filed_date` required on the
//      "submitted" member, so a caller that forgets it does not compile.
//   6. The two firm-level dialogs ask for it with the one date field (`DateInput`)
//      and refuse to submit over text that is not a date (`useDateProblems`).
//
// WHAT THIS DOES NOT DO
//     It reads source. It cannot see a request assembled somewhere this reader
//     does not look, and it cannot prove the server refuses a missing date,
//     which is the Python suite's job. The per-client GST tab
//     (app/clients/[id]/compliance/gst/page.tsx) already sent a date; it is held
//     by rule 3.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";

const WEB = join(import.meta.dirname, "..");
const MARKERS = new Set(["markGSTR1Filed", "markGSTR3BFiled"]);
const GST_DATA = "lib/data/gst.ts";
const API_CLIENT = "lib/api/index.ts";
const FIRM_PAGES = ["app/gst/gstr1/page.tsx", "app/gst/gstr3b/page.tsx"];
/** The position of the date among the mark-filed functions' parameters. */
const DATE_ARG = 3;

function parse(fileName: string, source: string): ts.SourceFile {
  return ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true,
    fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
}

function walkTree(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === ".next" || name === "out" || name.startsWith(".")) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === "scripts") continue;
      walkTree(p, out);
    } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) && !name.endsWith(".d.ts")) {
      out.push(p);
    }
  }
  return out;
}

function visit(node: ts.Node, fn: (n: ts.Node) => void): void {
  fn(node);
  node.forEachChild((c) => visit(c, fn));
}

function lineOf(sf: ts.SourceFile, node: ts.Node): number {
  return sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
}

/** A thing the code worked out, as opposed to a thing somebody typed. */
function isComputed(e: ts.Expression): boolean {
  let n: ts.Expression = e;
  while (ts.isParenthesizedExpression(n) || ts.isAsExpression(n) || ts.isNonNullExpression(n)) n = n.expression;
  // `undefined` is an identifier that is the ABSENCE of a date, not a person's.
  if (ts.isIdentifier(n)) return n.text === "undefined";
  if (ts.isPropertyAccessExpression(n)) return false;
  return true; // a literal, a call, `new Date()`, `a ?? b`, `a || b`, `c ? a : b`, a template…
}

const isString = (n: ts.Node, text: string): boolean =>
  (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && n.text === text;

function propertyNames(o: ts.ObjectLiteralExpression): Set<string> {
  const names = new Set<string>();
  for (const p of o.properties) {
    if ((ts.isPropertyAssignment(p) || ts.isShorthandPropertyAssignment(p)) && p.name
        && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name))) names.add(p.name.text);
  }
  return names;
}

function hasSpread(o: ts.ObjectLiteralExpression): boolean {
  return o.properties.some((p) => ts.isSpreadAssignment(p));
}

function sayingSubmitted(o: ts.ObjectLiteralExpression): boolean {
  return o.properties.some((p) => ts.isPropertyAssignment(p) && p.name
    && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) && p.name.text === "status"
    && isString(p.initializer, "submitted"));
}

/** Does this file talk to a GST status route (the typed client or the path)? */
function talksToAGstStatusRoute(source: string): boolean {
  return /setGstr1Status|setGstr3bStatus|gst-workspace\/gstr[13]/.test(source);
}

export interface Gap { line: number; why: string }

/** Rules 1 and 3: every way a submit can be asked for without a stated date. */
export function submitsWithoutAStatedDate(fileName: string, source: string): Gap[] {
  const sf = parse(fileName, source);
  const gaps: Gap[] = [];
  const inGstFile = talksToAGstStatusRoute(source);
  visit(sf, (n) => {
    if (ts.isCallExpression(n)) {
      const callee = n.expression;
      if (ts.isIdentifier(callee) && MARKERS.has(callee.text)) {
        const date = n.arguments[DATE_ARG];
        if (!date) {
          gaps.push({ line: lineOf(sf, n), why: `${callee.text}(…) is called without a date` });
        } else if (isComputed(date)) {
          gaps.push({ line: lineOf(sf, n),
            why: `${callee.text}(…) is handed a date that is a literal or a computation (${date.getText(sf)}); it must be what the person typed` });
        }
      }
      if (inGstFile && n.arguments.some((a) => isString(a, "submitted"))) {
        const options = n.arguments.filter(ts.isObjectLiteralExpression);
        if (!options.some((o) => propertyNames(o).has("filed_date"))) {
          gaps.push({ line: lineOf(sf, n), why: `a call hands "submitted" to a helper with no filed_date` });
        }
      }
    }
    if (inGstFile && ts.isObjectLiteralExpression(n) && sayingSubmitted(n)) {
      const names = propertyNames(n);
      if (!names.has("filed_date")) {
        gaps.push({ line: lineOf(sf, n),
          why: hasSpread(n)
            ? "an object says status: \"submitted\" with no filed_date of its own (a spread is not trusted to carry one)"
            : "an object says status: \"submitted\" with no filed_date" });
      }
    }
  });
  return gaps;
}

function functionNamed(sf: ts.SourceFile, name: string): ts.FunctionDeclaration | undefined {
  let found: ts.FunctionDeclaration | undefined;
  visit(sf, (n) => { if (ts.isFunctionDeclaration(n) && n.name?.text === name) found = n; });
  return found;
}

const CLOCK = /^(today|now|ist|utc)/i;

/** Rule 4. */
export function functionTakesAStatedDate(source: string, name: string): string[] {
  const sf = parse(GST_DATA, source);
  const fn = functionNamed(sf, name);
  if (!fn) return [`${name} is gone — has it been renamed?`];
  const problems: string[] = [];
  const p = fn.parameters[DATE_ARG];
  if (!p || !ts.isIdentifier(p.name) || p.name.text !== "filedDate") {
    problems.push(`${name}'s parameter ${DATE_ARG + 1} is not \`filedDate\``);
  } else {
    if (p.questionToken) problems.push(`${name}'s filedDate is optional`);
    if (p.initializer) problems.push(`${name}'s filedDate has a default`);
    if (!p.type || p.type.getText(sf) !== "string") problems.push(`${name}'s filedDate is not typed string`);
  }
  let sendsIt = false;
  visit(fn.body ?? fn, (n) => {
    if (ts.isNewExpression(n) && n.expression.getText(sf) === "Date") problems.push(`${name} builds a Date`);
    if (ts.isCallExpression(n)) {
      const callee = n.expression;
      const id = ts.isIdentifier(callee) ? callee.text
        : ts.isPropertyAccessExpression(callee) ? callee.name.text : "";
      if (CLOCK.test(id)) problems.push(`${name} calls ${id}() — the clock is not an argument`);
    }
    if (ts.isPropertyAssignment(n) && ts.isIdentifier(n.name) && n.name.text === "filed_date"
        && ts.isIdentifier(n.initializer) && n.initializer.text === "filedDate") sendsIt = true;
  });
  if (!sendsIt) problems.push(`${name} does not send \`filed_date: filedDate\``);
  return problems;
}

/** Rule 5. */
export function statusTypeRequiresTheDate(source: string): string[] {
  const sf = parse(API_CLIENT, source);
  let alias: ts.TypeAliasDeclaration | undefined;
  visit(sf, (n) => { if (ts.isTypeAliasDeclaration(n) && n.name.text === "GSTStatusUpdate") alias = n; });
  if (!alias) return ["GSTStatusUpdate is gone — has it been renamed?"];
  const problems: string[] = [];
  let submittedMembers = 0;
  visit(alias, (n) => {
    if (!ts.isTypeLiteralNode(n)) return;
    const status = n.members.find((m): m is ts.PropertySignature =>
      ts.isPropertySignature(m) && ts.isIdentifier(m.name) && m.name.text === "status");
    if (!status || !status.type) return;
    let saysSubmitted = false;
    visit(status.type, (t) => {
      if (ts.isLiteralTypeNode(t) && ts.isStringLiteral(t.literal) && t.literal.text === "submitted") saysSubmitted = true;
    });
    if (!saysSubmitted) return;
    submittedMembers++;
    const date = n.members.find((m): m is ts.PropertySignature =>
      ts.isPropertySignature(m) && ts.isIdentifier(m.name) && m.name.text === "filed_date");
    if (!date) problems.push("a status type that allows \"submitted\" has no filed_date");
    else if (date.questionToken) problems.push("a status type that allows \"submitted\" leaves filed_date optional");
  });
  if (submittedMembers === 0) problems.push("GSTStatusUpdate no longer has a member that allows \"submitted\"");
  return problems;
}

// ── the detector is held to its own rule before it is trusted ───────────────

test("the reader finds each way a submit can be sent without a stated date", () => {
  const gst = (body: string) => `import x from "y";\nconst a = "gst-workspace/gstr1";\n${body}`;
  const bad: Record<string, string> = {
    "no date argument": `markGSTR1Filed(c, p, arn);`,
    "date left to the gstin slot": `markGSTR3BFiled(c, p, arn, undefined);`,
    "today's date by function": `markGSTR1Filed(c, p, arn, todayLocalISO(), g);`,
    "a Date": `markGSTR1Filed(c, p, arn, new Date().toISOString().slice(0, 10), g);`,
    "a fallback": `markGSTR3BFiled(c, p, arn, filedDate ?? today, g);`,
    "an or-default": `markGSTR3BFiled(c, p, arn, filedDate || today, g);`,
    "a literal": `markGSTR1Filed(c, p, arn, "2026-07-11", g);`,
    "an object with no date": gst(`api.gstWorkspace.setGstr1Status(id, { status: "submitted", ca_approved: true, arn });`),
    "an object that only spreads": gst(`const b = { status: "submitted", ca_approved: true, ...extra };`),
    "a helper handed 'submitted' and no date": gst(`updateStatus(id, "submitted", { arn });`),
    "a helper handed 'submitted' and nothing": gst(`updateStatus(id, "submitted");`),
  };
  for (const [why, src] of Object.entries(bad)) {
    assert.ok(submitsWithoutAStatedDate("probe.tsx", src).length > 0, `not found: ${why}`);
  }
  const good: Record<string, string> = {
    "a typed date": `markGSTR1Filed(c, p, arn, filedDate, g);`,
    "a property read": `markGSTR3BFiled(c, p, arn, form.filedDate, g);`,
    "an object with a date": gst(`api.gstWorkspace.setGstr3bStatus(id, { status: "submitted", ca_approved: true, arn, filed_date: filedDate });`),
    "a shorthand date": gst(`const b = { status: "submitted", filed_date };`),
    "a helper with a date": gst(`updateStatus(id, "submitted", { arn, filed_date: filedDate });`),
    "an approval, which files nothing": gst(`api.gstWorkspace.setGstr1Status(id, { status: "ca_approved", ca_approved: true });`),
    "a comparison, not a call": gst(`if (r.status === "submitted") show();`),
  };
  for (const [why, src] of Object.entries(good)) {
    assert.deepEqual(submitsWithoutAStatedDate("probe.tsx", src), [], `flagged but fine: ${why}`);
  }
  // The object rule is about files that talk to a GST status route: an MCA
  // filing that is also "submitted" is not this defect.
  assert.deepEqual(
    submitsWithoutAStatedDate("mca.tsx", `const b = { status: "submitted" };`), []);
});

test("the function-contract reader finds a missing, optional, defaulted or clocked date", () => {
  const fn = (params: string, body: string) =>
    `export async function markGSTR1Filed(${params}): Promise<void> { ${body} }`;
  const sends = `const res = await api.setGstr1Status(id, { status: "submitted", filed_date: filedDate });`;
  const ok = fn("c: string, p: string, a: string, filedDate: string, g?: string", sends);
  assert.deepEqual(functionTakesAStatedDate(ok, "markGSTR1Filed"), []);
  assert.ok(functionTakesAStatedDate(fn("c: string, p: string, a: string, g?: string", sends), "markGSTR1Filed").length > 0, "no parameter");
  assert.ok(functionTakesAStatedDate(fn("c: string, p: string, a: string, filedDate?: string", sends), "markGSTR1Filed").length > 0, "optional");
  assert.ok(functionTakesAStatedDate(fn("c: string, p: string, a: string, filedDate: string = todayISO()", sends), "markGSTR1Filed").length > 0, "default");
  assert.ok(functionTakesAStatedDate(fn("c: string, p: string, a: string, filedDate: string", sends.replace("filedDate", "todayLocalISO()")), "markGSTR1Filed").length > 0, "clock");
  assert.ok(functionTakesAStatedDate(fn("c: string, p: string, a: string, filedDate: string", `const d = new Date(); ${sends}`), "markGSTR1Filed").length > 0, "Date");
  assert.ok(functionTakesAStatedDate(fn("c: string, p: string, a: string, filedDate: string", `await api.setGstr1Status(id, { status: "submitted" });`), "markGSTR1Filed").length > 0, "not sent");
  assert.ok(functionTakesAStatedDate("export const x = 1;", "markGSTR1Filed").length > 0, "gone");
});

test("the type reader finds a submitted member that leaves the date optional", () => {
  const good = `export type GSTStatusUpdate = { status: "draft"; filed_date?: string } | { status: "submitted"; filed_date: string };`;
  assert.deepEqual(statusTypeRequiresTheDate(good), []);
  assert.ok(statusTypeRequiresTheDate(`export type GSTStatusUpdate = { status: "draft" | "submitted"; filed_date?: string };`).length > 0, "optional");
  assert.ok(statusTypeRequiresTheDate(`export type GSTStatusUpdate = { status: "submitted" };`).length > 0, "absent");
  assert.ok(statusTypeRequiresTheDate(`export type GSTStatusUpdate = { status: "draft" };`).length > 0, "no submitted member at all");
});

// ── the rules, over the tree ────────────────────────────────────────────────

const FILES = walkTree(WEB).map((p) => ({ rel: relative(WEB, p), src: readFileSync(p, "utf8") }));

test("nothing in the app asks a GST status route to mark a return submitted without a date the person stated", () => {
  const offenders: string[] = [];
  let calls = 0;
  for (const f of FILES) {
    for (const g of submitsWithoutAStatedDate(f.rel, f.src)) offenders.push(`${f.rel}:${g.line} — ${g.why}`);
    if (f.rel !== GST_DATA) calls += (f.src.match(/\bmarkGSTR[13]B?Filed\(/g) ?? []).length;
  }
  assert.deepEqual(offenders, [],
    "a return is being marked filed without a stated date — the server would refuse it (or, before " +
    "PRE-A-007, stamp today), and the lock message would quote a date nobody typed");
  assert.ok(calls >= 2, `found only ${calls} call(s) of the mark-filed functions; the rule is looking at the wrong tree`);
});

test("the per-client GST tab is among the files the rule reads, and sends its date", () => {
  const tab = FILES.find((f) => f.rel.replace(/\\/g, "/") === "app/clients/[id]/compliance/gst/page.tsx");
  assert.ok(tab, "the per-client GST tab moved — update this guard, do not drop it");
  assert.ok(talksToAGstStatusRoute(tab.src), "the tab no longer talks to a GST status route");
  assert.match(tab.src, /updateStatus\(id,\s*"submitted",\s*\{[^}]*filed_date/);
});

for (const name of MARKERS) {
  test(`${name} takes the date as a required argument and sends it`, () => {
    const src = readFileSync(join(WEB, GST_DATA), "utf8");
    assert.deepEqual(functionTakesAStatedDate(src, name), []);
  });
}

test("the typed API client cannot be asked to submit without a date", () => {
  assert.deepEqual(statusTypeRequiresTheDate(readFileSync(join(WEB, API_CLIENT), "utf8")), []);
});

for (const page of FIRM_PAGES) {
  test(`${page}: the date is typed into the one date field, and unreadable text blocks the save`, () => {
    const src = readFileSync(join(WEB, page), "utf8");
    const sf = parse(page, src);

    // The identifier handed to the mark-filed call is React state that starts
    // EMPTY: the dialog is where the CA types it, and nothing offers one.
    const found: { handedOver?: string; initial?: ts.Expression } = {};
    visit(sf, (n) => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && MARKERS.has(n.expression.text)) {
        const a = n.arguments[DATE_ARG];
        if (a && ts.isIdentifier(a)) found.handedOver = a.text;
      }
    });
    assert.ok(found.handedOver, `${page} does not hand an identifier to a mark-filed function`);
    visit(sf, (n) => {
      if (ts.isVariableDeclaration(n) && ts.isArrayBindingPattern(n.name)
          && n.name.elements[0] && ts.isBindingElement(n.name.elements[0])
          && n.name.elements[0].name.getText(sf) === found.handedOver
          && n.initializer && ts.isCallExpression(n.initializer)
          && n.initializer.expression.getText(sf) === "useState") {
        found.initial = n.initializer.arguments[0];
      }
    });
    assert.ok(found.initial, `${found.handedOver} is not React state in ${page}`);
    assert.ok(ts.isStringLiteral(found.initial) && found.initial.text === "",
      `${found.handedOver} starts from ${found.initial.getText(sf)} — the CA types the date, ` +
      `so the state starts empty and no default is offered`);

    // The field is the shared date field, named, and it reports its state.
    assert.match(src, /<DateInput\b/);
    assert.match(src, /import \{ DateInput \} from "@\/components\/ui\/date-input"/);
    assert.match(src, /import \{ useDateProblems \} from "@\/lib\/dates\/useDateProblems"/);
    const field = /<DateInput\b[\s\S]*?\/>/.exec(src)?.[0] ?? "";
    assert.match(field, /\bid="([a-z0-9-]+)"/, "the date field has no id");
    const id = /\bid="([a-z0-9-]+)"/.exec(field)![1];
    assert.match(src, new RegExp(`htmlFor="${id}"`), "the date field has no label");
    assert.match(field, /onStateChange=\{dates\.watch\(/, "the field does not report an unreadable date");
    // ...and the confirm button is held while the box holds text that is not a date.
    assert.match(src, /disabled=\{!arn\.trim\(\) \|\| !!dates\.first\}/);
    assert.match(src, /if \(!clientId \|\| !yearMonth \|\| !arn\.trim\(\) \|\| dates\.first\) return;/);
  });
}
