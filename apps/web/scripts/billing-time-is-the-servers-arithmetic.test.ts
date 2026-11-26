// POST-B-194, hourly billing: the dialog that bills a client's time sends what was ticked and typed and shows what the
// server answers. It adds up nothing, assumes no rate of GST, and never shows an old preview as the new one.
//   node --experimental-strip-types --test scripts/billing-time-is-the-servers-arithmetic.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(import.meta.dirname, "..");
const code = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

test("the dialog works nothing out: no sum, no multiplication, no rounding of money or minutes", () => {
  const dialog = code("components/time/BillTimeDialog.tsx");
  assert.doesNotMatch(dialog, /\.reduce\(/, "the dialog adds something up");
  assert.doesNotMatch(dialog, /Math\.(round|floor|ceil)|\* ?(100|60)\b|\/ ?(100|60)\b/, "the dialog does arithmetic on money or minutes");
  assert.doesNotMatch(dialog, /parseFloat|parseInt/);
  // What it shows is what the readers gave it.
  for (const reader of ["readUnbilledEntries", "readPreview", "readMade", "readServices"]) {
    assert.match(dialog, new RegExp(`${reader}\\(`), `the dialog does not read its answer through ${reader}`);
  }
});

test("a total is shown only for the preview of the ticks and layout on the screen", () => {
  const dialog = code("components/time/BillTimeDialog.tsx");
  assert.match(dialog, /const key = `\$\{grouping\}\|\$\{ids\.join\(","\)\}`;/);
  assert.match(dialog, /const shown = preview && preview\.forKey === key \? preview\.lines : null;/);
  assert.match(dialog, /setPreview\(\{ forKey: key, lines \}\)/);
  // And the draft cannot be made until that preview is on the screen.
  assert.match(dialog, /disabled=\{creating \|\| previewing \|\| !work \|\| ids\.length === 0 \|\| !serviceId \|\| rate === null \|\| !shown\}/);
  // And it cannot be closed while the draft is being made: the person would not learn whether their time was billed.
  assert.match(dialog, /onClose=\{\(\) => \{ if \(!creating\) onClose\(\); \}\}/);
});

test("no rate of GST is assumed: the box starts from the service's recorded rate or empty, and nothing is sent without one", () => {
  const dialog = code("components/time/BillTimeDialog.tsx");
  assert.match(dialog, /const \[gst, setGst\] = useState\(""\);/, "the GST box starts with a figure of the dialog's own");
  assert.match(dialog, /setGst\(service && service\.gstRateBps !== null \? String\(gstRateToPercent\(service\.gstRateBps\)\) : ""\)/);
  assert.match(dialog, /if \(creating \|\| ids\.length === 0 \|\| !serviceId \|\| rate === null\) return;/);
  assert.doesNotMatch(dialog, /gst_rate_percent: 18|"18"/, "a rate is written into the dialog");
  // The server holds none either.
  const router = fs.readFileSync(path.join(WEB, "..", "api", "routers", "billing.py"), "utf8");
  const model = router.slice(router.indexOf("class TimeInvoiceCreateIn"));
  assert.match(model.slice(0, model.indexOf("@router")), /gst_rate_percent: float\n/, "the route gives the rate a default");
});

test("the button is offered on a client's row to whoever may write the practice's billing, and not for time with no client", () => {
  const panel = code("components/time/UnbilledWorkPanel.tsx");
  assert.match(panel, /\{canEdit && id !== "unassigned" && \(\s*<Button[^>]*onClick=\{\(\) => setBilling\(id\)\}>Bill this time<\/Button>/);
  assert.match(panel, /onBilled=\{\(\) => \{ void load\(\); \}\}/, "the panel does not re-read what is unbilled after a draft is made");
  const page = code("app/time/page.tsx");
  assert.match(page, /<UnbilledWorkPanel clients=\{clients\} canEdit=\{canEditRates\} \/>/);
});

test("the three calls go to the hourly-billing doors", () => {
  const api = code("lib/api/index.ts");
  assert.match(api, /`\/api\/billing\/unbilled-work\/entries\?client_id=\$\{encodeURIComponent\(clientId\)\}`/);
  assert.match(api, /"\/api\/billing\/time-invoices\/preview", \{ method: "POST"/);
  assert.match(api, /"\/api\/billing\/time-invoices", \{ method: "POST"/);
});
