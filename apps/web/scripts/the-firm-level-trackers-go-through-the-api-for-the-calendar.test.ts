// The firm-level /gst and /income-tax trackers read and add `compliance_calendar` rows through the API, never from the browser (POST-A-208).
//
// They used to select the table over PostgREST (and the income-tax one inserted into it), so `rbac()` never ran, the caller's client
// assignment was whatever row security said, and the insert wrote no audit event. The list they show is unchanged (the calendar, said in a
// sentence under the heading by `a-firm-level-tracker-says-what-list-it-shows.test.ts`); how they reach it is the API's.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const read = (p: string) => strip(readFileSync(new URL(`../${p}`, import.meta.url), "utf8"));

for (const [screen, family] of [["app/gst/page.tsx", "gst"], ["app/income-tax/page.tsx", "itr"]] as const) {
  test(`${screen} does not reach the calendar table from the browser`, () => {
    const src = read(screen);
    assert.ok(!/\.from\(\s*["']compliance_calendar["']\s*\)/.test(src), "a direct read or write of compliance_calendar");
    assert.ok(!/getSupabaseClient|selectAll/.test(src), "a direct database client");
    assert.ok(src.includes(`api.compliance.trackerRows("${family}")`), "the tracker's rows come from the API");
  });
}

test("the add is made through the API and offered only to someone the route admits", () => {
  for (const screen of ["app/gst/page.tsx", "app/income-tax/page.tsx"]) {
    const src = read(screen);
    assert.ok(src.includes("api.compliance.addCalendarEntry("), `${screen} adds through the API`);
    assert.match(src, /can\("compliance_record", "write"\)/, `${screen} offers the add button only to someone who may write`);
  }
});

test("the client calls the two routes the server serves", () => {
  const api = read("lib/api/index.ts");
  assert.ok(api.includes("/api/compliance/calendar/tracker?family="));
  assert.match(api, /"\/api\/compliance\/calendar", \{ method: "POST"/);
});
