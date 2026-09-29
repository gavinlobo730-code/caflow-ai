// apex-overview-practice-04: the CLIENT-scoped health page
// (apps/web/app/clients/[id]/health/page.tsx) read `health_scores.*` via
// `select("*")` — so `hard_override`/`hard_override_reason` were already IN
// the payload — but its `HealthScore` interface never named them and the page
// never rendered them, so a client whose score the backend had CAPPED (e.g.
// `hard_override='gstr3b_overdue_2months'`) showed the capped number right
// next to an Overrides card reading "No overrides recorded", which reads as
// "nothing explains this score". The firm-level equivalent
// (apps/web/app/health/[client_id]/HealthDetailClient.tsx) already renders a
// "Critical Override Active" banner for exactly this; this file pins that the
// client-scoped copy now does too.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => fs.readFileSync(path.join(WEB, p), "utf8");

const CLIENT_PAGE = "app/clients/[id]/health/page.tsx";
const FIRM_PAGE = "app/health/[client_id]/HealthDetailClient.tsx";

test("the client-scoped HealthScore type carries the hard-override columns", () => {
  const src = read(CLIENT_PAGE);
  const iface = src.slice(src.indexOf("interface HealthScore"), src.indexOf("interface HistoryRecord"));
  assert.match(iface, /hard_override\??:\s*string \| null/,
    "HealthScore has no hard_override field — the column was already coming " +
    "back on `select(\"*\")` with nowhere in the type to land");
  assert.match(iface, /hard_override_reason\??:\s*string \| null/,
    "HealthScore has no hard_override_reason field");
});

test("the client-scoped page renders a Critical Override Active banner", () => {
  const src = read(CLIENT_PAGE);
  assert.match(src, /score\.hard_override\s*&&/,
    "nothing on the page branches on score.hard_override — a capped score " +
    "renders with no explanation");
  assert.match(src, /Critical Override Active/,
    "the banner's own headline (the one the firm-level page already uses) " +
    "is missing");
  assert.match(src, /score\.hard_override_reason/,
    "the banner does not show the server's own reason for the cap");
});

test("the banner is rendered ABOVE the score hero, matching the firm-level page's layout", () => {
  const src = read(CLIENT_PAGE);
  const bannerAt = src.indexOf("Critical Override Active");
  // "Score hero" also labels the LOADING SKELETON, earlier in the file — the
  // one that matters here is the real one in the main render path, so take
  // the LAST occurrence rather than the first.
  const heroAt = src.lastIndexOf("Score hero");
  assert.ok(bannerAt > -1 && heroAt > -1 && bannerAt < heroAt,
    "the override banner must appear before the score hero card, the same " +
    "order the firm-level page uses");
});

test("the Overrides card says an automatic override is in force, rather than only 'No overrides recorded', when hard_override is set", () => {
  const src = read(CLIENT_PAGE);
  const overridesSection = src.slice(src.indexOf("{/* Overrides */}"));
  assert.match(overridesSection, /overrides\.length === 0/,
    "could not find the empty-overrides branch to check");
  assert.match(overridesSection, /score\.hard_override/,
    "the empty-overrides branch never looks at score.hard_override, so it " +
    "still reads \"No overrides recorded\" even when an automatic override " +
    "is actively capping the score");
  assert.match(overridesSection, /automatic override/i,
    "the empty-overrides branch has no sentence naming an automatic override");
});

test("the client-scoped page's banner matches the firm-level page's own pattern (not a second, drifting copy)", () => {
  const clientSrc = read(CLIENT_PAGE);
  const firmSrc = read(FIRM_PAGE);
  assert.match(firmSrc, /Critical Override Active/,
    "the firm-level page this was ported from no longer has the phrase — " +
    "update this test's premise rather than the client page");
  // Both use the same severity tokens (state-problem), not an ad-hoc red.
  assert.match(clientSrc, /state-problem/);
});
