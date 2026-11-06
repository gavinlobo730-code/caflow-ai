// Run with: node --experimental-strip-types --test lib/tds/excludedTyped.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { readExcludedTyped } from "./excludedTyped.ts";

const ROW = {
  id: "t1", deductee_name: "Acme Services", deductee_pan: "AAACA1234A", section: "194J", section_1961: "194J",
  transaction_date: "2025-10-12", payment_amount_paise: 10000000, tds_paise: 1000000,
};
const SERVER = {
  count: 2, payment_paise: 14000000, tds_paise: 1080000, reason: "The server's sentence.",
  deductions: [ROW, { ...ROW, id: "t2", transaction_date: "2025-12-05", payment_amount_paise: 4000000, tds_paise: 80000 }],
};

function some(raw: unknown) {
  const got = readExcludedTyped(raw);
  assert.equal(got.kind, "some", JSON.stringify(raw));
  if (got.kind !== "some") throw new Error("unreachable");
  return got.typed;
}

test("a whole answer is read as it was sent, and nothing is added up here", () => {
  const got = some(SERVER);
  assert.equal(got.count, 2);
  assert.equal(got.tds_paise, 1080000);
  assert.equal(got.reason, "The server's sentence.");
  assert.equal(got.rows?.length, 2);
  assert.deepEqual(got.rows?.[0], ROW);
});

test("nothing left out is none, and no key at all is absent: they are not the same fact", () => {
  assert.deepEqual(readExcludedTyped({ ...SERVER, count: 0, tds_paise: 0, deductions: [] }), { kind: "none" });
  assert.deepEqual(readExcludedTyped({ count: 0 }), { kind: "none" });
  assert.deepEqual(readExcludedTyped(undefined), { kind: "absent" });
  assert.deepEqual(readExcludedTyped(null), { kind: "absent" });
  assert.notDeepEqual(readExcludedTyped({ count: 0 }), readExcludedTyped(undefined));
});

test("a key that is there and cannot be read is unreadable, never none", () => {
  for (const raw of ["2 deductions", 2, true, [SERVER], { ...SERVER, count: "2" }, { ...SERVER, count: 1.5 }, { ...SERVER, count: -1 }, { ...SERVER, count: null },
    { ...SERVER, count: undefined }, { ...SERVER, tds_paise: "1080000" }, { ...SERVER, tds_paise: null }, { ...SERVER, tds_paise: undefined }, { ...SERVER, tds_paise: -5 },
    { ...SERVER, tds_paise: 1.5 }, { ...SERVER, tds_paise: Number.NaN }, { ...SERVER, tds_paise: Number.POSITIVE_INFINITY }]) {
    assert.deepEqual(readExcludedTyped(raw), { kind: "unreadable" }, JSON.stringify(raw));
  }
});

test("a figure the server did not send is not a figure of nothing", () => {
  const noTax: Partial<typeof SERVER> = { ...SERVER };
  delete noTax.tds_paise;
  assert.deepEqual(readExcludedTyped(noTax), { kind: "unreadable" });
});

test("only what the note draws is required: the payment total and the sentence are optional", () => {
  const noPayment: Partial<typeof SERVER> = { ...SERVER };
  delete noPayment.payment_paise;
  assert.equal(some(noPayment).tds_paise, 1080000);
  assert.equal(some({ ...SERVER, payment_paise: "14000000" }).count, 2);
  for (const reason of ["", "   ", undefined, null, 7, {}]) {
    assert.equal(some({ ...SERVER, reason }).reason, null, JSON.stringify(reason));
  }
  assert.equal(some({ ...SERVER, reason: "  kept as sent  " }).reason, "  kept as sent  ");
});

test("a list that is not whole is not drawn, and the count and the tax still are", () => {
  for (const deductions of [undefined, null, "rows", [], [ROW], [ROW, ROW, ROW], [ROW, null], [ROW, { ...ROW, tds_paise: "80000" }],
    [ROW, { ...ROW, transaction_date: 20251205 }], [ROW, { ...ROW, deductee_pan: 7 }], [ROW, { ...ROW, section: {} }]]) {
    const got = some({ ...SERVER, deductions });
    assert.equal(got.count, 2);
    assert.equal(got.tds_paise, 1080000);
    assert.equal(got.rows, null, JSON.stringify(deductions));
  }
});

test("a row with no PAN or no name is read as unknown, never as a value", () => {
  const got = some({ ...SERVER, count: 1, deductions: [{ ...ROW, deductee_pan: null, deductee_name: null, section_1961: undefined }] });
  assert.ok(got.rows);
  assert.equal(got.rows[0].deductee_pan, null);
  assert.equal(got.rows[0].deductee_name, null);
  assert.equal(got.rows[0].section_1961, null);
});

test("the answer is not changed by being read", () => {
  const before = JSON.stringify(SERVER);
  readExcludedTyped(SERVER);
  assert.equal(JSON.stringify(SERVER), before);
});
