// A deduction typed on the TDS screen is named on the statement built from the books, and the year is not called nil for a payee the server could not look up (POST-A-078). Run with:
//   node --experimental-strip-types --test scripts/a-typed-deduction-is-named-on-the-statement-and-the-year-is-not-called-nil-for-a-payee-with-no-pan.test.ts
//
// WHY THIS EXISTS
//     The 26Q built from the books reads posted purchase bills and withholding advances only, so a deduction typed on the TDS screen is not on it, and the screens said
//     nothing: a statement that is silent about the register's tax reads as a complete one. The server now names them (`excluded_typed`) and the two return screens draw
//     what it said. Separately, the typed form told the CA "the year's total for this payee has not reached it either" over a nil that meant "no PAN, so nothing was
//     looked up" (and, for a section with no yearly threshold, over a year that was never compared with anything).
//
//     The rules, held from the side that reads the screens:
//       * both return screens draw ONE component, `TypedDeductionsNote`, handed the server's answer whole; neither reads a count, a tax or a row itself;
//       * that component draws the server's sentence as it arrived, through the one reader, calls nothing but the reader, the two shared formatters and `.map`, and
//         does no arithmetic of any kind (an AST rule, not a list of spellings);
//       * the typed form says the year's total is below the section's yearly threshold ONLY when the server says it added the year up (`aggregate_tested === true`), a
//         server that sends no key does not count as saying so, and the form shows what a settled quote says and nothing of a quote that has just been typed over.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.join(import.meta.dirname, "..");
const TAB = "app/clients/[id]/compliance/tds/page.tsx";
const PAGE = "app/tds/returns/page.tsx";
const TYPED_FORM = "app/tds/page.tsx";
const NOTE = "components/tds/TypedDeductionsNote.tsx";
const READER = "lib/tds/excludedTyped.ts";
const DATA = "lib/data/tds.ts";

/** The file with comments blanked (block comments, whole-line comments, JSX comments and trailing ones that follow a space), so a sentence in a comment is not read as code. */
function code(rel: string): string {
  return strip(fs.readFileSync(path.join(WEB, rel), "utf8"));
}
function strip(src: string): string {
  return src
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/(\s)\/\/\s[^\n]*$/gm, "$1");
}

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
    const rel = path.posix.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(rel));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(rel);
  }
  return out;
}

// ── the rules, as functions of a source text, so the self-test can run them on a spoiled copy ──────────────────────

/** A screen draws the note once, hands it the whole answer, and reads nothing of it itself. */
function screenProblems(src: string, key: string): string[] {
  const problems: string[] = [];
  const draws = [...src.matchAll(/<TypedDeductionsNote\s+raw=\{([^}]*)\}\s*\/>/g)];
  if (draws.length !== 1) problems.push(`draws the note ${draws.length} times`);
  else if (draws[0][1].replace(/\s+/g, "") !== key) problems.push(`hands the note ${draws[0][1]} and not ${key}`);
  if (!/import \{ TypedDeductionsNote \} from "@\/components\/tds\/TypedDeductionsNote";/.test(src)) problems.push("does not import the shared note");
  const reads = [...src.matchAll(/excluded_typed/g)].length;
  if (reads !== 1) problems.push(`names excluded_typed ${reads} times (once, in the hand-over)`);
  if (/readExcludedTyped|ExcludedTyped\b/.test(src)) problems.push("reads the answer itself");
  return problems;
}

const ARITHMETIC = new Set<number>([
  ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken, ts.SyntaxKind.SlashToken, ts.SyntaxKind.PercentToken, ts.SyntaxKind.AsteriskAsteriskToken,
  ts.SyntaxKind.PlusEqualsToken, ts.SyntaxKind.MinusEqualsToken, ts.SyntaxKind.AsteriskEqualsToken, ts.SyntaxKind.SlashEqualsToken, ts.SyntaxKind.PercentEqualsToken,
  ts.SyntaxKind.AsteriskAsteriskEqualsToken,
]);
/** The only calls the note makes: the one reader, the two shared formatters and a list's `.map`. Anything else (parseInt, Number, BigInt, Math.*, .reduce, .toFixed…) is a figure being made here. */
const ALLOWED_CALLS = /^(readExcludedTyped|formatPaise|formatDate|typed\.rows\.map)$/;

/** Arithmetic and calls the note must not have, found in the syntax tree and not by spelling. */
function figureMakingIn(src: string): string[] {
  const file = ts.createSourceFile("note.tsx", src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isBinaryExpression(node) && ARITHMETIC.has(node.operatorToken.kind)) found.push(`arithmetic: ${node.getText(file)}`);
    if ((ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node))
      && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken, ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken].includes(node.operator)) found.push(`unary: ${node.getText(file)}`);
    if (ts.isCallExpression(node)) {
      const callee = node.expression.getText(file);
      if (!ALLOWED_CALLS.test(callee)) found.push(`call: ${callee}(…)`);
    }
    if (ts.isNewExpression(node)) found.push(`new: ${node.getText(file)}`);
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

/** The note draws the server's sentence, through the reader, says when the answer cannot be read, and makes no figure. */
function noteProblems(src: string): string[] {
  const problems: string[] = [...figureMakingIn(src)];
  const text = strip(src);
  if (!/const reading = readExcludedTyped\(raw\);/.test(text)) problems.push("does not read through the one reader");
  if (!/reading\.kind === "none" \|\| reading\.kind === "absent"\) return null;/.test(text)) problems.push("draws something for none or no key");
  if (!/reading\.kind === "unreadable"/.test(text) || !/could not be read from the server&apos;s answer/.test(text)) problems.push("says nothing when the answer is there and cannot be read");
  if (!/\{typed\.reason \? ` \$\{typed\.reason\}` : ""\}/.test(text)) problems.push("does not draw the server's sentence as it arrived");
  if (!/formatPaise\(typed\.tds_paise\)/.test(text)) problems.push("does not draw the tax through the shared money formatter");
  if (!/formatDate\(row\.transaction_date\)/.test(text)) problems.push("does not draw the date through the shared date module");
  if (!/\{typed\.rows && \(/.test(text)) problems.push("draws a list that is not whole");
  if (!/<details>/.test(text)) problems.push("does not fold the list away");
  if (!/role="region"/.test(text) || !/tabIndex=\{0\}/.test(text) || !/aria-label="Deductions typed on the TDS screen/.test(text)) problems.push("the list's scroll box cannot be reached from the keyboard or says nothing of what it holds");
  if (/dangerouslySetInnerHTML/.test(text)) problems.push("sets HTML");
  return problems;
}

/** The typed form says the year's total is below the threshold only on the server's word, and shows only a settled quote. */
function formProblems(src: string): string[] {
  const problems: string[] = [];
  if (/the year&apos;s total for this payee has not reached it either/.test(src)) problems.push("still says the year's total for this payee has not reached it");
  const claims = [...src.matchAll(/below the section's yearly threshold too/g)];
  if (claims.length !== 1) problems.push(`makes the claim ${claims.length} times`);
  else {
    const before = src.slice(Math.max(0, claims[0].index! - 260), claims[0].index!);
    if (!/aggregate_tested === true\s*\?\s*"[^"]*$/.test(before)) problems.push("makes the claim without the server saying it added the year up");
  }
  for (const m of src.matchAll(/aggregate_tested[^\n]*/g)) {
    if (!/aggregate_tested === true/.test(m[0])) problems.push(`reads aggregate_tested some other way: ${m[0].trim()}`);
  }
  if ((src.match(/const shown = quoting \? null : quote;/g) ?? []).length !== 1) problems.push("does not hold back a quote that is being replaced");
  const from = src.indexOf("const shown = quoting ? null : quote;");
  const to = src.indexOf("})()}", from);
  if (from >= 0 && to > from) {
    const block = src.slice(from + "const shown = quoting ? null : quote;".length, to).replace('{quoting ? "…" : quote ? formatPaise(quote.tds_paise) : "—"}', "");
    const stale = block.match(/\bquote\b[^\n]*/);
    if (stale) problems.push(`the block reads the unsettled quote: ${stale[0].trim()}`);
  } else problems.push("the quote block cannot be found");
  return problems;
}

test("both return screens draw the one shared note, handed the server's answer whole", () => {
  assert.deepEqual(screenProblems(code(PAGE), "result.excluded_typed"), []);
  assert.deepEqual(screenProblems(code(TAB), "computeResult.excluded_typed"), []);
});

test("the note draws the server's sentence through the one reader, says when it cannot read, and makes no figure", () => {
  assert.deepEqual(noteProblems(fs.readFileSync(path.join(WEB, NOTE), "utf8")), []);
});

test("the reader is pure: it imports nothing and draws nothing", () => {
  const src = code(READER);
  assert.equal([...src.matchAll(/^\s*import\b/gm)].length, 0, "the reader imports something");
  assert.ok(!/<[A-Za-z]/.test(src.replace(/Array<[^>]*>|Record<[^>]*>|\w+<[^>]*>/g, "")), "the reader draws markup");
  assert.deepEqual(figureMakingIn(fs.readFileSync(path.join(WEB, READER), "utf8")).filter((f) => f.startsWith("arithmetic") || f.startsWith("unary")), [], "the reader does arithmetic");
});

test("the payload type does not pretend to know the answers", () => {
  const src = code(DATA);
  assert.match(src, /excluded_typed\?: unknown;/);
  assert.match(src, /aggregate_tested\?: boolean;/);
  assert.ok(!/aggregate_read/.test(src), "the old field is still named");
});

test("the typed form says the year's total is below the threshold only when the server says it added the year up, and shows only a settled quote", () => {
  assert.deepEqual(formProblems(code(TYPED_FORM)), []);
});

test("the browser drive speaks the screen's own sentence for an answer it cannot read", () => {
  const drive = fs.readFileSync(path.join(WEB, "scripts/drive/scenarios/typedDeductionsNamed.mjs"), "utf8");
  const spoken = drive.match(/const UNREADABLE = "((?:[^"\\]|\\.)*)";/);
  assert.ok(spoken, "the drive no longer names the sentence as a constant");
  const drawn = fs.readFileSync(path.join(WEB, NOTE), "utf8").match(/<p className="text-xs text-state-attention[^>]*>\s*([\s\S]*?)\s*<\/p>/);
  assert.ok(drawn, "the note's unreadable paragraph cannot be found");
  assert.equal(spoken[1], drawn[1].replace(/&apos;/g, "'").replace(/\s+/g, " ").trim());
});

test("nothing else in the app reads the fields", () => {
  const files = sourceFiles(".");
  const holding = (word: RegExp) => files.filter((f) => word.test(code(f))).sort();
  assert.deepEqual(holding(/\bexcluded_typed\b/), [DATA, PAGE, TAB].sort());
  assert.deepEqual(holding(/\baggregate_tested\b/), [DATA, TYPED_FORM].sort());
});

// ── the rules can fail ───────────────────────────────────────────────────────────────────────────────────────

test("self-test: the rules fail on a spoiled copy of each file", () => {
  const page = code(PAGE);
  const tab = code(TAB);
  const note = fs.readFileSync(path.join(WEB, NOTE), "utf8");
  const form = code(TYPED_FORM);
  const spoil = (src: string, from: string, to: string) => {
    assert.ok(src.includes(from), `the self-test's anchor is gone: ${from}`);
    return src.replace(from, to);
  };

  assert.ok(screenProblems(spoil(page, "<TypedDeductionsNote raw={result.excluded_typed} />", ""), "result.excluded_typed").length, "a screen that stopped drawing the note");
  assert.ok(screenProblems(spoil(page, "<TypedDeductionsNote raw={result.excluded_typed} />", "<TypedDeductionsNote raw={result.excluded_typed?.count} />"), "result.excluded_typed").length, "a screen that hands over a piece");
  assert.ok(screenProblems(page + "\nconst n = result.excluded_typed.count;", "result.excluded_typed").length, "a screen that reads the count itself");
  assert.ok(screenProblems(tab.replace(/import \{ TypedDeductionsNote \}[^\n]*\n/, ""), "computeResult.excluded_typed").length, "a screen that does not import the note");
  assert.ok(screenProblems(tab + "\nreadExcludedTyped(x);", "computeResult.excluded_typed").length, "a screen that reads the answer through the reader");

  assert.ok(noteProblems(spoil(note, "{typed.reason ? ` ${typed.reason}` : \"\"}", "")).length, "a note that stopped drawing the server's sentence");
  assert.ok(noteProblems(spoil(note, "if (reading.kind === \"none\" || reading.kind === \"absent\") return null;", "")).length, "a note that draws for none");
  assert.ok(noteProblems(spoil(note, "if (reading.kind === \"unreadable\") {", "if (false) {")).length, "a note that says nothing for an answer it cannot read");
  assert.ok(noteProblems(spoil(note, "formatPaise(typed.tds_paise)", "(typed.tds_paise / 100).toFixed(2)")).length, "a note that formats the tax itself");
  assert.ok(noteProblems(spoil(note, "{typed.rows && (", "{(typed.rows ?? []) && (")).length, "a note that draws a list that is not whole");
  assert.ok(noteProblems(spoil(note, "<details>", "<div>")).length, "a note that stops folding the list away");
  assert.ok(noteProblems(spoil(note, "tabIndex={0}", "")).length, "a scroll box nobody can reach from the keyboard");
  assert.ok(noteProblems(spoil(note, "const reading = readExcludedTyped(raw);", "const reading = raw as never;")).length, "a note that does not read through the reader");
  // every way of making a figure in the note, found in the tree and not by spelling
  for (const [what, line] of [
    ["a sum with +", "const total = typed.count + typed.tds_paise;"], ["a difference with -", "const left = typed.tds_paise - typed.count;"],
    ["a division", "const rupees = typed.tds_paise / 100;"], ["a product", "const paise = typed.count * 100;"], ["a remainder", "const r = typed.tds_paise % 100;"],
    ["parseInt", "const n = parseInt(String(typed.count), 10);"], ["Number()", "const n = Number(typed.count);"], ["BigInt", "const n = BigInt(1);"],
    ["Math.round", "const n = Math.round(typed.count);"], ["a reduce", "const t = (typed.rows ?? []).reduce((a, r) => r.tds_paise, 0);"],
    ["toFixed", "const t = typed.count.toFixed(2);"], ["an increment", "let i = 0; i++;"], ["a compound assignment", "let t = 0; t += typed.count;"],
  ] as const) {
    assert.ok(figureMakingIn(spoil(note, "const one = typed.count === 1;", `const one = typed.count === 1; ${line}`)).length, `not caught: ${what}`);
  }
  assert.deepEqual(figureMakingIn(note), [], "the real note makes a figure");

  assert.ok(formProblems(spoil(form, "shown.explain.aggregate_tested === true", "shown.explain.aggregate_tested !== false")).length, "a form that says it when the key is absent");
  assert.ok(formProblems(spoil(form, "shown.explain.aggregate_tested === true", "true")).length, "a form that always says it");
  assert.ok(formProblems(spoil(form, "Nothing is deducted — this payment is below", "the year&apos;s total for this payee has not reached it either. Nothing is deducted — this payment is below")).length, "a form that kept the old sentence");
  assert.ok(formProblems(spoil(form, "const shown = quoting ? null : quote;", "const shown = quote;")).length, "a form that shows a quote that has just been typed over");
  assert.ok(formProblems(spoil(form, "{shown?.explain.rate_basis && (", "{quote?.explain.rate_basis && (")).length, "a form that reads the unsettled quote in one place");
});
