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

// ── How a screen sits on the page, and what it draws while it waits (POST-A-530) ─────────────────────────────────────────────
//
// The owner, walking the live site on 20-11-2026: inside a client's workspace a screen is laid out and waits with placeholders
// shaped like itself; outside it a screen may hug the left edge with the right half of the window empty, and wait as one line of
// plain text. Both are facts about what a BROWSER draws, so they are measured there and not read off class names: a page that
// delegates to a component, or caps an inner card and not its own wrapper, reads one way in the source and draws another.
//
// TWO MEASUREMENTS, ONE PAGE PER ROUTE.
//   waiting  The stubbed API is held for a few seconds and the screen is read while its data is still out: placeholder blocks
//            (the shared `Skeleton`, which is what pulses), words only (a status region or a bare "Loading…" with no shape), or
//            nothing at all. A screen that asked the API for nothing has nothing to wait for and is `static`.
//   layout   Once the data has landed, at a WIDE window (1920: at 1440 the shell's rails leave less than any cap on a data screen,
//            so every screen looks full-width and the measurement says nothing): the screen's own container, which is the first
//            element under `<main>` with more than one visible child, and the gap on each side of it. A container with far more
//            room on its right than its left is capped and not centred, which is "hugs the left".
//
// It reports and judges nothing by itself: the walk writes the rows to its report, and what is a defect is decided there.
export const FRAME_VIEWPORT = { width: 1920, height: 1000 };
export const FRAME_HOLD_MS = 2_500;
/** A container this much closer to the left edge than the right is not centred (pixels at the wide window). */
export const HUGS_LEFT_BY = 48;

export function waitingVerdict(w) {
  if (!w) return "unread";
  if (w.pulses > 0) return w.bare.length ? "placeholders, and bare words" : "placeholders";
  if (w.bare.length) return "bare words";
  if (w.status > 0 || w.spinners > 0) return "words or a spinner, no shape";
  if (w.text) return "the screen itself";
  return w.asked > 0 ? "nothing" : "static";
}

export function layoutVerdict(l) {
  if (!l) return "outside the shell";
  if (l.right - l.left > HUGS_LEFT_BY) return "hugs the left";
  if (l.left <= 1 && l.right <= 1) return "full width";
  return "centred";
}

export async function measureFrame({ context, url, stub, sealOff, escaped, shotBase = null }) {
  const page = await context.newPage();
  const out = { waiting: null, layout: null, error: null };
  const before = stub.requests.length;
  stub.apiDelayMs = FRAME_HOLD_MS;
  try {
    await page.setViewportSize(FRAME_VIEWPORT);
    await sealOff(page, escaped);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForTimeout(1_100);
    const readWaiting = () => page.evaluate(() => {
      const main = document.querySelector("main") || document.body;
      const vis = (el) => {
        const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
      };
      const count = (sel) => [...main.querySelectorAll(sel)].filter(vis).length;
      const bare = []; const inStatus = [];
      const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const t = (n.textContent || "").trim();
        if (!/^(loading\b|please wait|fetching\b)/i.test(t) || t.length > 80) continue;
        const el = n.parentElement;
        if (!el || !vis(el)) continue;
        (el.closest('[role="status"]') ? inStatus : bare).push(t);
      }
      return { pulses: count(".animate-pulse"), status: count('[role="status"]'), spinners: count(".animate-spin"), bare, inStatus,
               text: (main.innerText || "").replace(/\s+/g, " ").trim().slice(0, 140) };
    });
    // A screen behind a gate (the session, the person's permissions) draws nothing until the gate's own read lands, and that
    // read is held too. So a blank first look is the GATE waiting, not the screen: look again once the gate's answer is in and
    // the screen's own reads are the ones being held.
    let waiting = await readWaiting();
    waiting.look = 1;
    if (!waiting.text && !waiting.pulses && !waiting.status && !waiting.spinners) {
      await page.waitForTimeout(FRAME_HOLD_MS);
      waiting = await readWaiting();
      waiting.look = 2;
    }
    waiting.asked = stub.requests.length - before;
    if (shotBase) await page.screenshot({ path: `${shotBase}-waiting.jpg`, type: "jpeg", quality: 80 });
    out.waiting = waiting;
    stub.apiDelayMs = 0;
    await page.waitForLoadState("networkidle", { timeout: 30_000 });
    // The network going quiet is not the screen having settled: a screen that reads one thing and then another is quiet in
    // between, and its placeholder was measured as its layout. Wait for the placeholders to leave, and say so when they do not.
    const settled = await page.waitForFunction(
      () => !document.querySelector('main .animate-pulse, main [role="status"][aria-label^="Loading"]'), null, { timeout: 8_000 },
    ).then(() => true, () => false);
    await page.waitForTimeout(300);
    out.settled = settled;
    out.landed = new URL(page.url()).pathname;
    if (shotBase) await page.screenshot({ path: `${shotBase}-settled.jpg`, type: "jpeg", quality: 80 });
    out.layout = await page.evaluate(() => {
      const main = document.querySelector("main");
      if (!main) return null;
      const kids = (el) => [...el.children].filter((c) => {
        const r = c.getBoundingClientRect(); const s = getComputedStyle(c);
        return r.width > 0 && r.height > 0 && s.display !== "none" && s.position !== "fixed" && s.position !== "absolute";
      });
      let el = main; let depth = 0;
      for (; depth < 14; depth++) { const k = kids(el); if (k.length !== 1) break; el = k[0]; }
      const m = main.getBoundingClientRect(); const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
      return {
        main: Math.round(m.width), width: Math.round(r.width),
        left: Math.round(r.left - m.left), right: Math.round(m.right - r.right),
        cap: cs.maxWidth, depth, cls: String(el.className || "").slice(0, 90),
      };
    });
  } catch (e) {
    out.error = String(e?.message ?? e).split("\n")[0];
  } finally {
    stub.apiDelayMs = 0;
    await page.close();
  }
  return out;
}

// ── The list of screens not yet right, which only shrinks ───────────────────────────────────────────────────────────────────
/** A waiting verdict that is a defect: the screen was asked to wait and drew words, or nothing, where a shape belongs. */
export const WAITS_WITHOUT_A_SHAPE = new Set([
  "words or a spinner, no shape", "bare words", "placeholders, and bare words", "nothing",
]);

/**
 * What a run found against the committed list (`scripts/frame-baseline.json`). `fresh` is a screen that is wrong and not on
 * the list: a new screen, or one that was right. `stale` is a screen on the list that the run measured and found right: its
 * line is deleted, which is how the list shrinks and can never grow. A route the run did not measure (`--only`) is left alone.
 */
/**
 * @typedef {{ route: string, key?: string, layout: string, waiting: string }} FrameRow
 * @typedef {{ hugs_left?: string[], no_placeholder?: string[] }} FrameList
 * @param {FrameRow[]} rows
 * @param {FrameList | null} baseline
 * @returns {{ fresh: Array<{ list: string, route: string, saw: string }>, stale: Array<{ list: string, route: string }> }}
 */
export function judgeFrame(rows, baseline) {
  const measured = new Map(rows.map((r) => [r.key ?? r.route, r]));
  /** @type {{ fresh: Array<{ list: string, route: string, saw: string }>, stale: Array<{ list: string, route: string }> }} */
  const out = { fresh: [], stale: [] };
  const lists = [
    ["hugs_left", (r) => r.layout === "hugs the left"],
    ["no_placeholder", (r) => WAITS_WITHOUT_A_SHAPE.has(r.waiting)],
  ];
  for (const [name, wrong] of lists) {
    const listed = new Set(baseline?.[name] ?? []);
    for (const [key, row] of measured) {
      if (wrong(row) && !listed.has(key)) out.fresh.push({ list: name, route: key, saw: name === "hugs_left" ? row.layout : row.waiting });
      if (!wrong(row) && listed.has(key)) out.stale.push({ list: name, route: key });
    }
  }
  return out;
}

/** The list a run would write: every measured offender, sorted, and the unmeasured lines of the old list kept as they were. */
/**
 * @param {FrameRow[]} rows
 * @param {FrameList | null} [old]
 * @returns {{ hugs_left: string[], no_placeholder: string[] }}
 */
export function frameBaselineFrom(rows, old = null) {
  const measured = new Set(rows.map((r) => r.key ?? r.route));
  /** @param {"hugs_left" | "no_placeholder"} name */
  const keep = (name) => (old?.[name] ?? []).filter((k) => !measured.has(k));
  return {
    hugs_left: [...new Set([...keep("hugs_left"), ...rows.filter((r) => r.layout === "hugs the left").map((r) => r.key ?? r.route)])].sort(),
    no_placeholder: [...new Set([...keep("no_placeholder"), ...rows.filter((r) => WAITS_WITHOUT_A_SHAPE.has(r.waiting)).map((r) => r.key ?? r.route)])].sort(),
  };
}
