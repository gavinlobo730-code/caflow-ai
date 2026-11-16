/**
 * What the marketing quality pass reads and writes, as pure functions (POST-A-122).
 *
 * The pass itself is scripts/quality-pass.mjs, started by hand from
 * .github/workflows/marketing-quality.yml on a GitHub runner. It runs Lighthouse
 * and an axe scan over every page of the site and keeps the reports. This module
 * is the part that can be tested without a browser: which pages there are, the
 * plan's performance budget as the plan words it, the figures taken out of a
 * Lighthouse report and an axe result, and the summary that puts them side by side
 * (scripts/the-marketing-quality-pass-is-started-by-hand.test.ts).
 *
 * IT JUDGES NOTHING AGAINST A NUMBER OF ITS OWN. The plan's budget
 * (docs/marketing/2026-09-16-website-redesign-plan.md, Stage 2) is five sentences
 * and states no figure for LCP or CLS, so the summary prints those sentences
 * verbatim beside what was measured and leaves the comparison to the reader.
 * The score printed beside each metric is Lighthouse's own (0 to 1), labelled as
 * Lighthouse's. A figure that a report does not carry is printed as a dash,
 * never as zero.
 */
import fs from "node:fs";
import path from "node:path";

/** WCAG 2.0 and 2.1, A and AA: the tags apps/web/scripts/axeAudit.mjs scans the product with. */
export const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/** The two ways each page is measured: Lighthouse's default (a phone on a slow network) and its desktop preset. */
export const FORM_FACTORS = ["mobile", "desktop"];

/** The two windows each page is scanned at for accessibility. */
export const AXE_VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "mobile", width: 390, height: 844 },
];

/**
 * Every page of the site, as the URL path the static export serves it at.
 *
 * Read off the app/ tree rather than listed, so a page added to the site is
 * measured without anybody remembering to add it here. A route group, `(site)`,
 * is not part of the URL; a dynamic segment would have no single URL and is
 * left out (the site has none).
 */
export function pagesOf(appDir) {
  const out = [];
  const walk = (dir, segments) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        const name = entry.name;
        if (name.startsWith("[") || name.startsWith("_") || name.startsWith("@")) continue;
        walk(path.join(dir, name), /^\(.*\)$/.test(name) ? segments : [...segments, name]);
      } else if (/^page\.(tsx|jsx|ts|js)$/.test(entry.name)) {
        out.push(segments.length ? `/${segments.join("/")}/` : "/");
      }
    }
  };
  walk(appDir, []);
  return [...new Set(out)].sort((a, b) => (a === "/" ? -1 : b === "/" ? 1 : a.localeCompare(b)));
}

/** A file name for a page: `home` for `/`, `pricing` for `/pricing/`. */
export function slugOf(route) {
  const s = route.replace(/^\/|\/$/g, "").replace(/\//g, "-");
  return s || "home";
}

/**
 * The plan's performance budget, as the plan words it: the bullets that follow
 * the "**Performance budget" paragraph in Stage 2, each a single line.
 */
export function planBudget(markdown) {
  const lines = markdown.split("\n");
  const start = lines.findIndex((l) => l.startsWith("**Performance budget"));
  if (start < 0) return [];
  const bullets = [];
  for (let i = start + 1; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("#")) break;
    if (line.startsWith("- ")) bullets.push(line.slice(2).trim());
    else if (bullets.length && /^\s+\S/.test(line)) bullets[bullets.length - 1] += ` ${line.trim()}`;
    else if (bullets.length && line.trim() && !/^\s/.test(line)) break;
  }
  return bullets;
}

const score100 = (category) =>
  category && typeof category.score === "number" ? Math.round(category.score * 100) : null;

const audit = (lhr, id) => {
  const a = lhr?.audits?.[id];
  return {
    value: a && typeof a.numericValue === "number" ? a.numericValue : null,
    score: a && typeof a.score === "number" ? a.score : null,
  };
};

/** The figures the summary prints, out of one Lighthouse result (the `.report.json`). */
export function metricsOf(lhr) {
  const lcp = audit(lhr, "largest-contentful-paint");
  const cls = audit(lhr, "cumulative-layout-shift");
  const tbt = audit(lhr, "total-blocking-time");
  const fcp = audit(lhr, "first-contentful-paint");
  return {
    url: lhr?.finalDisplayedUrl ?? lhr?.finalUrl ?? lhr?.requestedUrl ?? null,
    formFactor: lhr?.configSettings?.formFactor ?? null,
    lighthouseVersion: lhr?.lighthouseVersion ?? null,
    performance: score100(lhr?.categories?.performance),
    accessibility: score100(lhr?.categories?.accessibility),
    bestPractices: score100(lhr?.categories?.["best-practices"]),
    seo: score100(lhr?.categories?.seo),
    lcpMs: lcp.value,
    lcpScore: lcp.score,
    cls: cls.value,
    clsScore: cls.score,
    tbtMs: tbt.value,
    fcpMs: fcp.value,
    runWarnings: Array.isArray(lhr?.runWarnings) ? lhr.runWarnings : [],
  };
}

const IMPACTS = ["critical", "serious", "moderate", "minor"];

/** What one axe result found: rules broken, how many elements, by impact. */
export function axeCountsOf(result) {
  const violations = Array.isArray(result?.violations) ? result.violations : [];
  const byImpact = Object.fromEntries(IMPACTS.map((k) => [k, 0]));
  const rules = violations.map((v) => {
    const nodes = Array.isArray(v.nodes) ? v.nodes.length : 0;
    if (v.impact in byImpact) byImpact[v.impact] += nodes;
    return { id: v.id, impact: v.impact ?? null, nodes };
  });
  return {
    url: result?.url ?? null,
    rules,
    nodes: rules.reduce((n, r) => n + r.nodes, 0),
    byImpact,
  };
}

const dash = "—";
const fmtSeconds = (ms) => (typeof ms === "number" ? `${(ms / 1000).toFixed(2)} s` : dash);
const fmtMs = (ms) => (typeof ms === "number" ? `${Math.round(ms)} ms` : dash);
const fmtCls = (v) => (typeof v === "number" ? v.toFixed(3) : dash);
const fmtScore = (v) => (typeof v === "number" ? v.toFixed(2) : dash);
const fmtInt = (v) => (typeof v === "number" ? String(v) : dash);

/**
 * The summary, as Markdown: what was measured and how, the plan's budget word
 * for word, a table of Lighthouse's figures per page and form factor, a table
 * of what axe found per page and window, and every measurement that failed.
 */
export function renderSummary({ base, commit, budget, lighthouse, axe, failures }) {
  const out = [];
  out.push("# Marketing site: Lighthouse and axe");
  out.push("");
  out.push(`Measured: \`${base}\`${commit ? ` at commit \`${commit}\`` : ""}, on a GitHub-hosted runner.`);
  const versions = [...new Set(lighthouse.map((m) => m.lighthouseVersion).filter(Boolean))];
  if (versions.length) out.push(`Lighthouse ${versions.join(", ")}; axe tags ${AXE_TAGS.join(", ")}.`);
  out.push(
    "One run per page and form factor. Lighthouse's mobile run simulates a slow phone and network, so its " +
      "figures are not a visitor's; run it again before reading a small difference as real.",
  );
  out.push("");
  out.push("## The plan's performance budget, word for word");
  out.push("");
  out.push("From docs/marketing/2026-09-16-website-redesign-plan.md, Stage 2:");
  out.push("");
  if (budget.length) for (const line of budget) out.push(`- ${line}`);
  else out.push("- (the budget could not be found in the plan; read the plan by hand)");
  out.push("");
  out.push(
    "The plan states no LCP or CLS figure, so nothing below is marked as passing or failing it. It was " +
      "written for a WebGL globe the hero no longer has (the hero has been a still picture since " +
      "17-09-2026); the line a measured CLS speaks to is the last one. The score beside a metric is " +
      "Lighthouse's own, from 0 to 1.",
  );
  out.push("");
  out.push("## Lighthouse");
  out.push("");
  out.push(
    "| Page | Form factor | Performance | LCP | LCP score | CLS | CLS score | TBT | Accessibility | Best practices | SEO |",
  );
  out.push("|---|---|---|---|---|---|---|---|---|---|---|");
  for (const m of lighthouse) {
    out.push(
      `| ${m.page} | ${m.formFactor ?? dash} | ${fmtInt(m.performance)} | ${fmtSeconds(m.lcpMs)} | ` +
        `${fmtScore(m.lcpScore)} | ${fmtCls(m.cls)} | ${fmtScore(m.clsScore)} | ${fmtMs(m.tbtMs)} | ` +
        `${fmtInt(m.accessibility)} | ${fmtInt(m.bestPractices)} | ${fmtInt(m.seo)} |`,
    );
  }
  const warned = lighthouse.filter((m) => m.runWarnings.length);
  for (const m of warned) out.push("", `Lighthouse warned on ${m.page} (${m.formFactor}): ${m.runWarnings.join(" ")}`);
  out.push("");
  out.push("## axe");
  out.push("");
  out.push("| Page | Window | Rules broken | Elements | Critical | Serious | Moderate | Minor |");
  out.push("|---|---|---|---|---|---|---|---|");
  for (const a of axe) {
    out.push(
      `| ${a.page} | ${a.viewport} | ${a.rules.length} | ${a.nodes} | ${a.byImpact.critical} | ` +
        `${a.byImpact.serious} | ${a.byImpact.moderate} | ${a.byImpact.minor} |`,
    );
  }
  const broken = axe.filter((a) => a.rules.length);
  if (broken.length) {
    out.push("");
    for (const a of broken) {
      out.push(`- ${a.page} (${a.viewport}): ${a.rules.map((r) => `${r.id} (${r.impact ?? "?"}, ${r.nodes})`).join(", ")}`);
    }
  }
  out.push("");
  out.push(
    "Not covered by either tool, and still to be done by a person: that keyboard focus is visible on every " +
      "control, that the layout holds at phone widths beyond the one window scanned, and the path from each " +
      "call to action to the demo form.",
  );
  if (failures.length) {
    out.push("");
    out.push("## Measurements that did not happen");
    out.push("");
    for (const f of failures) out.push(`- ${f}`);
  }
  out.push("");
  return out.join("\n");
}
