/**
 * Group: ai-naming. The AI is presented as PracticeSync AI, the provider stays named, and a model code is shown only
 * once Technical details is opened (POST-A-448).
 *
 * The owner, opening Settings > AI status on 16-11-2026, asked why the screen led with `openai/gpt-oss-120b` and
 * `gemini-3.5-flash`. This serves the status and the month's use with real-looking model codes and reads what a
 * person sees: the codes are not visible until a Technical details is opened, and then they are; the providers and
 * the features' names are visible all along.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";

export const group = "ai-naming";

const TEXT_MODEL_CODE = "openai/gpt-oss-120b";
const IMAGE_MODEL_CODE = "gemini-3.5-flash";
const MONTH = { key: "2026-11", label: "November 2026", starts_on: "2026-11-01", ends_before: "2026-12-01" };
const FIG = { calls: 4, attempts: 4, answered: 4, failed: 0, refused: 0, tokens: 1200, reasoning_tokens: 0, pages: 1 };

function provider(name, label, model) {
  const seen = { at: "2026-11-15T20:00:00Z", model, latency_ms: 900, total_tokens: 40 };
  return {
    provider: name, label, configured: true, model, fallback_models: ["a-fallback-model"],
    status: "ok", status_label: "Answering", status_tone: "ready",
    this_process: { last_attempt: { ...seen, outcome: "ok" }, last_success: seen },
    this_firm: { last_answered: seen, last_attempt: seen },
    this_firm_unread: null,
  };
}

function usage() {
  return {
    month: MONTH, current_month: MONTH, choices: [{ key: MONTH.key, label: MONTH.label }], not_covered: [],
    usage: {
      totals: FIG,
      by_feature: [
        { ...FIG, feature: "invoice_extraction", provider: "gemini", models: [IMAGE_MODEL_CODE],
          label: "PracticeSync AI invoice reader", provider_label: "Gemini" },
        { ...FIG, feature: "assistant", provider: "groq", models: [TEXT_MODEL_CODE],
          label: "PracticeSync AI Assistant", provider_label: "Groq" },
      ],
      by_day: [], truncated: false,
    },
    allowance: { limits: { monthly_tokens: null, monthly_pages: null }, updated_at: null, standing: null },
    first_recorded_at: "2026-11-01T00:00:00Z",
    unread: null,
  };
}

/** The page's text as a person sees it: a closed details element shows only its summary. */
async function visibleText(page) {
  return page.locator("main").innerText();
}

export const scenarios = [
  {
    id: "the-ai-status-page-names-practicesync-and-folds-the-model-codes",
    title: "AI status leads with PracticeSync AI and the providers; a model code shows only under Technical details",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /\/api\/ai-status\/usage/, reply: () => ok(usage()) });
      stub.route({ method: "GET", re: /\/api\/ai-status(\?|$)/, reply: () => ok({
        providers: [provider("groq", "Groq", TEXT_MODEL_CODE), provider("gemini", "Gemini", IMAGE_MODEL_CODE)], not_covered: [] }) });
      await page.goto(env.base + "/settings/ai/", { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "PracticeSync AI status" }).waitFor();
      await page.getByRole("table").first().waitFor();

      const closed = await visibleText(page);
      for (const code of [TEXT_MODEL_CODE, IMAGE_MODEL_CODE, "a-fallback-model"]) {
        assert.ok(!closed.includes(code), `the model code ${code} is visible before Technical details is opened`);
      }
      for (const name of ["Groq", "Gemini", "PracticeSync AI invoice reader", "PracticeSync AI Assistant"]) {
        assert.ok(closed.includes(name), `${name} is not visible`);
      }
      assert.ok(!closed.includes("invoice_extraction"), "the usage table shows a feature by its internal key");

      const folds = page.getByText(/^Technical details/);
      const n = await folds.count();
      assert.ok(n >= 3, `expected a Technical details for each provider and one for the usage, found ${n}`);
      for (let i = 0; i < n; i++) await folds.nth(i).click();
      const open = await visibleText(page);
      for (const code of [TEXT_MODEL_CODE, IMAGE_MODEL_CODE, "a-fallback-model"]) {
        assert.ok(open.includes(code), `the model code ${code} is not under Technical details`);
      }
    },
  },
  {
    id: "the-ai-pages-carry-the-products-name",
    title: "the assistant and the copilot are titled PracticeSync AI",
    async run(env) {
      const { page } = env;
      await page.goto(env.base + "/ai-assistant/", { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "PracticeSync AI Assistant" }).waitFor();
      await page.goto(env.base + "/copilot/", { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "PracticeSync AI Copilot" }).waitFor();
    },
  },
];
