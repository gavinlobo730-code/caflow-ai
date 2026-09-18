// One rupee formatter, and the three things the old one got wrong.
//   node --experimental-strip-types --test lib/money/format.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { formatPaise, formatWhole, formatPaiseBare, carriesPaise, toPaise, NO_FIGURE } from "./format.ts";

test("Indian grouping, not Western (D6)", () => {
  assert.equal(formatPaise(12345678), "₹1,23,456.78");
  assert.equal(formatPaise(100000000000), "₹1,00,00,00,000.00");
  // The failure this guards: en-US would render ₹123,456.78, and 139 of the
  // 248 formatters measured on 18 Sep 2026 had no locale at all.
  assert.ok(!formatPaise(12345678).includes("123,456"));
});

test("two decimals always, so a column of figures lines up (D5)", () => {
  assert.equal(formatPaise(100), "₹1.00");
  assert.equal(formatPaise(0), "₹0.00");
  assert.equal(formatPaise(50), "₹0.50");
  assert.equal(formatPaise(1), "₹0.01");
});

test("nothing is not zero", () => {
  // The old shared formatter rendered null as ₹0.00 — a figure nobody holds
  // shown as one somebody computed — and undefined as the literal "₹NaN".
  assert.equal(formatPaise(null), NO_FIGURE);
  assert.equal(formatPaise(undefined), NO_FIGURE);
  assert.equal(formatPaise(0), "₹0.00", "a real zero is still a figure");
});

test("a bigint arrives as a string, and a rendering does not", () => {
  assert.equal(formatPaise("118000"), "₹1,180.00", "PostgREST bigint");
  assert.equal(formatPaise("-118000"), "-₹1,180.00");
  // A grouped string is a RENDERING. Number("1,18,000") is NaN and the old
  // formatter printed ₹NaN; Number("") is 0, which is worse.
  assert.equal(formatPaise("1,18,000"), NO_FIGURE);
  assert.equal(formatPaise(""), NO_FIGURE);
  assert.equal(formatPaise("   "), NO_FIGURE);
  assert.equal(formatPaise("abc"), NO_FIGURE);
  assert.equal(formatPaise(NaN), NO_FIGURE);
  assert.equal(formatPaise(Infinity), NO_FIGURE);
});

test("a whole-rupee figure is the server's, and one carrying paise is NOT rounded", () => {
  assert.equal(formatWhole(12345600), "₹1,23,456");
  assert.equal(formatWhole(0), "₹0");
  // THE RULE. CGST §170 rounds half UP and `domain/gst/money.py` is the
  // authority; a browser-side round() disagrees with it at exactly ₹x.50,
  // which is the value it is most often asked about. So the paise are SHOWN
  // and the row stands out, rather than a different rounding being filed.
  assert.equal(formatWhole(12345650), "₹1,23,456.50");
  assert.equal(formatWhole(1), "₹0.01");
  assert.ok(carriesPaise(12345650));
  assert.ok(!carriesPaise(12345600));
  assert.ok(!carriesPaise(null));
});

test("the bare form drops the symbol and nothing else", () => {
  assert.equal(formatPaiseBare(12345678), "1,23,456.78");
  assert.equal(formatPaiseBare(null), NO_FIGURE);
  assert.ok(!formatPaiseBare(100).includes("₹"));
});

test("negatives keep the sign in front of the symbol", () => {
  // Not "₹-1,23,456.78": a minus buried after the symbol is missed in a
  // column, and an overdrawn balance is exactly what a CA is scanning for.
  assert.equal(formatPaise(-12345678), "-₹1,23,456.78");
  assert.equal(formatWhole(-12345600), "-₹1,23,456");
});

test("toPaise is the one parse, and it is total", () => {
  assert.equal(toPaise(5), 5);
  assert.equal(toPaise("5"), 5);
  assert.equal(toPaise(null), null);
  assert.equal(toPaise("5.5"), null, "paise are integers");
  assert.equal(toPaise("0x10"), null);
  assert.equal(toPaise("1e3"), null, "an exponent is not a paise figure");
});
