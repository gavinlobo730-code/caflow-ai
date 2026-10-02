/**
 * The two things the smoke walk does with a browser beyond "render every route": scan the six named screens
 * with axe (frontend_ux-03) and prove the slow-server notice appears, offers a Retry and goes away
 * (frontend_ux-05). Both take the pieces they need from the walk rather than starting their own, so the walk's
 * stub server, its seal against the real network and its session script stay in one place.
 *
 * The pure half of the accessibility work — which screens, what fails, the ratchet — is `axeAudit.mjs`, and
 * the pure half of the notice is `lib/async/slowServer.ts`. This file is the part that needs Chromium and so
 * cannot be run under plain node; it is exercised by the walk itself, in CI by the nightly.
 */
import { NAMED_SCREENS, auditPage, resolveNamedRoute } from "./axeAudit.mjs";

const trim = (p) => (p.endsWith("/") && p !== "/" ? p.slice(0, -1) : p);

/** The sentence `lib/async/slowServer.ts` exports, held as a literal here ONLY because this file runs under
 *  plain node with no TypeScript. A test (`a-loading-region-says-when-the-server-is-slow.test.ts`) holds the
 *  two equal, so this cannot drift from what the screen says. */
export const WAKING_SENTENCE =
  "The server is waking up. The first screen of the day can take up to a minute.";

/** Open the firm-level menu the way a person does: the top bar's button that controls the workspace menu. */
async function openFirmMenu(page) {
  await page.click('header button[aria-controls="workspace-menu"]', { timeout: 10_000 });
  await page.waitForSelector("#workspace-menu", { timeout: 10_000 });
  // The overlay animates in; scanning mid-transition measures a colour that is about to change.
  await page.waitForTimeout(300);
}

/**
 * Scan each named screen on its own page and return one row per screen.
 *
 * A screen that was not scanned where it was asked is an ERROR row, not a clean one: a signed-in context
 * bounces `/login` to `/`, a missing build 404s, and a scan of the wrong page would say "no violations" about
 * a page nobody meant.
 *
 * Signed-out screens get a context with no session (that is the only way `/login` renders as itself); the rest
 * share one with the walk's fake session. Both are sealed off from the real network, as every walk page is.
 */
export async function auditNamedScreens({
  browser, AxeBuilder, port, clientId, viewport, sessionScript, sealOff, escaped,
}) {
  const signedIn = await browser.newContext({ viewport });
  await signedIn.addInitScript(sessionScript());
  const signedOut = await browser.newContext({ viewport });
  const rows = [];
  try {
    for (const screen of NAMED_SCREENS) {
      const route = resolveNamedRoute(screen, clientId);
      const row = { id: screen.id, label: screen.label, route, findings: [] };
      const page = await (screen.signedIn ? signedIn : signedOut).newPage();
      try {
        await sealOff(page, escaped);
        const asked = route.endsWith("/") ? route : `${route}/`;
        await page.goto(`http://127.0.0.1:${port}${asked}`, { waitUntil: "networkidle", timeout: 30_000 });
        await page.waitForTimeout(400);
        const landed = trim(new URL(page.url()).pathname);
        if (landed !== trim(route)) {
          row.error = `landed on ${landed}, not ${route} — the scan would be of the wrong page`;
        } else if (!(await page.evaluate(() => (document.body.innerText || "").trim()))) {
          row.error = "rendered an empty body";
        } else {
          if (screen.opens === "firm-menu") await openFirmMenu(page);
          const scan = await auditPage(AxeBuilder, page);
          if (scan.error) row.error = scan.error;
          else row.findings = scan.findings;
        }
      } catch (e) {
        row.error = `could not be opened: ${String(e?.message ?? e).split("\n")[0]}`;
      }
      await page.close();
      rows.push(row);
    }
  } finally {
    await signedIn.close();
    await signedOut.close();
  }
  return rows;
}

/**
 * The slow-server notice, driven the way a person meets it: the API takes twenty-four seconds to answer.
 *
 * `/tasks` is a list whose first load is the shared DataTable's loading state (an `AsyncBoundary` with a
 * `load` it can call again), which is the case the audit named. The stub server answers the API and the
 * PostgREST reads after `stub.apiDelayMs`, except the two reads the sign-in guard needs, so the screen itself
 * renders and only its data is slow.
 *
 * It asserts, in order: nothing is said in the first second; the sentence appears (about three seconds in),
 * word for word and ONCE on the page; no Retry is offered yet; a Retry appears (about twenty seconds in);
 * pressing it asks the server again and quiets the notice; and when the first answer lands the notice is gone
 * from the page altogether. Returns the problems found, empty when every step held.
 */
export async function slowServerScenario({ context, port, stub, sealOff, escaped }) {
  const problems = [];
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`threw: ${e.message}`));
  const speaking = page.locator('[data-slow-server-notice]:not([data-slow-server-notice="quiet"])');
  const anyNotice = page.locator("[data-slow-server-notice]");
  const note = (msg) => problems.push(msg);
  stub.apiDelayMs = 24_000;
  stub.requests.length = 0;
  try {
    await sealOff(page, escaped);
    await page.goto(`http://127.0.0.1:${port}/tasks/`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    // The region is mounted, and silent.
    await anyNotice.first().waitFor({ state: "attached", timeout: 15_000 });
    await page.waitForTimeout(1_000);
    if (await speaking.count()) note("the notice spoke inside the first second — a warm server answers in that time");

    // About three seconds in: the sentence, exactly, and once.
    await speaking.first().waitFor({ state: "visible", timeout: 10_000 });
    const said = (await speaking.allInnerTexts()).map((t) => t.trim());
    if (said.length !== 1) note(`${said.length} notices were speaking at once; one is the rule`);
    if (!said[0]?.includes(WAKING_SENTENCE)) note(`the notice said ${JSON.stringify(said[0])}, not the waking-up sentence`);
    if (await page.locator('[data-slow-server-notice] button').count()) note("a Retry was offered at three seconds; it belongs at twenty");

    // About twenty seconds in: a Retry, and it asks the server again.
    const retry = page.locator('[data-slow-server-notice="stalled"] button', { hasText: "Retry" });
    await retry.waitFor({ state: "visible", timeout: 25_000 });
    const before = stub.requests.length;
    await retry.click();
    await page.waitForTimeout(300);
    if (stub.requests.length <= before) note("pressing Retry sent no request");
    if (await page.locator('[data-slow-server-notice="stalled"]').count()) note("the notice was still offering Retry after it was pressed");

    // The first answer lands: nothing about waiting stays on the page.
    await page.waitForFunction(() => document.querySelectorAll("[data-slow-server-notice]").length === 0, null, { timeout: 30_000 });
    if (await page.getByText(WAKING_SENTENCE).count()) note("the sentence was still on the page after the data arrived");
  } catch (e) {
    note(`the scenario stopped: ${String(e?.message ?? e).split("\n")[0]}`);
  } finally {
    stub.apiDelayMs = 0;
    await page.close();
  }
  for (const e of new Set(errors)) note(e);
  return problems;
}
