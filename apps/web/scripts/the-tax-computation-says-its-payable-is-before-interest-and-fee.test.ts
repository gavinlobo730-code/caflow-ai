// THE TAX COMPUTATION'S PAYABLE FIGURE SAYS IT IS BEFORE INTEREST AND FEE.
//   node --experimental-strip-types --test scripts/the-tax-computation-says-its-payable-is-before-interest-and-fee.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT (PRE-A-009, IT-13)
// ─────────────────────────────────────────────────────────────────────────────
// `app/clients/[id]/tax/computation/page.tsx` showed the engine's
// `payable.net_payable_paise` under a bare "Net Payable" (and, in the latest-
// computation card and the version list, a bare "Payable"). The engine sets it
// to `total_tax_paise - tds_and_advance_paise` (domain/income_tax/itr_engine.py,
// both branches): the tax less TDS and advance tax already paid, and NOTHING
// else. It carries no §234A/B/C interest and no §234F fee, which are worked on
// the separate Advance Tax screen, so a CA reading "Net Payable" as what the
// client pays with the return is short by exactly those. The probe pass's
// blocker on IT-13 was these two figures not adding up; the endpoint
// (`section_140a_tax_due_paise` on POST /interest/234ab), the 234ab screen and
// migration 407 landed and the label did not.
//
// NO FIGURE MOVES. This changes what the number is CALLED and where a reader is
// sent for the rest.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE (not a spelling of the old label)
// ─────────────────────────────────────────────────────────────────────────────
//   1. Wherever the screen chooses a label by `is_refund` (the three places the
//      figure is shown), the payable branch says it is before interest AND fee
//      and the refund branch says it is before interest. A branch may be a
//      literal or a constant; constants are resolved.
//   2. No string or JSX text on the screen is a bare "Net Payable" or "Payable".
//   3. Any text that says "net payable" also says "before interest".
//   4. The screen points at the Advance Tax screen (/income-tax/advance-tax,
//      carrying the client) where the interest and the §140A challan are.
// The detectors are exercised on the label that shipped, below.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PAGE = "app/clients/[id]/tax/computation/page.tsx";

function parse(src: string): ts.SourceFile {
  return ts.createSourceFile("page.tsx", src, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
}

function walk(node: ts.Node, visit: (n: ts.Node) => void): void {
  visit(node);
  ts.forEachChild(node, (c) => walk(c, visit));
}

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

type Audit = {
  /** `is_refund ? A : B` sites found (a floor against reading nothing) */
  sites: number;
  /** sites whose branches do not carry the qualifier, with the text read */
  unqualified: string[];
  /** strings or JSX text that are exactly "Net Payable" or "Payable" */
  bareLabels: string[];
  /** strings that say "net payable" without "before interest" */
  netPayableWithoutQualifier: string[];
  /** hrefs to the Advance Tax screen that carry the client */
  advanceTaxLinks: number;
};

function audit(src: string): Audit {
  const sf = parse(src);
  const consts = new Map<string, string>();
  walk(sf, (n) => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name)) {
      const v = stringValue(n.initializer);
      if (v !== null) consts.set(n.name.text, v);
    }
  });
  const resolve = (e: ts.Expression): string | null =>
    ts.isIdentifier(e) ? (consts.get(e.text) ?? null) : stringValue(e);

  let sites = 0;
  const unqualified: string[] = [];
  walk(sf, (n) => {
    if (ts.isConditionalExpression(n) && /is_refund/.test(n.condition.getText(sf))) {
      const a = resolve(n.whenTrue);
      const b = resolve(n.whenFalse);
      // Only a choice between LABELS for the figure counts. A class name
      // (`is_refund ? "text-green-600" : ...`) or a sign (`"+"`) is not one.
      const labelish = (s: string | null) => s !== null && /refund|payable/i.test(s);
      if (!labelish(a) && !labelish(b)) return;
      sites++;
      const line = sf.getLineAndCharacterOfPosition(n.getStart()).line + 1;
      if (!(a !== null && /before interest/i.test(a))) {
        unqualified.push(`line ${line}: refund label ${JSON.stringify(a)}`);
      }
      if (!(b !== null && /before interest and fee/i.test(b))) {
        unqualified.push(`line ${line}: payable label ${JSON.stringify(b)}`);
      }
    }
  });

  const texts: string[] = [];
  walk(sf, (n) => {
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)
        || ts.isTemplateHead(n) || ts.isTemplateMiddle(n) || ts.isTemplateTail(n)
        || ts.isJsxText(n)) {
      texts.push(n.text);
    }
  });
  const bareLabels = texts.filter((t) => /^\s*(net\s+)?payable\s*$/i.test(t)).map((t) => t.trim());
  const netPayableWithoutQualifier = texts
    .filter((t) => /net\s+payable/i.test(t) && !/before interest/i.test(t))
    .map((t) => t.trim());

  let advanceTaxLinks = 0;
  walk(sf, (n) => {
    if (ts.isJsxAttribute(n) && n.name.getText(sf) === "href" && n.initializer) {
      const text = n.initializer.getText(sf);
      if (/\/income-tax\/advance-tax/.test(text) && /client_id=/.test(text)) advanceTaxLinks++;
    }
  });
  return { sites, unqualified, bareLabels, netPayableWithoutQualifier, advanceTaxLinks };
}

const page = audit(fs.readFileSync(path.join(WEB, PAGE), "utf8"));

test("the screen is read: the places that label the payable figure are found", () => {
  assert.ok(page.sites >= 3,
    `expected the three places the payable figure is labelled (result, latest card, version list); found ${page.sites}`);
});

test("every label chosen by is_refund says the figure is before interest (and fee, when payable)", () => {
  assert.deepEqual(page.unqualified, []);
});

test("no label on the screen is a bare Net Payable or Payable", () => {
  assert.deepEqual(page.bareLabels, []);
});

test("any text that says net payable also says before interest", () => {
  assert.deepEqual(page.netPayableWithoutQualifier, []);
});

test("the screen points at the Advance Tax screen, carrying the client", () => {
  assert.ok(page.advanceTaxLinks >= 1,
    "link to /income-tax/advance-tax?client_id=... where the interest and the §140A challan are");
});

// ── The detectors, on the label that shipped (the negative control, kept) ───
const SHIPPED = `
export default function P({ computeResult, latestSnap, s }: any) {
  return (
    <div>
      <p>{computeResult.payable?.is_refund ? "Refund" : "Net Payable"}</p>
      <p>{latestSnap.is_refund ? "Refund" : "Payable"}</p>
      <p>{s.is_refund ? "Refund" : "Payable"}</p>
    </div>
  );
}`;

test("the detectors catch the label that shipped", () => {
  const a = audit(SHIPPED);
  assert.equal(a.sites, 3);
  assert.equal(a.unqualified.length, 6, "all six branches lack the qualifier");
  assert.ok(a.bareLabels.includes("Net Payable") && a.bareLabels.includes("Payable"));
  assert.equal(a.netPayableWithoutQualifier.length, 1);
  assert.equal(a.advanceTaxLinks, 0);
});

test("the detectors accept labels held as constants, and a link carrying the client", () => {
  const a = audit(`
const PAYABLE = "Net payable, before interest and fee";
const REFUND = "Refund, before interest";
export default function P({ computeResult, clientId }: any) {
  return (
    <div>
      <p>{computeResult.payable?.is_refund ? REFUND : PAYABLE}</p>
      <a href={\`/income-tax/advance-tax?client_id=\${clientId}\`}>Advance Tax screen</a>
    </div>
  );
}`);
  assert.equal(a.sites, 1);
  assert.deepEqual(a.unqualified, []);
  assert.deepEqual(a.bareLabels, []);
  assert.deepEqual(a.netPayableWithoutQualifier, []);
  assert.equal(a.advanceTaxLinks, 1);
});
