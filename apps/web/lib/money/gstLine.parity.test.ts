/**
 * Frontend half of the frontend/backend GST parity guard.
 *
 * shared/gst-parity-vectors.json is GENERATED from the real Python backend
 * (apps/api/tests/generate_gst_parity_vectors.py) and asserted on that side by
 * test_gst_parity_vectors.py. Here we require the preview math to land on the
 * exact same integers. If either implementation drifts, one of the two tests
 * goes red — the preview can no longer quietly disagree with what gets saved.
 *
 * The bugs this exists to prevent, both real:
 *   - GST was Math.round(taxable * pct / 100) where the server floors:
 *     ₹105.55 @ 18% previewed 1900 paise, saved 1899.
 *   - Taxable was Math.round(qty * rate * 100) in binary floating point where
 *     the server does exact decimal and TRUNCATES: qty 0.335 × ₹1.00 previewed
 *     34 paise, saved 33.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  applyDiscountsToLines,
  computeLineGst,
  gstRateBpsFromPercent,
  quantityFromInput,
  ratePaiseFromRupees,
  splitLineGst,
  taxablePaise,
} from "./gstLine.ts";
import { previewTotals } from "../invoices/gst.ts";
import { toInvoiceLinePayload } from "../invoices/lineItemPayload.ts";

interface Vector {
  label: string;
  qty: string;
  rate: string;
  gst_rate_percent: number;
  is_interstate: boolean;
  payload: { quantity: number; rate_paise: number; gst_rate_bps: number };
  expected: {
    taxable_paise: number;
    cgst_paise: number;
    sgst_paise: number;
    igst_paise: number;
    line_total_paise: number;
  };
}

interface DocCase {
  label: string;
  is_interstate: boolean;
  round_off_enabled: boolean;
  lines: { qty: string; rate: string; gst_rate_percent: number }[];
  expected: {
    taxable_paise: number;
    cgst_paise: number;
    sgst_paise: number;
    igst_paise: number;
    gst_paise: number;
    round_off_paise: number;
    grand_total_paise: number;
  };
}

interface DiscountCase {
  label: string;
  is_interstate: boolean;
  document_discount_percent_bps: number | null;
  document_discount_paise: number | null;
  lines: {
    qty: string;
    rate: string;
    gst_rate_percent: number;
    discount_percent_bps: number | null;
    discount_paise: number | null;
  }[];
  expected: {
    lines: {
      gross_paise: number;
      discount_paise: number;
      taxable_paise: number;
      cgst_paise: number;
      sgst_paise: number;
      igst_paise: number;
    }[];
    total_gross_paise: number;
    total_discount_paise: number;
    taxable_paise: number;
    cgst_paise: number;
    sgst_paise: number;
    igst_paise: number;
    gst_paise: number;
    grand_total_paise: number;
  };
}

const fixture = JSON.parse(
  readFileSync(
    new URL("../../../../shared/gst-parity-vectors.json", import.meta.url),
    "utf8",
  ),
) as { vectors: Vector[]; documents: DocCase[]; discounts: DiscountCase[] };

test("fixture is present and non-trivial", () => {
  assert.ok(fixture.vectors.length >= 30, "parity vectors were trimmed");
  assert.ok(fixture.documents.length >= 5, "parity documents were trimmed");
  assert.ok(fixture.discounts.length >= 10, "discount parity cases were trimmed");
});

// ── §15(3)(a): the discount comes off before the tax, identically both sides ──
//
// These pin the TAXABLE VALUE, not just the discount arithmetic: the discount
// is subtracted first and the GST charged on what is left, so a browser that
// allocated a document discount even a paise differently would preview a
// different tax from the one the server saves.
for (const d of fixture.discounts) {
  test(`discount parity — ${d.label}`, () => {
    const resolved = applyDiscountsToLines(
      d.lines.map((ln, i) => ({
        gross_paise: d.expected.lines[i].gross_paise,
        discount_percent_bps: ln.discount_percent_bps,
        discount_paise: ln.discount_paise,
      })),
      d.document_discount_percent_bps,
      d.document_discount_paise,
    );
    assert.ok(resolved, `the server accepted ${d.label}; the preview refused it`);

    // The gross the browser derives from the raw strings must be the gross the
    // fixture says the server computed — otherwise the discounts below are
    // parity against the wrong input.
    d.lines.forEach((ln, i) => {
      const gross = taxablePaise(quantityFromInput(ln.qty), ratePaiseFromRupees(ln.rate));
      assert.equal(gross, d.expected.lines[i].gross_paise, `gross, line ${i}`);
    });

    let taxable = 0, cgst = 0, sgst = 0, igst = 0;
    resolved.forEach((r, i) => {
      const want = d.expected.lines[i];
      assert.equal(r.discount_paise, want.discount_paise, `discount, line ${i}`);
      assert.equal(r.taxable_paise, want.taxable_paise, `taxable, line ${i}`);

      const heads = splitLineGst(
        r.taxable_paise,
        gstRateBpsFromPercent(d.lines[i].gst_rate_percent),
        d.is_interstate,
      );
      assert.equal(heads.cgst_paise, want.cgst_paise, `cgst, line ${i}`);
      assert.equal(heads.sgst_paise, want.sgst_paise, `sgst, line ${i}`);
      assert.equal(heads.igst_paise, want.igst_paise, `igst, line ${i}`);

      taxable += r.taxable_paise;
      cgst += heads.cgst_paise;
      sgst += heads.sgst_paise;
      igst += heads.igst_paise;
    });

    assert.equal(taxable, d.expected.taxable_paise, "document taxable");
    assert.equal(cgst + sgst + igst, d.expected.gst_paise, "document GST");
    assert.equal(
      resolved.reduce((a, r) => a + r.discount_paise, 0),
      d.expected.total_discount_paise,
      "the allocated parts must sum to the whole discount",
    );
  });
}

test("a discount larger than the line is refused, not capped", () => {
  // The server raises a 422; a preview that silently capped it would show a
  // figure that cannot be saved, which is the drift this whole fixture exists
  // to prevent.
  assert.equal(applyDiscountsToLines([{ gross_paise: 100, discount_paise: 101 }]), null);
  assert.equal(applyDiscountsToLines([{ gross_paise: 100 }], null, 101), null);
  assert.equal(applyDiscountsToLines([{ gross_paise: 100, discount_percent_bps: 10001 }]), null);
});

for (const v of fixture.vectors) {
  test(`line parity — ${v.label}`, () => {
    // The payload the frontend would actually send must match what the fixture
    // says the server received; otherwise the amounts below are parity against
    // the wrong input.
    assert.equal(quantityFromInput(v.qty), v.payload.quantity, "quantity");
    assert.equal(ratePaiseFromRupees(v.rate), v.payload.rate_paise, "rate_paise");
    assert.equal(
      gstRateBpsFromPercent(v.gst_rate_percent),
      v.payload.gst_rate_bps,
      "gst_rate_bps",
    );

    const got = computeLineGst(
      { qty: v.qty, rate: v.rate, gst_rate: v.gst_rate_percent },
      v.is_interstate,
    );
    assert.deepEqual(
      {
        taxable_paise: got.taxable_paise,
        cgst_paise: got.cgst_paise,
        sgst_paise: got.sgst_paise,
        igst_paise: got.igst_paise,
        line_total_paise: got.line_total_paise,
      },
      v.expected,
    );
  });
}

for (const d of fixture.documents) {
  test(`document parity — ${d.label}`, () => {
    const lines = d.lines.map((l) => ({
      description: "x",
      hsn_sac: "9982",
      qty: l.qty,
      rate: l.rate,
      gst_rate: l.gst_rate_percent,
      unit: "",
    }));
    const t = previewTotals(lines, d.is_interstate, d.round_off_enabled);
    assert.deepEqual(
      {
        taxable_paise: t.taxable_paise,
        cgst_paise: t.cgst_paise,
        sgst_paise: t.sgst_paise,
        igst_paise: t.igst_paise,
        gst_paise: t.gst_paise,
        round_off_paise: t.round_off_paise,
        grand_total_paise: t.grand_total_paise,
      },
      d.expected,
    );
  });
}

// ── The specific regressions, spelled out ────────────────────────────────────

test("GST floors, never rounds — ₹105.55 @ 18% is 1899 paise not 1900", () => {
  const g = computeLineGst({ qty: "1", rate: "105.55", gst_rate: 18 }, false);
  assert.equal(g.cgst_paise + g.sgst_paise, 1899);
  assert.equal(g.line_total_paise, 12_454);
  // The split must still sum to what the same supply would attract as IGST.
  const inter = computeLineGst({ qty: "1", rate: "105.55", gst_rate: 18 }, true);
  assert.equal(g.cgst_paise + g.sgst_paise, inter.igst_paise);
});

test("taxable truncates, never rounds — 0.335 × ₹1.00 is 33 paise not 34", () => {
  assert.equal(taxablePaise(0.335, 100), 33);
  assert.equal(taxablePaise(2.5, 100), 250);
  assert.equal(taxablePaise(0.5, 1), 0); // 0.5 truncates to 0, not 1
});

test("exact decimal, not binary float — 0.29 × 100 is 29 not 28", () => {
  // 0.29 * 100 === 28.999999999999996 in IEEE-754; truncating that naively
  // gives 28. The exact-decimal path must give 29.
  assert.equal(taxablePaise(0.29, 100), 29);
  assert.equal(taxablePaise(1.1, 100), 110);
  assert.equal(taxablePaise(8.7, 100), 870);
});

test("SGST carries the odd paise, and heads never exceed the full tax", () => {
  for (let taxable = 0; taxable < 400; taxable++) {
    for (const bps of [10, 25, 100, 150, 300, 500, 600, 750, 1200, 1800, 2800]) {
      const intra = splitLineGst(taxable, bps, false);
      const inter = splitLineGst(taxable, bps, true);
      const full = Math.floor((taxable * bps) / 10000);
      assert.equal(intra.cgst_paise + intra.sgst_paise, full);
      assert.equal(inter.igst_paise, full);
      assert.ok(intra.sgst_paise - intra.cgst_paise <= 1);
    }
  }
});

test("the payload builder and the preview share one rupee→paise conversion", () => {
  // Same input through both paths must yield the same rate_paise — this is what
  // stops the preview reasoning about a different number than the one sent.
  for (const rate of ["105.55", "0.29", "1.005", "99999.99", "0", "1234.56"]) {
    const payload = toInvoiceLinePayload({
      description: "x", hsn_sac: "9982", qty: "1", rate, gst_rate: 18,
    });
    assert.equal(payload.rate_paise, ratePaiseFromRupees(rate), `rate ${rate}`);
  }
});
