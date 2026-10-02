// The §16(4) radar renders the server's dates and decides none. Run with:
//   node --experimental-strip-types --test scripts/a-lapsing-credit-is-listed-with-the-servers-date.test.ts
//
// WHAT WAS MISSING
//   `correction_window` has answered "when does this year's window close" since
//   GST-09 and nothing laid it against the credit. A CA could see, bill by bill,
//   that a supplier had not filed and could not see which credits would be GONE
//   on 30 November. gst-15 lists them, nearest lapse first.
//
// THE RULE IS THE SERVER'S — `domain/gst/itc_time_bar` decides what is on the
// list and `correction_window` the date, and
// `apps/api/tests/test_the_16_4_radar_dates_the_credit_that_is_not_yet_claimed.py`
// pins both. This holds what only the screen can get wrong: it computes no date,
// it names no deadline, an empty list is not shown as a clean bill of health
// while a month is unreconciled, and a closed window is still shown.
//
// This reads source, because the web suite has no DOM.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const RADAR = read("components/gst/ItcTimeBarRadar.tsx");
const PAGE = read("app/clients/[id]/compliance/gst/page.tsx");
const API = read("lib/api/index.ts");

test("the radar sits above the ITC register on the client GST tab", () => {
  assert.match(PAGE, /import \{ ItcTimeBarRadar \} from "@\/components\/gst\/ItcTimeBarRadar"/);
  const at = PAGE.indexOf('{tab === "itc" && (');
  assert.ok(at >= 0);
  const block = PAGE.slice(at, PAGE.indexOf(")}", at));
  assert.ok(block.indexOf("<ItcTimeBarRadar clientId={clientId} />")
    < block.indexOf("<ItcRegisterTab clientId={clientId} />"));
});

test("the screen computes no date and names no deadline", () => {
  // No month arithmetic, no `new Date(`, no 30 November and no financial-year
  // arithmetic: every date on screen is one the server sent.
  assert.doesNotMatch(RADAR, /new Date\(/);
  assert.doesNotMatch(RADAR, /setMonth|setDate|getTime\(\)|Date\.now/);
  assert.doesNotMatch(RADAR, /30 November|"11-30"|-11-30/);
  assert.doesNotMatch(RADAR, /november|nov_30/i);
  assert.doesNotMatch(RADAR, /fyEnd|financialYearEnd|gstPeriodFinancialYear/);
});

test("a calendar date is shown without ever being read through UTC", () => {
  // It used to carry its own `day()` helper over `fromLocalISO`. The rule is
  // unchanged and now has one home: the date goes through lib/dates/format,
  // which prints a bare YYYY-MM-DD from its own digits and never parses it.
  assert.match(RADAR, /import \{ formatDate \} from "@\/lib\/dates\/format"/);
  assert.match(RADAR, /formatDate\([a-z]+\.closes_on\)/);
  assert.doesNotMatch(RADAR, /toISOString|Date\.parse|new Date\(/);
});

test("the rule sentence on screen is the one the server sent", () => {
  assert.match(RADAR, /radar\?\.rule \?\?/);
});

test("the list is read through the one typed API call and its lists are guarded", () => {
  assert.match(API, /itcTimeBar: \(clientId: string\) =>/);
  assert.match(API, /"\/api\/gst-workspace\/itc\/time-bar\?client_id="|\/api\/gst-workspace\/itc\/time-bar\?client_id=/);
  assert.match(RADAR, /api\.gstWorkspace\.itcTimeBar\(clientId\)/);
  assert.match(RADAR,
    /objectWithLists<ItcTimeBar>\(\s*r\.data, "items", "by_financial_year", "periods_not_reconciled",\s*"notes", "scanned_financial_years"\)/);
});

test("it is read-only: nothing here claims, posts, files or sends", () => {
  assert.doesNotMatch(RADAR, /method: "(POST|PUT|PATCH|DELETE)"/);
  assert.doesNotMatch(RADAR, /<button|onClick|onSubmit|<form/);
  assert.doesNotMatch(RADAR, /localStorage|sessionStorage|fetch\(/);
});

test("a window that has closed is shown, in the problem tone, and says how long ago", () => {
  assert.match(RADAR, /closed: "text-state-problem"/);
  assert.match(RADAR, /closed \$\{Math\.abs\(days\)\} day\(s\) ago/);
  assert.match(RADAR, /closing_soon: "text-state-attention"/);
});

test("an empty list is not a clean bill of health while a month is unreconciled", () => {
  assert.match(RADAR, /radar\.periods_not_reconciled\.length > 0/);
  assert.match(RADAR, /but see the months below that have not been reconciled/);
  assert.match(RADAR, /nothing in them has been checked/);
});

test("withheld bills and unbooked documents are told apart, and the three groups stay apart", () => {
  assert.match(RADAR, /withheld_bill: "Bill — credit withheld"/);
  assert.match(RADAR, /not_booked: "On GSTR-2B — no bill"/);
  assert.match(RADAR, /data-testid="itc-time-bar-unreconciled"/);
  assert.match(RADAR, /radar\.notes\.map/);
});

test("an annual return that brought the date forward says so", () => {
  assert.match(RADAR, /shortened_by_annual_return && " · brought forward by the annual return"/);
});
