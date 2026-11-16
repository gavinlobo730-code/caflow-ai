/**
 * Group: window-stays-put. The window itself never scrolls: the page scrolls inside its own area (PRE-A-024).
 *
 * The owner saw it on 16-11-2026 on the live AI status page straight after Save allowance: the window scrolled
 * past the end of the page, the top bar went out of view and a screen of blank space showed below. The cause was
 * the usage tables' screen-reader captions. A caption hidden that way is positioned absolutely; with no
 * positioned ancestor it was laid out against the window, outside the scrolling area, and made the window as tall
 * as the whole page. A local build served no usage figures, so no tables and nothing to see, which is why it did
 * not reproduce there. This serves the figures and measures: before Save allowance, after it, and after the page
 * is scrolled to its end, the document is no taller than the window and the window has not moved.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";

export const group = "window-stays-put";

const MONTH = { key: "2026-11", label: "November 2026", starts_on: "2026-11-01", ends_before: "2026-12-01" };
const EARLIER = { key: "2026-10", label: "October 2026", starts_on: "2026-10-01", ends_before: "2026-11-01" };
const FIG = { calls: 12, attempts: 13, answered: 11, failed: 1, refused: 0, tokens: 48210, reasoning_tokens: 9100, pages: 3 };

function usage(month = MONTH) {
  return {
    month,
    current_month: MONTH,
    choices: [{ key: MONTH.key, label: MONTH.label }, { key: EARLIER.key, label: EARLIER.label }],
    not_covered: [],
    usage: {
      totals: FIG,
      by_feature: ["assistant", "copilot", "invoice_reader", "notice_reader", "statement_scan", "digest"].map((f, i) => ({
        ...FIG, feature: f, provider: i % 2 ? "gemini" : "groq", models: ["a model"],
      })),
      by_day: Array.from({ length: 30 }, (_, i) => ({ ...FIG, day: `${month.key}-${String(i + 1).padStart(2, "0")}` })),
      truncated: false,
    },
    allowance: {
      limits: { monthly_tokens: 5000000, monthly_pages: 500 },
      updated_at: "2026-11-15T20:00:00Z",
      standing: {
        tokens: { limit: 5000000, used: 48210, remaining: 4951790, reached: false },
        pages: { limit: 500, used: 3, remaining: 497, reached: false },
        reached: false,
        sentence: null,
      },
    },
    first_recorded_at: "2026-10-01T00:00:00Z",
    unread: null,
  };
}

function provider(name, label) {
  return {
    provider: name, label, configured: true, model: "a model", fallback_models: [],
    status: "ok", status_label: "Answering", status_tone: "ready",
    this_process: { last_attempt: null, last_success: null },
    this_firm: { last_answered: null, last_attempt: null },
    this_firm_unread: null,
  };
}

/** The document's height against the window's, and where the window has scrolled to. */
async function measure(page) {
  return page.evaluate(() => ({
    documentHeight: document.scrollingElement.scrollHeight,
    windowHeight: innerHeight,
    windowScrolledTo: scrollY,
    shellScrolledTo: document.querySelector("main")?.parentElement?.scrollTop ?? 0,
  }));
}

function assertStill(m, when) {
  assert.ok(m.documentHeight <= m.windowHeight,
    `${when}: the document is ${m.documentHeight}px tall in a ${m.windowHeight}px window, so the window can scroll`);
  assert.strictEqual(m.windowScrolledTo, 0, `${when}: the window scrolled to ${m.windowScrolledTo}px`);
  assert.strictEqual(m.shellScrolledTo, 0, `${when}: the shell around the page scrolled to ${m.shellScrolledTo}px`);
}

async function driveTheAiStatusPage(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /\/api\/ai-status\/usage/,
               reply: (req) => ok(usage(/month=2026-10/.test(req.url) ? EARLIER : MONTH)) });
  stub.route({ method: "PUT", re: /\/api\/ai-status\/budget/, reply: () => ok(usage()) });
  stub.route({ method: "GET", re: /\/api\/ai-status(\?|$)/,
               reply: () => ok({ providers: [provider("groq", "Groq"), provider("gemini", "Google Gemini")], not_covered: [] }) });
  await page.goto(env.base + "/settings/ai/", { waitUntil: "networkidle" });
  await page.getByRole("table").first().waitFor();
  assertStill(await measure(page), "with the usage tables on the page");

  await page.getByRole("button", { name: "Save allowance" }).click();
  await page.getByText("Allowance saved.").waitFor();
  assertStill(await measure(page), "after Save allowance");

  await page.locator('section[aria-label="AI use and allowance"] select').first().selectOption(EARLIER.key);
  await page.waitForLoadState("networkidle");
  assertStill(await measure(page), "after choosing another month");

  // Scroll the page to its end with the wheel, the way a person does: the page's own area scrolls, and once it is
  // at its end a further turn must not carry on into the window.
  await page.locator("main").hover();
  for (let i = 0; i < 40; i++) await page.mouse.wheel(0, 600);
  await page.waitForTimeout(200);
  assertStill(await measure(page), "after scrolling the page to its end");
  const mainAtEnd = await page.evaluate(() => {
    const m = document.querySelector("main");
    return m.scrollTop + m.clientHeight >= m.scrollHeight - 2;
  });
  assert.ok(mainAtEnd, "the page's own area did not scroll to its end");
}

export const scenarios = [
  {
    id: "the-ai-status-page-does-not-stretch-the-window",
    title: "with usage figures served, the AI status page keeps the window still: on load, after Save allowance, after another month, at its end",
    async run(env) {
      await driveTheAiStatusPage(env);
    },
  },
  {
    id: "the-ai-status-page-does-not-stretch-the-window-when-zoomed",
    title: "the same at 125% browser zoom (a 1440 by 900 screen lays the page out in 1152 by 720)",
    async run(env) {
      await env.page.setViewportSize({ width: 1152, height: 720 });
      await driveTheAiStatusPage(env);
    },
  },
];
