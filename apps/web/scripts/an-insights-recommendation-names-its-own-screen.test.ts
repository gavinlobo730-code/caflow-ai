// sweep-misc-tools-10 / sweep-misc-tools-11.
//
// `compute_recommendations` (apps/api/services/intelligence_service.py) stamps
// every recommendation with an internal routing code — `open_compliance`,
// `open_client`, `open_invoices`, `open_journal_suggestions` — meant for
// ROUTING, never for a CA to read. `/insights` used to print that raw code
// under every card (misc-tools-11) and, whatever the code said, sent the
// card's arrow to the client's generic Overview tab (misc-tools-10) — so
// "Review filings for Acme" (action `open_compliance`) landed on Overview
// exactly like "Re-engage Acme" (action `open_client`), although the same
// page already links its own compliance-risk rows to `/clients/{id}/compliance`.
//
// `lib/insights/recommendationActions.ts` is the one place that now decides
// both: the label shown on the card, and where its arrow goes. These assert
// it against the real backend actions, and assert the page itself never
// prints a raw action code again.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  RECOMMENDATION_ACTIONS,
  recommendationHref,
  recommendationLabel,
} from "../lib/insights/recommendationActions.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => fs.readFileSync(path.join(WEB, p), "utf8");

const CLIENT_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6";

test("every action the backend actually emits is in the map", () => {
  // apps/api/services/intelligence_service.py::compute_recommendations is the
  // one place that stamps `"action": "..."` on a recommendation. Read the
  // literal strings out of it rather than re-typing them here, so a new
  // action added there without a matching entry here fails loudly instead of
  // silently falling back to Overview and no label.
  const src = read("../api/services/intelligence_service.py");
  const emitted = [...src.matchAll(/"action":\s*"([a-z_]+)"/g)].map((m) => m[1]);
  assert.ok(emitted.length >= 4, `expected at least 4 actions in intelligence_service.py, found ${emitted.length}`);
  const missing = emitted.filter((a) => !(a in RECOMMENDATION_ACTIONS));
  assert.deepEqual(missing, [], `action(s) emitted by the backend with no entry in RECOMMENDATION_ACTIONS: ${missing.join(", ")}`);
});

test("a recommendation for a client-scoped action opens that client's own screen, not Overview", () => {
  assert.equal(recommendationHref("open_compliance", CLIENT_ID), `/clients/${CLIENT_ID}/compliance`);
  assert.equal(recommendationHref("open_invoices", CLIENT_ID), `/clients/${CLIENT_ID}/sales?tab=invoices`);
  assert.equal(recommendationHref("open_journal_suggestions", CLIENT_ID), `/clients/${CLIENT_ID}/accounting?tab=journal`);
  assert.equal(recommendationHref("open_client", CLIENT_ID), `/clients/${CLIENT_ID}/overview`);
});

test("an unrecognised or absent action falls back to Overview, not a broken link", () => {
  assert.equal(recommendationHref("some_future_action", CLIENT_ID), `/clients/${CLIENT_ID}/overview`);
  assert.equal(recommendationHref(null, CLIENT_ID), `/clients/${CLIENT_ID}/overview`);
  assert.equal(recommendationHref(undefined, CLIENT_ID), `/clients/${CLIENT_ID}/overview`);
});

test("the label is always a human sentence, and is never shown for an action nobody named", () => {
  for (const action of Object.keys(RECOMMENDATION_ACTIONS)) {
    const label = recommendationLabel(action);
    assert.ok(label, `no label for ${action}`);
    assert.doesNotMatch(label!, /_/, `label for ${action} still looks like a raw action code: "${label}"`);
  }
  assert.equal(recommendationLabel("some_future_action"), null);
  assert.equal(recommendationLabel(null), null);
  assert.equal(recommendationLabel(undefined), null);
});

test("the insights page renders the mapped label, never the raw action code", () => {
  const src = read("app/insights/page.tsx");
  assert.match(src, /recommendationLabel\(/, "the page no longer calls recommendationLabel");
  assert.match(src, /recommendationHref\(/, "the page no longer calls recommendationHref");
  // The defect this replaces: `{r.action && <p ...>{r.action}</p>}` prints
  // the raw code straight onto the card.
  assert.doesNotMatch(src, /\{r\.action\}/, "the page still prints the raw action code");
  // The defect this replaces: every client-scoped card linking to the same
  // hardcoded Overview href regardless of its own action.
  assert.doesNotMatch(
    src,
    /href=\{`\/clients\/\$\{r\.client_id\}\/overview`\}/,
    "the arrow still ignores r.action and always links to Overview",
  );
});
