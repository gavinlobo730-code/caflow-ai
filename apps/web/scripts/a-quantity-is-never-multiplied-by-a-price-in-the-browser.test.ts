/**
 * A line's value is made by the ONE mirror of the server's rule, never by a product written on a screen (POST-A-134).
 *
 * THE DEFECT
 *
 *   The server values a line as `int(Decimal(str(quantity)) * rate_paise)`: exact decimal multiplication, then
 *   truncation (`domain/sales/line_tax`). The browser mirrors that in `lib/money/gstLine.taxablePaise`, pinned to the
 *   server by `shared/gst-parity-vectors.json`. Four places multiplied a quantity by a price themselves, in binary
 *   floating point, and rounded:
 *
 *     the recurring invoice template  list base and editor total   `Math.round(rate * quantity)`
 *     the recurring bill template     base                          `Math.round(rate_paise * quantity)`
 *     the inventory write-down modal  preview                       `Math.round((average cost - NRV) * quantity)`
 *
 *   The first two showed a base a few paise away from the invoice or bill the template went on to raise (0.335 units at
 *   Rs 1 is 33 paise on the server and showed 34). The third was a different formula from the posting's altogether (it
 *   used the rounded average cost, where the server compares the exact carrying value), so it could say nothing would
 *   post where something did. The first two now call the mirror (`lib/recurring/templateBase`); the third asks the
 *   server (`POST /api/inventory/items/{id}/writedown-preview`).
 *
 * THE RULE, NOT THE FOUR SPELLINGS
 *
 *   Outside `lib/money/` (the pinned mirrors), no source file multiplies anything named like a quantity. A fifth
 *   screen that wrote `price * qty` would otherwise be the same defect again, in a spelling no list of four names.
 *   The scan strips comments and string literals first, so prose about a product is not mistaken for one.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const WEB = join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", ".git", "scripts"]);
const ROOTS = ["app", "components", "lib"];
/** The pinned mirrors: the one place a quantity is allowed to meet a price, because the vectors hold them to the server. */
const MIRRORS = "lib/money/";

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

/** Comments and string literals removed, line structure kept, so a hit can be reported with its line number. */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, "").replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`/g, '""'))
    .join("\n");
}

const NAMED_LIKE_A_QUANTITY = String.raw`[A-Za-z_$][\w$]*(?:quantity|qty|Qty|Quantity)[\w$]*`;
/** A `*` whose right operand names a quantity (`x * l.quantity`, `x * (l.quantity || 0)`), or whose left operand does. */
const AFTER = new RegExp(String.raw`(?<![*/\w])\*(?!\*)\s*\(?\s*(?:[\w$]+\.)*${NAMED_LIKE_A_QUANTITY}|(?<![*/\w])\*(?!\*)\s*\(?\s*(?:[\w$]+\.)*(?:quantity|qty)\b`);
const BEFORE = new RegExp(String.raw`(?:\b(?:quantity|qty)\b|${NAMED_LIKE_A_QUANTITY})\s*(?:\|\|\s*0\s*)?\)?\s*(?<![*/])\*(?![*/=])`);

/** The lines of `src` that multiply a quantity-named operand. */
function productsOfAQuantity(src: string): number[] {
  const hits: number[] = [];
  code(src).split("\n").forEach((line, i) => {
    if (AFTER.test(line) || BEFORE.test(line)) hits.push(i + 1);
  });
  return hits;
}

test("no screen or library outside the pinned mirrors multiplies a quantity", () => {
  const offenders: string[] = [];
  let scanned = 0;
  for (const root of ROOTS) {
    for (const f of walk(join(WEB, root))) {
      const rel = relative(WEB, f).replace(/\\/g, "/");
      if (rel.startsWith(MIRRORS)) continue;
      scanned++;
      for (const line of productsOfAQuantity(readFileSync(f, "utf8"))) offenders.push(`${rel}:${line}`);
    }
  }
  assert.ok(scanned > 500, `only ${scanned} files were scanned: the walk has stopped seeing the tree`);
  assert.deepEqual(
    offenders,
    [],
    "a quantity is multiplied by hand: value the line with `taxablePaise` (lib/money/gstLine), or ask the server, " +
      "which values it by exact decimal multiplication and truncation:\n  " + offenders.join("\n  "),
  );
});

test("the scan finds the forms that were in the code, and not their neighbours (negative controls)", () => {
  const flagged = [
    "const t = lines.reduce((s, l) => s + Math.round((l.rate_paise || 0) * (l.quantity || 0)), 0);",
    "const x = Math.round(l.rate * l.quantity);",
    "const w = Math.round((avgCostPaise - nrvPaise) * qty);",
    "const y = price * qty;",
    "const z = quantity * ratePaise;",
    "const v = (l.quantity || 0) * l.rate_paise;",
    "total += item.unitPaise * item.stockQty;",
  ];
  for (const s of flagged) assert.deepEqual(productsOfAQuantity(s), [1], s);

  const allowed = [
    "const q = parseQuantity(l.quantity || \"\");",                       // a quantity read, not multiplied
    "rate: String((l.rate_paise ?? 0) / 100),",                            // a unit conversion
    "const n = taxablePaise(l.quantity, l.rate);",                         // the mirror
    "// the old form was Math.round(rate * quantity)",                     // prose
    "const msg = \"rate * quantity is not how a line is valued\";",       // a string
    "/* (l.rate_paise || 0) * (l.quantity || 0) */ const ok = 1;",        // a block comment
    "const area = width * height;",                                        // an unrelated product
    "const p = 2 ** quantityBits;",                                        // an exponent, not a product
  ];
  for (const s of allowed) assert.deepEqual(productsOfAQuantity(s), [], s);
});

test("the write-down preview is the server's, and the modal computes nothing", () => {
  const src = code(readFileSync(join(WEB, "app/clients/[id]/inventory/page.tsx"), "utf8"));
  assert.ok(/api\.inventory\.writedownPreview\(/.test(src), "the modal no longer asks the server for the write-down");
  assert.ok(!/avgCostPaise/.test(src), "the modal is working from the rounded average cost again");
  assert.ok(!/previewWritedownPaise/.test(src), "the modal has a figure of its own again");
});

test("the recurring template totals are made by the one helper, which values a line with the mirror", () => {
  for (const rel of ["app/clients/[id]/sales/page.tsx", "components/purchases/RecurringBills.tsx"]) {
    const src = code(readFileSync(join(WEB, rel), "utf8"));
    assert.ok(/templateBasePaise\(/.test(src), `${rel} no longer totals its template through lib/recurring/templateBase`);
  }
  const helper = code(readFileSync(join(WEB, "lib/recurring/templateBase.ts"), "utf8"));
  assert.ok(/taxablePaise\(/.test(helper), "the helper no longer values a line with taxablePaise");
  assert.ok(!/Math\.round/.test(helper), "the helper rounds where the server truncates");
});
