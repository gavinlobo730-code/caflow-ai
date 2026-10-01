#!/usr/bin/env node
/**
 * Asks the LIVE site whether the redirect rules it was built with are the rules
 * it actually serves (ops-25).
 *
 * WHY THIS EXISTS
 *   apps/web is a static export, so `/clients/<any id>/<section>/` exists only as
 *   a Cloudflare Pages REWRITE to the pre-built `_placeholder` page, written into
 *   public/_redirects by generate-redirects.js. Cloudflare allows 100 dynamic
 *   rules, counts by POSITION (every rule after the first dynamic one), and DROPS
 *   what is past the cap WITHOUT A WORD. On 30-09-2026 it dropped 30 rules,
 *   including every splat: each hard reload or shared link into a client page
 *   returned 404 in production for as long as nobody reloaded one, because
 *   in-app navigation never asks the server.
 *
 *   The repository's other checks are all static. `generate-redirects.test.ts`
 *   counts rules in the FILE, and a file can be perfectly under budget while the
 *   site serves something else (it was, for the count by syntax). Nothing asked
 *   the site. This does.
 *
 * WHAT IT REQUESTS
 *   One real URL per rule, derived from the file itself:
 *     - a literal rule: its own path;
 *     - an enumerated rule (`/clients/:id/accounting`): the path with every
 *       `:name` filled in;
 *     - a splat rule (`/clients/:id/year-end/xbrl/*`): every REAL page it serves,
 *       in both shapes a browser asks for (`.../` and `.../index.txt`). A splat's
 *       test URL has to be a page that exists, or it 404s with the rule working
 *       (CLAUDE.md, Deployment) — so the candidates are the pages the enumerated
 *       rules name, and a candidate is kept only when this splat is the FIRST
 *       rule to claim it.
 *
 *   THE FIRST-MATCH MODEL IS THE WHOLE POINT, AND IT FOUND SOMETHING ON THE
 *   FIRST RUN. `:id` matches any run of non-slash characters, dots included, so
 *   `/clients/probe.txt` is claimed by `/clients/:id` and never reaches
 *   `/clients/:id.txt` — measured live: it answers text/html, not the RSC
 *   payload. Such a rule can never fire, so it is reported as DEAD and is not
 *   requested (a probe for it would fail for a reason that is not a regression).
 *
 * WHAT COUNTS AS A FAILURE
 *   Not just a 404. A rewrite rule answers 200 IN PLACE, so:
 *     - any redirect (3xx) fails — a bare path that bounces to its target has
 *       leaked `_placeholder` into the address bar, and the app would read it as
 *       the client id;
 *     - any status but 200 fails;
 *     - a 200 whose body differs from the page the rule points at FAILS. That is
 *       the failure status codes cannot see: the generator's own header records
 *       Cloudflare serving `/health/[client_id]`'s bundle for `/health/critical/`
 *       with a 200. The rewrite and a direct fetch of the target are
 *       byte-identical (measured), so any difference is a wrong page.
 *   A failure is retried (default three attempts) before it is reported, so a
 *   deploy propagating or a transient 5xx does not page anybody; a rule that is
 *   broken stays broken.
 *
 * THE CONTROL
 *   A path no rule matches must answer 404. If it answers 200 the probe cannot
 *   tell a miss from a hit (a site that became a catch-all, a challenge page in
 *   front of the runner) and every green above it means nothing — so that is a
 *   failure too, with its own sentence.
 *
 * WHAT IT DOES NOT DO
 *   It does not decide whether the file is over budget (generate-redirects.test.ts
 *   does, and owns the number); it reports the position of a failing rule against
 *   Cloudflare's positional cap so a red says WHICH kind of red it is. It is
 *   read-only: GET requests, nothing written, nothing submitted anywhere.
 *
 * Usage:
 *   node scripts/check-live-redirects.mjs                     # production
 *   node scripts/check-live-redirects.mjs --base-url https://<hash>.caflow-ai.pages.dev
 *   node scripts/check-live-redirects.mjs --list              # the probes, no requests
 *   LIVE_BASE_URL=... node scripts/check-live-redirects.mjs
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_RULES_FILE = path.join(__dirname, "..", "public", "_redirects");

/** The product's own hostname — NOT practicesync.pages.dev, which is the marketing site. */
export const PRODUCTION_URL = "https://caflow-ai.pages.dev";

/** What a `:name` is replaced with. Any single segment works, because every
 * such rule rewrites to `_placeholder` whatever it matched. */
export const SAMPLE_VALUE = "probe";

/** A path no rule matches. It must 404. */
export const CONTROL_PATH = "/__live-redirects-control__/";

/** Cloudflare Pages' cap on dynamic rules. Owned by generate-redirects.test.ts;
 * repeated here only to say where a failing rule sits relative to it. */
export const DYNAMIC_RULE_CAP = 100;

/**
 * @typedef {{from: string, to: string, status: string, line: number}} Rule
 * @typedef {{rule: string, kind: string, url: string, target: string, position: number, baseline: boolean}} Probe
 * @typedef {Probe & {problem: string, beyondBudget: boolean}} Failure
 * @typedef {{url: string, target: string, baseline: boolean}} ProbeLike
 * @typedef {{status?: number, location?: string|null, type?: string|null, digest?: string, error?: string}} Answer
 */

// ── the rule file ───────────────────────────────────────────────────────────────

/**
 * @param {string} text
 * @returns {Rule[]}
 */
export function parseRules(text) {
  /** @type {Rule[]} */
  const rules = [];
  text.split("\n").forEach((raw, i) => {
    const line = raw.trim();
    if (!line || line.startsWith("#")) return;
    const [from, to, status] = line.split(/\s+/);
    if (from && to) rules.push({ from, to, status: status ?? "", line: i + 1 });
  });
  return rules;
}

const isDynamic = (from) => from.includes(":") || from.includes("*");
const isSplat = (rule) => rule.from.endsWith("/*");

/**
 * Cloudflare's matching, as far as this file needs it: `:name` is one run of
 * characters other than "/" (dots included), `*` is everything, the rest is
 * literal, and the whole path must match. A trailing slash is significant.
 */
export function compile(from) {
  let source = "^";
  for (let i = 0; i < from.length; ) {
    const name = from[i] === ":" ? /^:([A-Za-z_][A-Za-z0-9_]*)/.exec(from.slice(i)) : null;
    if (name) {
      source += "([^/]+)";
      i += name[0].length;
    } else if (from[i] === "*") {
      source += "(.*)";
      i += 1;
    } else {
      source += from[i].replace(/[.+?^${}()|[\]\\]/g, "\\$&");
      i += 1;
    }
  }
  return new RegExp(`${source}$`);
}

/** The rule's `to` with `:splat` filled in, or null when the rule does not match. */
export function rewrite(rule, pathname) {
  const m = compile(rule.from).exec(pathname);
  if (!m) return null;
  if (!isSplat(rule)) return rule.to;
  return rule.to.replace(":splat", m[m.length - 1]);
}

/** First-match-wins, exactly as the file is ordered. */
export function resolve(rules, pathname) {
  for (const rule of rules) {
    const target = rewrite(rule, pathname);
    if (target !== null) return { rule, target };
  }
  return null;
}

const sampleFor = (from) => from.replace(/:[A-Za-z_][A-Za-z0-9_]*/g, SAMPLE_VALUE);

/**
 * How many rules Cloudflare spends from its 100-dynamic budget: once its parser
 * has met the first dynamic rule it counts EVERYTHING after it, a literal rule
 * included (30-09-2026). Not the count of lines that contain ":" or "*".
 */
export function cloudflareDynamicCount(rules) {
  const first = rules.findIndex((r) => isDynamic(r.from));
  return first === -1 ? 0 : rules.length - first;
}

/** The rules Cloudflare keeps, in file order: everything up to the cap past the
 * first dynamic rule. What is past it is dropped without a message. */
export function rulesCloudflareKeeps(rules, cap = DYNAMIC_RULE_CAP) {
  const first = rules.findIndex((r) => isDynamic(r.from));
  return first === -1 ? rules : rules.slice(0, first + cap);
}

// ── deriving the probes ─────────────────────────────────────────────────────────

/**
 * One real URL per rule that can fire, plus every real page a splat serves.
 *
 * @param {Rule[]} rules
 * @returns {{
 *   probes: Probe[],
 *   dead: {rule: string, shadowedBy: string|null}[],
 *   uncovered: string[],
 *   misrouted: {rule: string|null, url: string, got: string|null, want: string}[],
 * }}
 *   dead       a rule an earlier rule always claims first, so it can never fire;
 *   uncovered  a splat with no real page it is the first to claim (nothing to ask);
 *   misrouted  a page's own URL (either shape) that the FILE sends somewhere other
 *              than that page — or nowhere. A defect in the file, found without
 *              asking the site, so it is held by a test rather than by a red run.
 *   baseline   whether fetching `target` directly is a fair picture of what the
 *              rewrite should serve. It is not when ANOTHER rule claims the target
 *              path itself: `/clients/_placeholder/year-end/index.txt` is taken by
 *              `/clients/:id/year-end/:engagementId` (which matches "index.txt"),
 *              so a direct fetch returns that rule's page, while the year-end.txt
 *              rewrite — which Cloudflare does not re-evaluate — serves the file.
 */
export function deriveProbes(rules) {
  const live = rules.filter((r) => r.status === "200");
  const position = new Map(live.map((r, i) => [r.from, i + 1]));
  /** @type {Probe[]} */
  const probes = [];
  /** @type {{rule: string, shadowedBy: string|null}[]} */
  const dead = [];
  /** @type {{rule: string|null, url: string, got: string|null, want: string}[]} */
  const misrouted = [];
  const seen = new Set();
  /** @param {{rule: string, kind: string, url: string, target: string}} probe */
  const add = (probe) => {
    const key = `${probe.url}\n${probe.target}`;
    if (seen.has(key)) return;
    seen.add(key);
    const claimed = resolve(live, probe.target);
    probes.push({
      ...probe,
      position: position.get(probe.rule) ?? 0,
      baseline: !claimed || claimed.target === probe.target,
    });
  };

  // 1. Every rule that is not a splat asks for its own path.
  for (const rule of live.filter((r) => !isSplat(r))) {
    const url = sampleFor(rule.from);
    const hit = resolve(live, url);
    if (hit && hit.rule === rule) {
      add({ rule: rule.from, kind: isDynamic(rule.from) ? "enumerated" : "literal", url, target: hit.target });
    } else {
      dead.push({ rule: rule.from, shadowedBy: hit ? hit.rule.from : null });
    }
  }

  // 2. Every real page is asked for in both shapes a browser uses. A page is
  //    what an enumerated bare rule names: its `to` is a directory (trailing
  //    slash) and its `from` is neither a slash form nor an RSC `.txt`. Whichever
  //    rule claims the URL first must send it to that page; where that rule is a
  //    splat, the splat is what the probe exercises.
  const pages = live.filter((r) => !isSplat(r) && r.to.endsWith("/") && !r.from.endsWith("/") && !r.from.endsWith(".txt"));
  const covered = new Set();
  for (const page of pages) {
    const base = sampleFor(page.from);
    for (const [url, want] of [[`${base}/`, page.to], [`${base}/index.txt`, `${page.to}index.txt`]]) {
      const hit = resolve(live, url);
      if (!hit || hit.target !== want) {
        misrouted.push({ rule: hit ? hit.rule.from : null, url, got: hit ? hit.target : null, want });
        continue;
      }
      if (isSplat(hit.rule)) {
        covered.add(hit.rule.from);
        add({ rule: hit.rule.from, kind: "splat", url, target: want });
      }
    }
  }
  const uncovered = live.filter(isSplat).map((r) => r.from).filter((f) => !covered.has(f));
  return { probes, dead, uncovered, misrouted };
}

// ── asking the site ─────────────────────────────────────────────────────────────

/**
 * @param {string} base
 * @param {string} pathname
 * @param {{fetchImpl: typeof fetch, timeoutMs: number}} options
 * @returns {Promise<Answer>}
 */
async function get(base, pathname, { fetchImpl, timeoutMs }) {
  try {
    const res = await fetchImpl(base + pathname, {
      redirect: "manual",
      signal: AbortSignal.timeout(timeoutMs),
      headers: { "user-agent": "practicesync-live-redirects/1", "cache-control": "no-cache" },
    });
    const body = Buffer.from(await res.arrayBuffer());
    return {
      status: res.status,
      location: res.headers.get("location"),
      type: res.headers.get("content-type"),
      digest: crypto.createHash("sha256").update(body).digest("hex").slice(0, 16),
    };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

/** What kind of body a target should be: an RSC payload is text, a page is HTML. */
export const expectedType = (target) => (target.endsWith(".txt") ? "text/plain" : "text/html");

/** A sentence for what is wrong with this probe's answer, or null when nothing is. */
/**
 * @param {ProbeLike} probe
 * @param {Answer} answer
 * @param {Answer|null} targetAnswer
 * @returns {string|null}
 */
export function judge(probe, answer, targetAnswer) {
  if (answer.error) return `the request failed: ${answer.error}`;
  if (answer.status >= 300 && answer.status < 400) {
    return `answered a ${answer.status} redirect to ${answer.location ?? "?"} — a rewrite rule answers 200 in place, and a bounce puts the placeholder in the address bar`;
  }
  if (answer.status !== 200) return `answered HTTP ${answer.status}`;
  // The type is always a fair test, and it is the one that names a rule Cloudflare
  // is not applying: an RSC request answered with HTML is the app's own page.
  const want = expectedType(probe.target);
  if (!String(answer.type ?? "").toLowerCase().startsWith(want)) {
    return `answered 200 but as ${answer.type ?? "no content type"}, where ${probe.target} is ${want} — the rewrite went to the wrong place`;
  }
  if (probe.url === probe.target || !probe.baseline || !targetAnswer) return null;
  if (targetAnswer.error || targetAnswer.status !== 200) {
    return `answered 200, but the page it should serve (${probe.target}) itself answers ${targetAnswer.error ?? `HTTP ${targetAnswer.status}`}`;
  }
  if (answer.digest !== targetAnswer.digest) {
    return `answered 200 with a DIFFERENT page from ${probe.target} — the rewrite went to the wrong place`;
  }
  return null;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Request every probe, retry what fails, and ask the control.
 *
 * @param {{base: string, probes: Probe[], rules?: Rule[], fetchImpl?: typeof fetch, attempts?: number, retryDelayMs?: number, concurrency?: number, timeoutMs?: number, cap?: number}} options
 * @returns {Promise<{failures: Failure[], checked: number, retried: number, control: {ok: boolean, reason: string|null}}>}
 */
export async function run({
  base,
  probes,
  fetchImpl = fetch,
  attempts = 3,
  retryDelayMs = 15000,
  concurrency = 8,
  timeoutMs = 20000,
  cap = DYNAMIC_RULE_CAP,
  rules = [],
}) {
  const cfg = { fetchImpl, timeoutMs };
  /** @type {Map<string, Answer>} only SUCCESSFUL answers are kept: a retry must re-ask a failure */
  const targets = new Map();
  /** @param {string} p */
  const targetAnswer = async (p) => {
    const kept = targets.get(p);
    if (kept) return kept;
    const a = await get(base, p, cfg);
    if (!a.error && a.status === 200) targets.set(p, a);
    return a;
  };

  // Both are read off the same filtered list deriveProbes() numbers its positions
  // from, so "rule 109" means the same rule here and in the probe.
  const live = rules.filter((r) => r.status === "200");
  const first = live.findIndex((r) => isDynamic(r.from));
  const budgetEnd = first === -1 ? Infinity : first + cap; // 0-based index into `live`
  const ruleIndex = new Map(live.map((r, i) => [r.from, i]));

  let retried = 0;
  /** @type {Failure[]} */
  const failures = [];
  const queue = [...probes];
  const worker = async () => {
    for (let probe = queue.shift(); probe; probe = queue.shift()) {
      let problem = null;
      for (let attempt = 1; attempt <= attempts; attempt++) {
        const [answer, tAnswer] = await Promise.all([
          get(base, probe.url, cfg),
          probe.url === probe.target || !probe.baseline ? Promise.resolve(null) : targetAnswer(probe.target),
        ]);
        problem = judge(probe, answer, tAnswer);
        if (!problem) break;
        if (attempt < attempts) {
          retried += 1;
          await sleep(retryDelayMs);
        }
      }
      if (problem) {
        const idx = ruleIndex.get(probe.rule);
        failures.push({ ...probe, problem, beyondBudget: idx !== undefined && idx >= budgetEnd });
      }
    }
  };
  await Promise.all(Array.from({ length: Math.max(1, concurrency) }, worker));

  const c = await get(base, CONTROL_PATH, cfg);
  const control = c.error
    ? { ok: false, reason: `the control request failed: ${c.error}` }
    : c.status === 404
      ? { ok: true, reason: null }
      : {
          ok: false,
          reason:
            `the control path ${CONTROL_PATH} matches no rule and must answer 404, but answered HTTP ${c.status}. ` +
            "Either the site answers everything, or something (a challenge page, a proxy) is in front of this runner: " +
            "in both cases a green above this line proves nothing.",
        };
  failures.sort((a, b) => a.url.localeCompare(b.url));
  return { failures, checked: probes.length, retried, control };
}

// ── the command line ────────────────────────────────────────────────────────────

function parseArgs(argv, env) {
  const args = {
    base: env.LIVE_BASE_URL || PRODUCTION_URL,
    rulesFile: DEFAULT_RULES_FILE,
    attempts: 3,
    retryDelayMs: 15000,
    concurrency: 8,
    timeoutMs: 20000,
    list: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    if (a === "--base-url") args.base = next();
    else if (a === "--rules") args.rulesFile = next();
    else if (a === "--attempts") args.attempts = Number(next());
    else if (a === "--retry-delay-ms") args.retryDelayMs = Number(next());
    else if (a === "--concurrency") args.concurrency = Number(next());
    else if (a === "--timeout-ms") args.timeoutMs = Number(next());
    else if (a === "--list") args.list = true;
    else throw new Error(`unknown argument ${a}`);
  }
  args.base = args.base.replace(/\/+$/, "");
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2), process.env);
  const rules = parseRules(fs.readFileSync(args.rulesFile, "utf8"));
  const { probes, dead, uncovered, misrouted } = deriveProbes(rules);

  console.log(`live redirects: ${args.base}`);
  console.log(
    `  ${rules.length} rules in the file · Cloudflare counts ${cloudflareDynamicCount(rules)} of ${DYNAMIC_RULE_CAP} dynamic · ${probes.length} URLs to ask`,
  );
  for (const d of dead) {
    console.log(`  note: ${d.rule} can never fire — ${d.shadowedBy ? `${d.shadowedBy} claims its URLs first` : "no rule matches its own sample"} (not requested)`);
  }
  for (const u of uncovered) console.log(`  note: ${u} has no real page it is the first rule to claim (not requested)`);
  for (const m of misrouted) {
    console.log(`  known file defect (not requested — held by check-live-redirects.test.ts): ${m.url} goes to ${m.got ?? "no rule at all"}${m.rule ? ` via ${m.rule}` : ""}, not ${m.want}`);
  }

  if (args.list) {
    for (const p of probes) console.log(`${p.kind.padEnd(10)} ${p.url}  ->  ${p.target}   [rule ${p.position}: ${p.rule}]`);
    return;
  }
  if (probes.length === 0) {
    console.error("::error::no probes were derived — the rule file is empty or unreadable, and a check that asks nothing passes everything.");
    process.exitCode = 1;
    return;
  }

  const result = await run({ base: args.base, probes, rules, ...args });
  const github = process.env.GITHUB_ACTIONS === "true";
  for (const f of result.failures) {
    const where = f.beyondBudget
      ? ` — rule ${f.position} is PAST Cloudflare's ${DYNAMIC_RULE_CAP}-dynamic-rule cap, so Cloudflare dropped it`
      : "";
    const line = `${f.url} (rule ${f.position}: ${f.rule}) ${f.problem}${where}`;
    console.log(github ? `::error title=Live redirect broken::${line}` : `FAIL ${line}`);
  }
  if (!result.control.ok) {
    console.log(github ? `::error title=Live redirect control::${result.control.reason}` : `FAIL control: ${result.control.reason}`);
  }
  const passed = result.checked - result.failures.length;
  console.log(
    `${passed}/${result.checked} URLs answered correctly · ${result.retried} retried · control ${result.control.ok ? "404 as required" : "FAILED"}`,
  );

  if (process.env.GITHUB_STEP_SUMMARY) {
    const rows = result.failures.slice(0, 50).map((f) => `| \`${f.url}\` | \`${f.rule}\` | ${f.problem.replace(/\|/g, "\\|")} |`);
    fs.appendFileSync(
      process.env.GITHUB_STEP_SUMMARY,
      [
        `### Live redirects — ${args.base}`,
        `${passed}/${result.checked} URLs correct · ${result.retried} retried · control ${result.control.ok ? "ok" : "FAILED"}`,
        ...(rows.length ? ["", "| URL | rule | problem |", "|---|---|---|", ...rows] : []),
        "",
      ].join("\n"),
    );
  }
  if (result.failures.length > 0 || !result.control.ok) process.exitCode = 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch((err) => {
    console.error(err);
    process.exitCode = 1;
  });
}
