// POST-A-490: the browser's part of working a GST-inclusive price back is the question and the reading of the answer.
//   node --experimental-strip-types --test lib/invoices/inclusivePrice.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { inclusiveAnswer, inclusiveQuestion, rateBoxText, type LineFacts } from "./inclusivePrice.ts";

const LINE: LineFacts = { qty: "1", gstRatePercent: 18 };
const ANSWER = {
  rate_paise: 1000000, typed_total_paise: 1180000, list_value_paise: 1000000, list_tax_paise: 180000, list_total_paise: 1180000,
  difference_paise: 0, exact: true, discount_paise: 0, taxable_paise: 1000000, tax_paise: 180000, total_paise: 1180000,
  sentence: "A price of ₹10,000.00 a unit before GST gives exactly the ₹11,800.00 you typed for the line.",
};

test("the question carries what was typed, in paise and basis points, and nothing worked out", () => {
  const got = inclusiveQuestion("c-1", "11800", "line", { qty: "2.5", gstRatePercent: 18, discountPercent: "10" });
  assert.deepEqual(got, { question: {
    client_id: "c-1", inclusive_paise: 1180000, basis: "line", quantity: 2.5, gst_rate_bps: 1800, discount_percent_bps: 1000, has_cess: false,
  } });
  // The price is read to the paisa; a rate with a fraction of a percent keeps it.
  const unit = inclusiveQuestion("c-1", "125000.50", "unit", { qty: "3", gstRatePercent: 0.25 });
  assert.ok("question" in unit);
  assert.equal(unit.question.inclusive_paise, 12500050);
  assert.equal(unit.question.gst_rate_bps, 25);
  assert.equal(unit.question.basis, "unit");
  assert.equal(unit.question.discount_percent_bps, null);
});

test("a price typed with grouping is read as what it says (POST-A-567)", () => {
  const got = inclusiveQuestion("c-1", "1,25,000", "line", LINE);
  assert.ok(!("problem" in got), "a properly grouped price was refused");
  if ("problem" in got) return;
  assert.equal(got.question.inclusive_paise, 12_500_000);
});

test("what is not a figure is refused in words, before the server is asked", () => {
  for (const price of ["", "   ", "0", "abc", "12abc", "1e3", "-50", "1.2.3", "1,2,5"]) {
    const got = inclusiveQuestion("c-1", price, "line", LINE);
    assert.ok("problem" in got, `"${price}" was sent as a price`);
    assert.match(got.problem, /price including GST/);
  }
  for (const qty of ["", "0", "abc", "-1"]) {
    const got = inclusiveQuestion("c-1", "11800", "line", { ...LINE, qty });
    assert.ok("problem" in got, `quantity "${qty}" was sent`);
    assert.match(got.problem, /quantity/);
  }
  const bad = inclusiveQuestion("c-1", "11800", "line", { ...LINE, discountPercent: "ten" });
  assert.ok("problem" in bad);
  assert.match(bad.problem, /discount/);
});

test("a line that carries compensation cess says so, and a cess box holding nought does not", () => {
  const ask = (line: Partial<LineFacts>) => {
    const got = inclusiveQuestion("c-1", "11800", "line", { ...LINE, ...line });
    assert.ok("question" in got);
    return got.question.has_cess;
  };
  assert.equal(ask({}), false);
  assert.equal(ask({ cessPercent: "", cessPerUnit: null }), false);
  assert.equal(ask({ cessPercent: "0", cessPerUnit: "0.00" }), false);
  assert.equal(ask({ cessPercent: "12" }), true);
  assert.equal(ask({ cessPerUnit: "4.17" }), true);
  // A cess box that is not a figure is not read as "no cess": the server is told there is one and refuses in its words.
  assert.equal(ask({ cessPercent: "abc" }), true);
});

test("an answer is read only when it is the shape the route sends", () => {
  assert.deepEqual(inclusiveAnswer({ success: true, data: ANSWER, error: null }), ANSWER);
  for (const broken of [
    null, undefined, "x", [], {}, { success: false, data: ANSWER }, { success: true, data: null }, { success: true, data: [] },
    { success: true, data: { ...ANSWER, rate_paise: "1000000" } },
    { success: true, data: { ...ANSWER, rate_paise: 0 } },
    { success: true, data: { ...ANSWER, tax_paise: 1.5 } },
    { success: true, data: { ...ANSWER, total_paise: undefined } },
    { success: true, data: { ...ANSWER, exact: "yes" } },
    { success: true, data: { ...ANSWER, sentence: "  " } },
  ]) assert.equal(inclusiveAnswer(broken), null, JSON.stringify(broken));
});

test("the rate box takes the server's paise written as rupees", () => {
  assert.equal(rateBoxText(ANSWER), "10000.00");
  assert.equal(rateBoxText({ ...ANSWER, rate_paise: 84661 }), "846.61");
  assert.equal(rateBoxText({ ...ANSWER, rate_paise: 8 }), "0.08");
});
