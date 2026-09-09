import { test } from "node:test";
import assert from "node:assert/strict";
import { changedFields, formFor, REPOSTS_THE_ACQUISITION } from "./correction.ts";
import type { CorrectableAsset } from "./correction.ts";

const ASSET: CorrectableAsset = {
  asset_name: "Lathe",
  location: "Bay 1",
  notes: null,
  purchase_cost_paise: 15_00_000_00,
  salvage_value_paise: 0,
  wdv_rate_percent: 18.1,
  useful_life_years: 15,
};

test("an untouched form is not a correction", () => {
  const res = changedFields(ASSET, formFor(ASSET));
  assert.equal(res.ok, false);
});

test("a rename carries nothing that would re-post the acquisition journal", () => {
  // The whole reason this is a module. Sending the whole form back would put
  // purchase_cost_paise in every request, and a rename would reverse and
  // re-post a real journal on a real ledger.
  const res = changedFields(ASSET, { ...formFor(ASSET), asset_name: "Lathe — Bay 2" });
  assert.equal(res.ok, true);
  if (!res.ok) return;
  assert.deepEqual(Object.keys(res.body), ["asset_name"]);
  for (const f of REPOSTS_THE_ACQUISITION) assert.ok(!(f in res.body), f);
});

test("clearing a field sends null rather than dropping it", () => {
  const res = changedFields(ASSET, { ...formFor(ASSET), location: "" });
  assert.equal(res.ok, true);
  if (!res.ok) return;
  assert.deepEqual(res.body, { location: null });
});

test("a corrected cost is the one field that re-posts", () => {
  const res = changedFields(ASSET, { ...formFor(ASSET), purchase_cost_rs: "150000" });
  assert.equal(res.ok, true);
  if (!res.ok) return;
  assert.deepEqual(res.body, { purchase_cost_paise: 1_50_000_00 });
});

test("an amount typed with Indian grouping is refused, not read as one rupee", () => {
  // parseFloat("1,50,000") is 1, and a cost field is exactly where an amount is
  // typed that way. The canonical parser REFUSES it rather than guessing, so
  // the CA is told to retype instead of the register recording ₹1.
  const res = changedFields(ASSET, { ...formFor(ASSET), purchase_cost_rs: "1,50,000" });
  assert.equal(res.ok, false);
  if (res.ok) return;
  assert.match(res.error, /amount/);
});

test("something that is not an amount is refused, never sent as null", () => {
  const res = changedFields(ASSET, { ...formFor(ASSET), purchase_cost_rs: "one lakh fifty" });
  assert.equal(res.ok, false);
  if (res.ok) return;
  assert.match(res.error, /amount/);
});

test("a cleared rate is sent as null, not as zero", () => {
  // 0.00 is a real answer (Land). "" means the CA removed the recorded rate and
  // wants the Schedule II basis back; a 0 would freeze the charge at nothing.
  const res = changedFields(ASSET, { ...formFor(ASSET), wdv_rate_percent: "" });
  assert.equal(res.ok, true);
  if (!res.ok) return;
  assert.deepEqual(res.body, { wdv_rate_percent: null });
});

test("the reason rides along only when one was given", () => {
  const withReason = changedFields(ASSET, { ...formFor(ASSET), asset_name: "X", reason: " typo " });
  assert.equal(withReason.ok, true);
  if (withReason.ok) assert.equal(withReason.body.reason, "typo");

  const without = changedFields(ASSET, { ...formFor(ASSET), asset_name: "X", reason: "   " });
  assert.equal(without.ok, true);
  if (without.ok) assert.ok(!("reason" in without.body));
});
