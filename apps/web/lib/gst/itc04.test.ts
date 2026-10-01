// GST-30 — FORM GST ITC-04 and a lot coming back from a job worker: wording and keying.
//
// Run with:
//   node --experimental-strip-types --test lib/gst/itc04.test.ts
//
// The server decides everything about the statement. What is asserted here is
// that the clock's states are worded as different things — above all that a
// clock which cannot be run is never read as "no deadline" — and that a typed lot
// becomes a request body only through the one quantity parser.
import { test } from "node:test";
import assert from "node:assert/strict";
import { BLANK_LOT, clockText, clockTone, lotBody } from "./itc04.ts";

type C = Parameters<typeof clockText>[0];
const clock = (over: Partial<C>): C => ({
  applies: true, statute: "CGST Act s.143 with Rule 45", months: 12,
  sent_on: "2026-05-10", due_back_by: "2027-05-10", overdue: false,
  days_remaining: 221, consequence: "deemed supplied on the day sent out", gaps: [],
  ...over,
});

test("a running clock says how long is left and to what date", () => {
  assert.equal(clockText(clock({})), "221 days left — due back by 2027-05-10");
  assert.equal(clockText(clock({ days_remaining: 1 })), "1 day left — due back by 2027-05-10");
});

test("a lapsed clock says the date it passed and how long ago", () => {
  const c = clock({ overdue: true, due_back_by: "2026-05-10", days_remaining: -144 });
  assert.equal(clockText(c), "Past the date — due back by 2026-05-10 (144 days ago)");
  assert.equal(clockTone(c), "problem");
});

test("a clock that cannot be run is NOT read as having no deadline", () => {
  const c = clock({ due_back_by: null, overdue: null, days_remaining: null, months: null,
                    gaps: ["Whether these are inputs or capital goods is not recorded."] });
  const text = clockText(c);
  assert.match(text, /cannot be run/);
  assert.match(text, /not recorded/);
  assert.doesNotMatch(text, /no deadline|left/i);
  // Not fine, not a problem: nobody can say. That is attention.
  assert.equal(clockTone(c), "attention");
});

test("moulds and dies read the server's own sentence, not a deadline", () => {
  const c = clock({ applies: false, months: null, due_back_by: null, overdue: null,
                    days_remaining: null,
                    consequence: "Moulds, dies, jigs, fixtures and tools are outside both periods." });
  assert.equal(clockText(c), "Moulds, dies, jigs, fixtures and tools are outside both periods.");
  assert.equal(clockTone(c), "neutral");
});

test("a running clock is neutral", () => {
  assert.equal(clockTone(clock({})), "neutral");
});

const lot = (over = {}) => ({ ...BLANK_LOT, returned_on: "2026-08-20", returned: "4", ...over });

test("a lot becomes a body with quantities as numbers", () => {
  const r = lotBody("CLI", "LINE", lot({ wasted: "0.5", job_worker_challan_no: " JW/22 ",
                                          nature_of_job_work: "Machining" }));
  assert.equal(r.ok, true);
  if (r.ok) {
    assert.deepEqual(r.body, {
      client_id: "CLI", challan_line_id: "LINE", returned_on: "2026-08-20",
      quantity_returned: 4, quantity_lost_or_wasted: 0.5,
      job_worker_challan_no: "JW/22", job_worker_challan_date: null,
      nature_of_job_work: "Machining",
    });
  }
});

test("a lot may be goods alone or waste alone", () => {
  assert.equal(lotBody("C", "L", lot({ returned: "", wasted: "2" })).ok, true);
  assert.equal(lotBody("C", "L", lot({ returned: "3", wasted: "" })).ok, true);
});

test("what is not a quantity is refused, never coerced to a number or to null", () => {
  for (const bad of ["12abc", "1e3", "1.2.3", "1,5", "4.1234", "-1"]) {
    const r = lotBody("C", "L", lot({ returned: bad }));
    assert.equal(r.ok, false, `${JSON.stringify(bad)} must be refused`);
  }
  const w = lotBody("C", "L", lot({ wasted: "x" }));
  assert.equal(w.ok, false);
  if (!w.ok) assert.match(w.error, /lost or wasted/);
});

test("a lot that returns nothing and wastes nothing is refused, and so is no date", () => {
  assert.equal(lotBody("C", "L", lot({ returned: "", wasted: "" })).ok, false);
  assert.equal(lotBody("C", "L", lot({ returned: "0", wasted: "0" })).ok, false);
  assert.equal(lotBody("C", "L", lot({ returned_on: "" })).ok, false);
});
