// The live redirect check asks the right URLs, reads the answers honestly, and fails when it should (ops-25).
// Run with: node --experimental-strip-types --test scripts/check-live-redirects.test.ts
//
// WHAT CANNOT BE TESTED HERE, SAID FIRST
//   Whether Cloudflare behaves the way the model in check-live-redirects.mjs says
//   it does is a fact about Cloudflare. It was measured against the production
//   site when the check was written (207 of 207 URLs answered, and the four
//   bare-`.txt` rules it calls dead answered HTML where an RSC payload was
//   wanted), and it is re-measured every time the workflow runs. What these tests
//   pin is everything AROUND that model: which URLs are derived from the file,
//   what counts as a failure, and that a site which dropped rules, served the
//   wrong page, redirected, answered everything, or was down comes back RED.
//
//   The server below is an emulation of Cloudflare's rules — first match wins, a
//   rewrite is not re-evaluated, the tail past the 100-dynamic cap is dropped
//   without a word — so a test can put the 30-09-2026 incident in front of the
//   checker and watch it say so.
//
// NEGATIVE CONTROLS — each applied to check-live-redirects.mjs, measured, reverted:
//
//   | control                                                             | tests that fail |
//   |---------------------------------------------------------------------|-----------------|
//   | drop the body comparison in judge()                                 | 1               |
//   | compare bodies where the target is claimed by another rule          | 6               |
//   | stop reporting 3xx as a failure                                     | 1               |
//   | accept any control answer, not only 404                             | 1               |
//   | never retry                                                         | 1               |
//   | `:name` stops matching dots (the model's own premise)               | 3               |
//   | stop checking the content type                                      | 1               |
//   | stop labelling a failure as past the cap                            | 1               |
//
// And against the PRODUCTION site, by hand: the real file asked 207 URLs and got
// 207 right; the same file with one extra page the site does not have (what a
// dropped or undeployed rule looks like from outside) came back 207/210 with
// exactly that rule's three URLs red, naming the rule.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import type { AddressInfo } from "node:net";
import { fileURLToPath } from "node:url";
import {
  CONTROL_PATH,
  PRODUCTION_URL,
  cloudflareDynamicCount,
  compile,
  deriveProbes,
  parseRules,
  resolve,
  rewrite,
  rulesCloudflareKeeps,
  run,
} from "./check-live-redirects.mjs";
import { buildRedirectsFile } from "./generate-redirects.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REDIRECTS = path.join(HERE, "..", "public", "_redirects");
const WORKFLOW = path.join(HERE, "..", "..", "..", ".github", "workflows", "live-redirects.yml");
const committed = parseRules(fs.readFileSync(REDIRECTS, "utf8"));

type Rule = { from: string; to: string; status: string; line: number };
const rule = (from: string, to: string): Rule => ({ from, to, status: "200", line: 0 });

// ── the matcher ────────────────────────────────────────────────────────────────

test("a placeholder is one run of non-slash characters, dots included", () => {
  assert.ok(compile("/clients/:id").test("/clients/abc"));
  assert.ok(!compile("/clients/:id").test("/clients/abc/"), "a trailing slash is significant");
  assert.ok(!compile("/clients/:id").test("/clients/a/b"));
  // The fact the whole dead-rule analysis rests on, measured live: `:id` swallows ".txt".
  assert.ok(compile("/clients/:id").test("/clients/probe.txt"));
  assert.ok(compile("/clients/:id.txt").test("/clients/probe.txt"));
});

test("a splat matches anything after its prefix, the empty string included, and fills :splat", () => {
  const r = rule("/clients/:id/*", "/clients/_placeholder/:splat");
  assert.equal(rewrite(r, "/clients/x/accounting/"), "/clients/_placeholder/accounting/");
  assert.equal(rewrite(r, "/clients/x/"), "/clients/_placeholder/");
  assert.equal(rewrite(r, "/health/x/"), null);
});

test("regex metacharacters in a rule are literal: the dot of .txt is not 'any character'", () => {
  assert.ok(!compile("/clients/documents.txt").test("/clients/documentsXtxt"));
  assert.ok(compile("/clients/documents.txt").test("/clients/documents.txt"));
});

test("the first rule in file order wins", () => {
  const rules = [rule("/a/:x", "/first/"), rule("/a/b", "/second/")];
  assert.equal(resolve(rules, "/a/b")?.target, "/first/");
});

test("Cloudflare counts from the first dynamic rule to the end, and keeps only the cap", () => {
  const lit = (n: number) => Array.from({ length: n }, (_, i) => rule(`/lit${i}`, `/lit${i}/`));
  const dyn = (n: number) => Array.from({ length: n }, (_, i) => rule(`/d/:x/p${i}`, `/d/_placeholder/p${i}/`));
  const rules = [...lit(5), ...dyn(3), ...lit(4)];
  assert.equal(cloudflareDynamicCount(rules), 7, "the literals AFTER the first dynamic rule count too");
  assert.equal(rulesCloudflareKeeps(rules, 4).length, 5 + 4);
});

// ── what is derived from the committed file ─────────────────────────────────────

test("the committed file yields real probes, and no rule is silently left unexercised", () => {
  const { probes, dead, uncovered } = deriveProbes(committed);
  assert.ok(probes.length > 150, `only ${probes.length} URLs derived from ${committed.length} rules`);
  const deadRules = new Set(dead.map((d) => d.rule));
  const probed = new Set(probes.map((p) => p.rule));
  const unexercised = committed.map((r) => r.from).filter((f) => !probed.has(f) && !deadRules.has(f));
  assert.deepEqual(unexercised, [], "a rule with no probe and not named dead is one the check never asks about");
  assert.deepEqual(uncovered, [], "a splat with no real page it is first to claim is one nothing exercises");
});

test("a dead rule is a bare .txt rule its own bare sibling claims first — and no other kind appears", () => {
  // Structure, not a list of four names: a NEW dead rule of any other shape is a
  // rule the generator is spending budget on that can never fire, and fails here.
  const { dead } = deriveProbes(committed);
  assert.ok(dead.length > 0, "the committed file has bare-.txt rules shadowed by `:id` — none found means the model changed");
  for (const d of dead) {
    assert.ok(d.rule.endsWith(".txt"), `${d.rule} is dead for a reason other than .txt`);
    assert.equal(d.shadowedBy, d.rule.slice(0, -".txt".length), `${d.rule} is shadowed by something unexpected`);
  }
});

test("the ONE known file defect is held exactly, so a second one fails and a fix must delete this entry", () => {
  // `/clients/:id/year-end/index.txt` — the RSC payload of the year-end landing
  // page — is claimed by `/clients/:id/year-end/:engagementId`, which matches
  // "index.txt" as an engagement id. Measured live: the URL answers text/html (the
  // engagement page), not the payload, so client-side navigation to year-end falls
  // back to a full page load. Not a 404, not this finding's to fix (it changes the
  // generator and the 98-rule budget), and NAMED here rather than left to a red run.
  const { misrouted } = deriveProbes(committed);
  assert.deepEqual(
    misrouted.map((m) => ({ url: m.url, rule: m.rule })),
    [{ url: "/clients/probe/year-end/index.txt", rule: "/clients/:id/year-end/:engagementId" }],
  );
});

test("a file the generator writes for a tree with static siblings has nothing misrouted or uncovered", () => {
  // The check must hold for the generator's shape and not only for today's file.
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "live-redirects-"));
  try {
    const mk = (...segs: string[]) => {
      const dir = path.join(tmp, ...segs);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "page.tsx"), "export default function P() { return null; }");
    };
    mk("clients", "[id]");
    mk("clients", "[id]", "overview");
    mk("clients", "[id]", "sales", "invoices", "[invoiceId]", "edit");
    mk("clients", "[id]", "sales", "invoices", "new");
    mk("clients", "documents");
    mk("health", "[client_id]");
    mk("health", "critical");
    const { misrouted, uncovered, probes } = deriveProbes(parseRules(buildRedirectsFile(tmp)));
    assert.deepEqual(misrouted, []);
    assert.deepEqual(uncovered, []);
    assert.ok(probes.length > 20);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

// ── an emulated Cloudflare, and the checker against it ──────────────────────────

type Reply = { status: number; type?: string; body?: string; location?: string };
type Hook = (pathname: string, count: number) => Reply | undefined;

/** Every file that exists: what the rules point at, in both shapes. */
function filesFor(rules: Rule[]): Set<string> {
  const files = new Set<string>();
  for (const r of rules) {
    if (r.to.includes(":splat")) continue;
    files.add(r.to);
    if (r.to.endsWith("/")) files.add(`${r.to}index.txt`);
  }
  return files;
}

async function emulate(kept: Rule[], files: Set<string>, hook: Hook = () => undefined) {
  const seen = new Map<string, number>();
  const server = http.createServer((req, res) => {
    const pathname = new URL(req.url ?? "/", "http://x").pathname;
    const count = (seen.get(pathname) ?? 0) + 1;
    seen.set(pathname, count);
    let reply = hook(pathname, count);
    if (!reply) {
      // A rewrite is answered in place and is NOT re-evaluated; with no rule the
      // path itself must be a file.
      const hit = resolve(kept, pathname);
      const served = hit ? hit.target : pathname;
      reply = files.has(served)
        ? { status: 200, type: served.endsWith(".txt") ? "text/plain" : "text/html", body: `file:${served}` }
        : { status: 404, type: "text/html", body: "not found" };
    }
    res.writeHead(reply.status, {
      "content-type": reply.type ?? "text/html",
      ...(reply.location ? { location: reply.location } : {}),
    });
    res.end(reply.body ?? "");
  });
  await new Promise<void>((ok) => server.listen(0, "127.0.0.1", ok));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return {
    base,
    seen,
    close: () => new Promise<void>((ok) => { server.closeAllConnections(); server.close(() => ok()); }),
  };
}

const FAST = { attempts: 1, retryDelayMs: 0, timeoutMs: 2000 } as const;

test("a site that serves the committed file faithfully is green, control included", async () => {
  const site = await emulate(committed, filesFor(committed));
  try {
    const { probes } = deriveProbes(committed);
    const out = await run({ base: site.base, probes, rules: committed, ...FAST });
    assert.deepEqual(out.failures.map((f: { url: string; problem: string }) => `${f.url}: ${f.problem}`), []);
    assert.equal(out.control.ok, true);
    assert.equal(out.checked, probes.length);
  } finally {
    await site.close();
  }
});

test("the year-end .txt rule is not failed for a target another rule claims — its baseline is not fair", async () => {
  // `/clients/:id/year-end.txt` rewrites to `.../year-end/index.txt`, which a
  // DIRECT fetch returns as a different page (the engagement one) because another
  // rule claims that path. Comparing the two would fail a rule that works; the
  // content type still has to be right.
  const { probes } = deriveProbes(committed);
  const yearEnd = probes.find((p: { url: string }) => p.url === "/clients/probe/year-end.txt");
  assert.ok(yearEnd, "the year-end.txt rule is probed");
  assert.equal(yearEnd.baseline, false);
  const fair = probes.filter((p: { baseline: boolean }) => p.baseline).length;
  assert.ok(fair > probes.length * 0.9, "almost every probe has a fair baseline; losing it widely would hollow the check out");
});

test("THE 30-09-2026 INCIDENT: a file over the cap comes back red, every failure past the cap, none before it", async () => {
  // 32 literal rules interleaved among the dynamic ones: Cloudflare counts 98+32
  // = 130 against a cap of 100 and drops the last 30 — the splats among them.
  const first = committed.findIndex((r) => r.from.includes(":") || r.from.includes("*"));
  const extras = Array.from({ length: 32 }, (_, i) => rule(`/extra/leaf${i}`, `/extra/leaf${i}/`));
  const overBudget = [...committed.slice(0, first + 1), ...extras, ...committed.slice(first + 1)];
  assert.equal(cloudflareDynamicCount(overBudget), 98 + 32);
  const kept = rulesCloudflareKeeps(overBudget);
  assert.equal(overBudget.length - kept.length, 30);

  const site = await emulate(kept, filesFor(overBudget));
  try {
    const { probes } = deriveProbes(overBudget);
    const out = await run({ base: site.base, probes, rules: overBudget, ...FAST });
    assert.ok(out.failures.length > 0, "a site that dropped thirty rules was reported green");
    assert.ok(
      out.failures.every((f: { beyondBudget: boolean }) => f.beyondBudget),
      "a rule INSIDE the cap was reported broken, or one past it was not labelled as dropped",
    );
    const droppedSplats = overBudget.slice(kept.length).filter((r) => r.from.endsWith("/*")).map((r) => r.from);
    assert.ok(droppedSplats.length > 0, "the incident dropped splats");
    for (const s of droppedSplats) {
      assert.ok(out.failures.some((f: { rule: string }) => f.rule === s), `no failure for the dropped splat ${s}`);
    }
    assert.equal(out.control.ok, true);
  } finally {
    await site.close();
  }
});

test("a 200 with the WRONG PAGE is a failure — the shape a status code cannot see", async () => {
  // The generator's own header records this: `/health/critical` answered with
  // `/health/[client_id]`'s bundle, status 200.
  const site = await emulate(committed, filesFor(committed), (p) =>
    p === "/health/critical" ? { status: 200, type: "text/html", body: "file:/health/_placeholder/" } : undefined);
  try {
    const { probes } = deriveProbes(committed);
    const out = await run({ base: site.base, probes, rules: committed, ...FAST });
    assert.equal(out.failures.length, 1);
    assert.equal(out.failures[0].rule, "/health/critical");
    assert.match(out.failures[0].problem, /DIFFERENT page/);
  } finally {
    await site.close();
  }
});

test("an RSC request answered with HTML is a failure, by content type", async () => {
  const site = await emulate(committed, filesFor(committed), (p) =>
    p === "/clients/probe/accounting.txt" ? { status: 200, type: "text/html", body: "file:/clients/_placeholder/accounting/" } : undefined);
  try {
    const { probes } = deriveProbes(committed);
    const out = await run({ base: site.base, probes, rules: committed, ...FAST });
    assert.equal(out.failures.length, 1);
    assert.match(out.failures[0].problem, /text\/html, where .* is text\/plain/);
  } finally {
    await site.close();
  }
});

test("a redirect is a failure: a bare path that bounces has put the placeholder in the address bar", async () => {
  const site = await emulate(committed, filesFor(committed), (p) =>
    p === "/clients/probe/accounting"
      ? { status: 308, location: "/clients/_placeholder/accounting/" }
      : undefined);
  try {
    const { probes } = deriveProbes(committed);
    const out = await run({ base: site.base, probes, rules: committed, ...FAST });
    assert.equal(out.failures.length, 1);
    assert.match(out.failures[0].problem, /308 redirect to \/clients\/_placeholder\/accounting\//);
  } finally {
    await site.close();
  }
});

test("a site that answers 200 to the control path is reported, because every green above it means nothing", async () => {
  const site = await emulate(committed, filesFor(committed), (p) =>
    p === CONTROL_PATH ? { status: 200, type: "text/html", body: "a catch-all" } : undefined);
  try {
    const { probes } = deriveProbes(committed);
    const out = await run({ base: site.base, probes, rules: committed, ...FAST });
    assert.equal(out.control.ok, false);
    assert.match(out.control.reason ?? "", /must answer 404, but answered HTTP 200/);
  } finally {
    await site.close();
  }
});

test("a site that is down is red on every URL and on the control, never green", async () => {
  const dead = http.createServer();
  await new Promise<void>((ok) => dead.listen(0, "127.0.0.1", ok));
  const base = `http://127.0.0.1:${(dead.address() as AddressInfo).port}`;
  await new Promise<void>((ok) => dead.close(() => ok())); // the port is now refusing
  const { probes } = deriveProbes(committed);
  const out = await run({ base, probes, rules: committed, ...FAST });
  assert.equal(out.failures.length, probes.length);
  assert.equal(out.control.ok, false);
  assert.match(out.failures[0].problem, /the request failed/);
});

test("a transient failure is retried and passes; a persistent one fails after the last attempt", async () => {
  const flaky = await emulate(committed, filesFor(committed), (p, n) =>
    p === "/clients/probe/accounting" && n <= 2 ? { status: 503, type: "text/html", body: "busy" } : undefined);
  try {
    const { probes } = deriveProbes(committed);
    const out = await run({ base: flaky.base, probes, rules: committed, attempts: 3, retryDelayMs: 0, timeoutMs: 2000 });
    assert.deepEqual(out.failures, [], "two 503s then a 200 must not page anybody");
    assert.equal(out.retried, 2);
  } finally {
    await flaky.close();
  }

  const broken = await emulate(committed, filesFor(committed), (p) =>
    p === "/clients/probe/accounting" ? { status: 404, type: "text/html", body: "not found" } : undefined);
  try {
    const { probes } = deriveProbes(committed);
    const out = await run({ base: broken.base, probes, rules: committed, attempts: 3, retryDelayMs: 0, timeoutMs: 2000 });
    assert.equal(out.failures.length, 1, "a rule that stays broken stays reported");
    assert.equal(out.retried, 2);
    assert.equal(broken.seen.get("/clients/probe/accounting"), 3, "asked once per attempt");
  } finally {
    await broken.close();
  }
});

// ── the workflow and the address ───────────────────────────────────────────────

test("the workflow exists, runs on a schedule and on demand, and cannot hide a failure", () => {
  const raw = fs.readFileSync(WORKFLOW, "utf8");
  const code = raw.split("\n").filter((l) => !l.trimStart().startsWith("#")).join("\n");
  assert.match(code, /^\s*schedule:/m);
  assert.match(code, /^\s*workflow_dispatch:/m);
  assert.match(code, /run:\s*node apps\/web\/scripts\/check-live-redirects\.mjs\s*$/m);
  assert.doesNotMatch(code, /continue-on-error/, "a check that cannot fail the job checks nothing");
  // CLAUDE.md: a path-filtered workflow does not run when the filter misses. This
  // is not a required check, but a redirect regression arrives with a change to
  // NOTHING under apps/web/public — a Cloudflare deploy or a page added elsewhere.
  assert.doesNotMatch(code, /^\s*paths(-ignore)?:/m);
});

test("the default host is the PRODUCT's Cloudflare project, not the marketing site's", () => {
  // `practicesync.pages.dev` is apps/marketing, a different project: probing it
  // with the product's rules would fail every URL for a reason that is not a bug.
  assert.equal(PRODUCTION_URL, "https://caflow-ai.pages.dev");
  const code = fs.readFileSync(WORKFLOW, "utf8").split("\n").filter((l) => !l.trimStart().startsWith("#")).join("\n");
  assert.doesNotMatch(code, /practicesync\.pages\.dev/);
});
