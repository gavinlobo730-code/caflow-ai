#!/usr/bin/env node
/**
 * The marketing quality pass: Lighthouse and an axe scan over every page of the
 * site, the reports kept, and a summary that prints the plan's performance
 * budget beside what was measured (POST-A-122).
 *
 *   node scripts/quality-pass.mjs --base http://127.0.0.1:4173 --out .qa
 *
 * IT RUNS ON A GITHUB RUNNER, STARTED BY HAND (.github/workflows/marketing-quality.yml),
 * AND NOT IN THE CONTAINER THE SITE IS BUILT IN. That container has no GPU and
 * renders in software, which the plan's own performance note says overstates
 * the real cost of what is drawn, so a figure taken there is not the budget's. No figure from this pass is written into the repository: a run keeps
 * its reports as the run's artifact, and whoever reads them says what they were.
 *
 * WHAT IT NEEDS, all installed by the workflow's job and by nothing else (none of
 * them is in package.json, so the site's own install and Marketing CI pay
 * nothing for them): `lighthouse` (its command line, from node_modules/.bin),
 * `playwright-core` and `@axe-core/playwright`, and a Chrome named by CHROME_PATH
 * (the runner's own; Lighthouse reads the same variable).
 *
 * WHAT IT WRITES under --out: lighthouse/<page>-<form factor>.report.json and
 * .report.html, axe/<page>-<window>.json, summary.json and summary.md. The summary
 * is also appended to the run's page when GITHUB_STEP_SUMMARY is set.
 *
 * EXIT CODE. 0 when every page was measured, whatever the measurements say:
 * there is no baseline yet to fail against, and the point of the pass is the
 * record. 1 when a measurement did not happen (Lighthouse failed on a page, axe
 * could not load or run), because a pass that skipped a page quietly is worse
 * than one that says it could not finish. 2 for a usage error.
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  AXE_TAGS,
  AXE_VIEWPORTS,
  FORM_FACTORS,
  axeCountsOf,
  metricsOf,
  pagesOf,
  planBudget,
  renderSummary,
  slugOf,
} from "./qualityReport.mjs";

const MARKETING = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PLAN = path.resolve(MARKETING, "..", "..", "docs", "marketing", "2026-09-16-website-redesign-plan.md");

function arg(name, fallback) {
  const at = process.argv.indexOf(`--${name}`);
  return at > 0 && process.argv[at + 1] ? process.argv[at + 1] : fallback;
}

const base = (arg("base", "") || "").replace(/\/$/, "");
const out = path.resolve(arg("out", ".qa"));
if (!/^https?:\/\//.test(base)) {
  console.error("quality-pass: --base must be the site's origin, e.g. --base http://127.0.0.1:4173");
  process.exit(2);
}

const pages = pagesOf(path.join(MARKETING, "app"));
const failures = [];
const lighthouse = [];
const axe = [];
fs.mkdirSync(path.join(out, "lighthouse"), { recursive: true });
fs.mkdirSync(path.join(out, "axe"), { recursive: true });

// ── Lighthouse ───────────────────────────────────────────────────────────────

const lighthouseBin = path.join(MARKETING, "node_modules", ".bin", "lighthouse");
if (!fs.existsSync(lighthouseBin)) {
  failures.push("Lighthouse is not installed in this checkout (the workflow adds it with `pnpm add`); no page was measured.");
} else {
  for (const page of pages) {
    for (const formFactor of FORM_FACTORS) {
      const stem = path.join(out, "lighthouse", `${slugOf(page)}-${formFactor}`);
      const args = [
        `${base}${page}`,
        "--quiet",
        "--output=json",
        "--output=html",
        `--output-path=${stem}`,
        "--only-categories=performance,accessibility,best-practices,seo",
        "--chrome-flags=--headless=new --no-sandbox",
        "--max-wait-for-load=45000",
        ...(formFactor === "desktop" ? ["--preset=desktop"] : []),
      ];
      console.log(`lighthouse ${page} (${formFactor})`);
      const run = spawnSync(lighthouseBin, args, { encoding: "utf8", timeout: 180_000 });
      const report = `${stem}.report.json`;
      if (run.status !== 0 || !fs.existsSync(report)) {
        failures.push(`Lighthouse on ${page} (${formFactor}) exited ${run.status ?? run.signal}: ${(run.stderr || "").trim().slice(-400)}`);
        continue;
      }
      lighthouse.push({ page, ...metricsOf(JSON.parse(fs.readFileSync(report, "utf8"))) });
    }
  }
}

// ── axe ──────────────────────────────────────────────────────────────────────

async function scanWithAxe() {
  let chromium;
  let AxeBuilder;
  try {
    const pw = await import("playwright-core");
    chromium = pw.chromium ?? pw.default?.chromium;
    const mod = await import("@axe-core/playwright");
    AxeBuilder = mod.default ?? mod.AxeBuilder;
  } catch (e) {
    failures.push(`axe could not be loaded (${e instanceof Error ? e.message : e}); no page was scanned.`);
    return;
  }
  if (!process.env.CHROME_PATH) {
    failures.push("CHROME_PATH is not set, so axe had no browser; no page was scanned.");
    return;
  }
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, args: ["--no-sandbox"] });
  try {
    for (const page of pages) {
      for (const viewport of AXE_VIEWPORTS) {
        // REDUCED MOTION, AND SCROLLED TO THE END FIRST. The site reveals sections as they scroll into view
        // (components/motion.tsx), and a scan of the default page reads every element caught mid-fade as low
        // contrast: a trial of this scan, run while it was written, reported two dozen such elements on the home
        // page, all of them legible once their section had appeared. Under prefers-reduced-motion the site renders every section in its
        // final state, which is what is then scanned; the scroll reaches anything that waits to be seen.
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          reducedMotion: "reduce",
        });
        try {
          const tab = await context.newPage();
          await tab.goto(`${base}${page}`, { waitUntil: "networkidle", timeout: 60_000 });
          await tab.evaluate(async () => {
            for (let y = 0; y < document.documentElement.scrollHeight; y += 600) {
              window.scrollTo(0, y);
              await new Promise((r) => setTimeout(r, 60));
            }
            window.scrollTo(0, 0);
          });
          await tab.waitForTimeout(500);
          const result = await new AxeBuilder({ page: tab }).withTags(AXE_TAGS).analyze();
          fs.writeFileSync(path.join(out, "axe", `${slugOf(page)}-${viewport.name}.json`), JSON.stringify(result, null, 2));
          axe.push({ page, viewport: viewport.name, ...axeCountsOf(result) });
          console.log(`axe ${page} (${viewport.name}): ${result.violations.length} rules broken`);
        } catch (e) {
          failures.push(`axe on ${page} (${viewport.name}) failed: ${e instanceof Error ? e.message : e}`);
        } finally {
          await context.close();
        }
      }
    }
  } finally {
    await browser.close();
  }
}

await scanWithAxe();

// ── the summary ──────────────────────────────────────────────────────────────

const budget = fs.existsSync(PLAN) ? planBudget(fs.readFileSync(PLAN, "utf8")) : [];
if (!budget.length) failures.push("The plan's performance budget could not be read from docs/marketing/2026-09-16-website-redesign-plan.md.");
const commit = process.env.GITHUB_SHA ?? null;
const summary = renderSummary({ base, commit, budget, lighthouse, axe, failures });
fs.writeFileSync(path.join(out, "summary.md"), summary);
fs.writeFileSync(
  path.join(out, "summary.json"),
  JSON.stringify({ base, commit, pages, budget, lighthouse, axe, failures }, null, 2),
);
if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary);
console.log(summary);

const measuredEverything = lighthouse.length === pages.length * FORM_FACTORS.length && axe.length === pages.length * AXE_VIEWPORTS.length;
process.exit(failures.length || !measuredEverything ? 1 : 0);
