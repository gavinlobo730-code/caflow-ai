import test from "node:test";
import assert from "node:assert/strict";

import { exportErrorMessage, exportQuery } from "./reportExport.ts";

test("a report is always asked for under a client and a format", () => {
  const q = new URLSearchParams(exportQuery("c-1", "pdf"));
  assert.equal(q.get("client_id"), "c-1");
  assert.equal(q.get("format"), "pdf");
});

test("an empty or absent parameter is left off so the server applies the screen's own default", () => {
  const q = new URLSearchParams(
    exportQuery("c-1", "xlsx", {
      account_id: "a-9", start_date: "2026-04-01", end_date: "", as_of: undefined, basis: "  ",
    }),
  );
  assert.equal(q.get("account_id"), "a-9");
  assert.equal(q.get("start_date"), "2026-04-01");
  assert.equal(q.has("end_date"), false);
  assert.equal(q.has("as_of"), false);
  assert.equal(q.has("basis"), false);
  assert.equal(q.get("format"), "xlsx");
});

test("a refusal is shown as the sentence the server wrote, not the JSON around it", () => {
  const msg = exportErrorMessage(
    new Error(
      'API error 422: {"detail":"This ledger has 9,999 lines in the period, and an export is limited to 6,000. Choose a shorter period and export it in parts."}',
    ),
  );
  assert.equal(
    msg,
    "This ledger has 9,999 lines in the period, and an export is limited to 6,000. Choose a shorter period and export it in parts.",
  );
});

test("an error that is not JSON still says something a person can act on", () => {
  assert.equal(
    exportErrorMessage(new Error("API error 503: upstream unavailable")),
    "The export could not be made (error 503).",
  );
  assert.equal(exportErrorMessage(new Error("Failed to fetch")), "Failed to fetch");
  assert.equal(exportErrorMessage(undefined), "The export could not be made.");
});
