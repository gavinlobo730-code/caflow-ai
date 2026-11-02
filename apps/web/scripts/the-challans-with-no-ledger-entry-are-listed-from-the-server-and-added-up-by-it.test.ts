// The firm-wide list of challans tied to no ledger entry is the server's, drawn (POST-A-272, the Partner view).
//
//   node --experimental-strip-types --test scripts/the-challans-with-no-ledger-entry-are-listed-from-the-server-and-added-up-by-it.test.ts
//
// WHAT THIS HOLDS
//   * the panel reads the list from the route that serves it, asks for the server's window and adds nothing up itself: the count, the
//     rupee total and `has_more` are the server's, and the component has no arithmetic over rows;
//   * a read that fails says so in words and draws no table, so an empty panel never reads as "all tied";
//   * the page places the panel, reads it again after a challan is recorded, retracted, tied or untied, and an Open takes the CA to that
//     client's Challans tab;
//   * rendered: the heading counts with the right number agreement and names the rupee total, a window that stopped says so, a full
//     list does not, each row has its client, challan, date, amount and wait, an unknown wait is a dash, and Open is named for its row;
//     nothing to list is one sentence and no table.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";
import { loadModule, requireFromWeb } from "./tsxHarness.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const PANEL = read("components/tds/UnlinkedChallansPanel.tsx");
const PAGE = read("app/tds/page.tsx");
const DATA = read("lib/data/tds.ts");

test("the panel reads the server's list and adds nothing up", () => {
  assert.ok(/listUnlinkedTdsChallans\(SHOWN\)/.test(PANEL), "the panel does not ask the server for its window");
  assert.ok(/\/api\/tds-workspace\/challans\/unlinked\?limit=/.test(DATA), "the reader does not call the route");
  assert.ok(!/\.reduce\(|\.filter\(|\.length\s*[-+*]|\*\s*100|parseFloat|Number\(/.test(PANEL), "the panel does arithmetic over rows");
  assert.ok(/const \{ rows, total, totalPaise, hasMore, longWaitDays, totalWaitingLong \} = data/.test(PANEL), "the figures are not taken from the server's answer");
});

test("a failed read says so and draws no table", () => {
  const failed = PANEL.slice(PANEL.indexOf('state.kind === "failed"'), PANEL.indexOf("return <UnlinkedChallansView"));
  assert.ok(/could not be listed/.test(failed) && !/<table/.test(failed), "a failed read is drawn as a list or as nothing");
});

test("the page places the panel, reads it again after every change to a challan, and Open selects the client and the Challans tab", () => {
  assert.ok(/<UnlinkedChallansPanel reloadKey=\{unlinkedKey\} onOpenClient=\{\(id\) => \{ setSelectedClientId\(id\); setActiveTab\(1\); \}\} \/>/.test(PAGE));
  assert.equal((PAGE.match(/setUnlinkedKey\(\(k\) => k \+ 1\)/g) ?? []).length, 4, "recording, retracting, tying and untying must each read the list again");
});

// ── rendered ───────────────────────────────────────────────────────────────────────────────────────

interface Row { id: string; client_id: string; client_name: string | null; challan_no: string | null; section: string | null; total_paise: number;
                payment_date: string | null; financial_year: string | null; quarter: string | null; days_since_payment: number | null; waiting_long: boolean }
const row = (over: Partial<Row> = {}): Row => ({ id: "c1", client_id: "cl1", client_name: "Acme Traders", challan_no: "CH-77", section: "194C",
  total_paise: 100_000_00, payment_date: "2026-07-07", financial_year: "2026-27", quarter: "Q2", days_since_payment: 118, waiting_long: true, ...over });

function render(d: { rows: Row[]; hasMore: boolean; total: number; totalPaise: number; longWaitDays?: number; totalWaitingLong?: number }): string {
  const data = { longWaitDays: 30, totalWaitingLong: 0, ...d };
  const React = requireFromWeb("react");
  const { renderToStaticMarkup } = requireFromWeb("react-dom/server");
  const { UnlinkedChallansView } = loadModule<{ UnlinkedChallansView: unknown }>("components/tds/UnlinkedChallansPanel");
  return renderToStaticMarkup(React.createElement(UnlinkedChallansView as never, { data, onOpenClient: () => undefined }));
}

test("rendered: the heading counts, the total is the server's, and each row carries its facts", () => {
  const html = render({ rows: [row(), row({ id: "c2", client_name: "Bharat Foods", challan_no: "CH-80", days_since_payment: 1 })], hasMore: false, total: 2, totalPaise: 150_000_00 });
  assert.match(html, /2 recorded challans are tied to no ledger entry/);
  assert.ok(html.includes("Acme Traders") && html.includes("CH-77") && html.includes("194C") && html.includes("118 days") && html.includes("1 day<"), html);
  assert.ok(html.includes("Open Acme Traders&#x27;s challans, CH-77") || html.includes("Open Acme Traders's challans, CH-77"), "Open is not named for its row");
  assert.ok(!html.includes("have waited longest"), "a complete list says it stopped");
});

test("rendered: the long waits are counted by the server, named in the heading and marked on their rows for a screen reader too", () => {
  const html = render({ rows: [row(), row({ id: "c2", days_since_payment: 5, waiting_long: false })], hasMore: false, total: 2, totalPaise: 150_000_00, totalWaitingLong: 1 });
  assert.match(html, /1 waiting over 30 days/);
  assert.equal((html.match(/\(over 30 days\)/g) ?? []).length, 1, "only the long wait is marked");
  assert.ok(!render({ rows: [row({ waiting_long: false })], hasMore: false, total: 1, totalPaise: 1, totalWaitingLong: 0 }).includes("waiting over"), "a heading names waits there are none of");
});

test("rendered: one challan is singular, and a window that stopped says so", () => {
  assert.match(render({ rows: [row()], hasMore: false, total: 1, totalPaise: 100_000_00 }), /1 recorded challan is tied to no ledger entry/);
  const html = render({ rows: [row(), row({ id: "c2" })], hasMore: true, total: 40, totalPaise: 4_000_000_00 });
  assert.match(html, /40 recorded challans are tied/);
  assert.ok(html.includes("Showing the 2 that have waited longest"), html);
});

test("rendered: an unknown wait and a missing date are dashes, never zero", () => {
  const html = render({ rows: [row({ payment_date: null, days_since_payment: null, waiting_long: false, challan_no: null })], hasMore: false, total: 1, totalPaise: 100_000_00 });
  assert.ok(!html.includes("0 days"), html);
  assert.ok((html.match(/>—</g) ?? []).length >= 3, "the missing challan number, date and wait are not dashes");
});

test("rendered: nothing to list is one sentence and no table", () => {
  const html = render({ rows: [], hasMore: false, total: 0, totalPaise: 0 });
  assert.ok(html.includes("Every challan recorded for your clients is tied to a ledger entry."));
  assert.ok(!html.includes("<table"), "an empty list drew a table");
});
