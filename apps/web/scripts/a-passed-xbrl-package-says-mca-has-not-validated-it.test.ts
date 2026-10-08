// A PACKAGE THAT PASSED OUR CHECK IS NEVER SHOWN AS VALIDATED, WITHOUT SAYING MCA HAS NOT.
//   node --experimental-strip-types --test scripts/a-passed-xbrl-package-says-mca-has-not-validated-it.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT (PRE-A-014)
// ─────────────────────────────────────────────────────────────────────────────
// `app/clients/[id]/year-end/xbrl/page.tsx` showed "Package validated — ready
// for review" and a status badge reading plain "validated". The check that sets
// that status is PracticeSync's OWN (`xbrl_service.validate_xbrl_package`:
// mandatory tags present, values numeric, assets equal equity and liabilities).
// MCA's pre-scrutiny is a different step, a server-side MCA rule set exposed
// only through MCA's desktop XBRL Validation Tool
// (docs/compliance/04-mca-epfo-esic.md section 1, XBRL), and this product runs
// neither it nor the tool. A CA reading a bare "validated" next to an MCA
// filing can take it to mean the MCA validator passed, and file on it.
//
// THE STORED VALUE IS NOT THE PROBLEM AND IS NOT CHANGED. The status string
// `validated` gates XBRL generation on the server; what is held here is what a
// PERSON reads.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE (not a spelling of the old copy)
// ─────────────────────────────────────────────────────────────────────────────
//   1. Every line of prose on the screen that says validate/validated/validation
//      names whose check it is ("PracticeSync").
//   2. The stored status is never rendered raw: the badge goes through
//      STATUS_LABEL, and every label for a validation status names PracticeSync.
//   3. Wherever the screen shows the passed state (a branch guarded on
//      status === "validated"), it also renders the one sentence that says it is
//      PracticeSync's own check and that MCA's XBRL Validation Tool and
//      pre-scrutiny have not been run.
// The detectors are exercised on the copy that shipped, below, so the rule
// cannot pass on a screen that states the old claim.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PAGE = "app/clients/[id]/year-end/xbrl/page.tsx";

function parse(src: string): ts.SourceFile {
  return ts.createSourceFile("page.tsx", src, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
}

function walk(node: ts.Node, visit: (n: ts.Node) => void): void {
  visit(node);
  ts.forEachChild(node, (c) => walk(c, visit));
}

/** The text of a string-ish expression, folding `"a" + "b"`, or null. */
function stringValue(node: ts.Node | undefined): string | null {
  if (!node) return null;
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  if (ts.isParenthesizedExpression(node)) return stringValue(node.expression);
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const l = stringValue(node.left);
    const r = stringValue(node.right);
    return l !== null && r !== null ? l + r : null;
  }
  return null;
}

/** Prose a person reads: a string, template piece or JSX text with a space in
 *  it. A stored token (`"validated"`, `"/validate"`, a class name) has none. */
function prose(sf: ts.SourceFile): { text: string; line: number }[] {
  const out: { text: string; line: number }[] = [];
  const add = (n: ts.Node, text: string) => {
    if (/\s/.test(text.trim())) {
      out.push({ text, line: sf.getLineAndCharacterOfPosition(n.getStart()).line + 1 });
    }
  };
  // A sentence written as `"a " + "b"` is ONE sentence: judge the folded text,
  // not each fragment, or a hedge in the second half reads as missing from the
  // first.
  const folded = new Set<ts.Node>();
  walk(sf, (n) => {
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.PlusToken
        && stringValue(n) !== null) {
      const inside = ts.isBinaryExpression(n.parent)
        && n.parent.operatorToken.kind === ts.SyntaxKind.PlusToken && stringValue(n.parent) !== null;
      if (!inside) {
        add(n, stringValue(n) as string);
        walk(n, (m) => { if (m !== n) folded.add(m); });
      }
    }
  });
  walk(sf, (n) => {
    if (folded.has(n)) return;
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) add(n, n.text);
    else if (ts.isTemplateHead(n) || ts.isTemplateMiddle(n) || ts.isTemplateTail(n)) add(n, n.text);
    else if (ts.isJsxText(n)) add(n, n.text);
  });
  return out;
}

function declaredStrings(sf: ts.SourceFile): Map<string, string> {
  const out = new Map<string, string>();
  walk(sf, (n) => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name)) {
      const v = stringValue(n.initializer);
      if (v !== null) out.set(n.name.text, v);
    }
  });
  return out;
}

function objectLabels(sf: ts.SourceFile, name: string): Map<string, string> | null {
  let found: Map<string, string> | null = null;
  walk(sf, (n) => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === name
        && n.initializer && ts.isObjectLiteralExpression(n.initializer)) {
      found = new Map();
      for (const p of n.initializer.properties) {
        if (ts.isPropertyAssignment(p)) {
          const key = ts.isIdentifier(p.name) || ts.isStringLiteral(p.name) ? p.name.text : null;
          const val = stringValue(p.initializer);
          if (key !== null && val !== null) found.set(key, val);
        }
      }
    }
  });
  return found;
}

type Audit = {
  /** prose that says validat* and does not name PracticeSync */
  unattributed: string[];
  /** a `{x.status ...}` rendered to the person without STATUS_LABEL */
  rawStatus: string[];
  /** STATUS_LABEL entries for a validation status that do not name PracticeSync */
  unlabelledStatuses: string[];
  /** `&& ` branches guarded on "validated" that do not render the sentence */
  gatedWithoutSentence: string[];
  /** how many branches guarded on "validated" exist (a floor against reading nothing) */
  gatedSites: number;
  /** the sentence's constant, found by what it says */
  sentenceName: string | null;
  sentence: string | null;
};

function audit(src: string): Audit {
  const sf = parse(src);
  const unattributed = prose(sf)
    .filter((p) => /validat/i.test(p.text) && !/PracticeSync/.test(p.text))
    .map((p) => `line ${p.line}: ${JSON.stringify(p.text.trim())}`);

  const strings = declaredStrings(sf);
  const hits = [...strings].filter(([, v]) => /pre-scrutiny/i.test(v));
  const sentenceName = hits.length === 1 ? hits[0][0] : null;
  const sentence = hits.length === 1 ? hits[0][1] : null;

  const rawStatus: string[] = [];
  walk(sf, (n) => {
    if (ts.isJsxExpression(n) && n.expression
        && (ts.isJsxElement(n.parent) || ts.isJsxFragment(n.parent))) {
      const e = n.expression;
      const isBranch = ts.isBinaryExpression(e)
        && e.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken;
      const text = e.getText(sf);
      if (!isBranch && /\.status\b/.test(text) && !/STATUS_LABEL/.test(text)) {
        rawStatus.push(`line ${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}: {${text}}`);
      }
    }
  });

  const labels = objectLabels(sf, "STATUS_LABEL");
  const unlabelledStatuses: string[] = [];
  if (!labels) unlabelledStatuses.push("STATUS_LABEL is not declared");
  else {
    for (const key of ["validated", "validation_pending", "validation_failed"]) {
      const v = labels.get(key);
      if (!v || !/PracticeSync/.test(v)) unlabelledStatuses.push(`${key}: ${JSON.stringify(v ?? null)}`);
    }
  }

  const gatedWithoutSentence: string[] = [];
  let gatedSites = 0;
  walk(sf, (n) => {
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
      // `A && B && <jsx>` parses as `(A && B) && <jsx>`: judge the whole chain
      // once, from its outermost `&&`, never its inner link.
      if (ts.isBinaryExpression(n.parent)
          && n.parent.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
          && n.parent.left === n) return;
      let mentionsValidated = false;
      walk(n.left, (m) => { if (ts.isStringLiteral(m) && m.text === "validated") mentionsValidated = true; });
      if (!mentionsValidated) return;
      gatedSites++;
      let rendersSentence = false;
      walk(n.right, (m) => {
        if (sentenceName && ts.isIdentifier(m) && m.text === sentenceName) rendersSentence = true;
      });
      if (!rendersSentence) {
        gatedWithoutSentence.push(`line ${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`);
      }
    }
  });
  return { unattributed, rawStatus, unlabelledStatuses, gatedWithoutSentence, gatedSites, sentenceName, sentence };
}

const page = audit(fs.readFileSync(path.join(WEB, PAGE), "utf8"));

test("the screen is read: its sentence, its labels and its passed-state branch are found", () => {
  assert.ok(page.sentenceName, "no constant says what pre-scrutiny is; the sentence is missing or was split");
  assert.ok(page.gatedSites >= 1, "no branch guarded on status === \"validated\" was found; the scan read nothing");
});

test("the one sentence says whose check it is and what has not been run", () => {
  const s = page.sentence ?? "";
  assert.match(s, /PracticeSync's own/, "must say the check is PracticeSync's own");
  assert.match(s, /MCA's XBRL Validation Tool/, "must name MCA's tool");
  assert.match(s, /pre-scrutiny/i, "must name pre-scrutiny");
  assert.match(s, /have not been run|has not been run/, "must say they have not been run");
});

test("every line of prose that says validated or validation names PracticeSync's check", () => {
  assert.deepEqual(page.unattributed, [],
    "say whose check it is: 'Passed PracticeSync's completeness check', not 'validated'");
});

test("the stored status is never shown raw, and every validation label names PracticeSync", () => {
  assert.deepEqual(page.rawStatus, [], "render the status through STATUS_LABEL");
  assert.deepEqual(page.unlabelledStatuses, []);
});

test("the passed state always renders the not-validated-by-MCA sentence", () => {
  assert.deepEqual(page.gatedWithoutSentence, [],
    "a branch guarded on status === \"validated\" must render the sentence constant");
});

// ── The detectors, on the copy that shipped (the negative control, kept) ─────
const SHIPPED = `
const STATUS_COLOR: Record<string, string> = { validated: "bg-x" };
export default function P({ pkg, selected }: any) {
  return (
    <div>
      <span>{pkg.status.replace(/_/g, " ")}</span>
      <p>Validation Errors</p>
      {selected.status === "validated" && selected.validation_errors.length === 0 && (
        <div><p>Package validated — ready for review</p></div>
      )}
      <button>Run Validation</button>
    </div>
  );
}
`;

test("the detectors catch the copy that shipped", () => {
  const a = audit(SHIPPED);
  assert.ok(a.unattributed.length >= 3, `bare 'validated' prose not caught: ${a.unattributed}`);
  assert.equal(a.rawStatus.length, 1, "the raw status badge was not caught");
  assert.ok(a.unlabelledStatuses.length >= 1, "a missing STATUS_LABEL was not caught");
  assert.equal(a.gatedSites, 1);
  assert.equal(a.gatedWithoutSentence.length, 1, "the unqualified passed branch was not caught");
});

test("the detectors accept a screen that attributes the check and says what is not run", () => {
  const good = audit(`
const STATUS_LABEL: Record<string, string> = {
  validated: "Passed PracticeSync check",
  validation_pending: "PracticeSync check pending",
  validation_failed: "PracticeSync check failed",
};
const ONLY = "This is PracticeSync's own check. MCA's XBRL Validation Tool and pre-scrutiny have not been run.";
export default function P({ pkg, selected }: any) {
  return (
    <div>
      <span>{STATUS_LABEL[pkg.status] ?? pkg.status.replace(/_/g, " ")}</span>
      {selected.status === "validated" && (<p>{ONLY}</p>)}
    </div>
  );
}`);
  assert.deepEqual(good.unattributed, []);
  assert.deepEqual(good.rawStatus, []);
  assert.deepEqual(good.unlabelledStatuses, []);
  assert.deepEqual(good.gatedWithoutSentence, []);
  assert.equal(good.gatedSites, 1);
});
