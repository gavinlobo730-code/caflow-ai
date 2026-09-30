// A screen recording sent to a monitoring tool must not contain a picture of a
// client's invoice (SECURITY-PRIVACY-36).
//
// `sentry.client.config.ts` set `maskAllText: true` and `blockAllMedia: false`.
// Text masking does nothing for pixels: a scanned bill or bank statement shown
// on the extraction screen is an <img>/<object>/<embed>, and with media
// blocking off the picture itself is recorded and uploaded to a third party.
// The same file traced every request (`tracesSampleRate: 1.0`) and recorded one
// session in ten at random.
//
// ⚠️ THE CONFIG IS NOT LOADED TODAY, which is worth saying before anyone reads
// this as a live leak being closed: next.config.mjs has no `withSentryConfig` and
// there is no `instrumentation-client.ts`, so the browser SDK never initialises.
// What this pins is the state the file is in on the day somebody wires it up —
// the settings a sub-processor gets handed — and it is asserted as a RULE over
// the tree, not over one path:
//
//   1. the replay integration blocks media and masks text and inputs;
//   2. nothing is traced, ordinary sessions are not recorded, and a replay is
//      kept only around an error, at a bounded rate;
//   3. no `sendDefaultPii: true` anywhere;
//   4. every `Sentry.init` / replay integration in apps/web is one of the two
//      audited files. A second init in a component would carry its own
//      settings and walk round the first three, which is the way a guard on one
//      file stops meaning anything; canvas capture is refused outright because
//      it records pixels that `blockAllMedia` does not cover.
//
// Run with: node --experimental-strip-types --test scripts/a-session-replay-does-not-record-what-is-on-screen.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel"]);

const AUDITED = ["sentry.client.config.ts", "sentry.edge.config.ts"];
const read = (name: string) => stripComments(fs.readFileSync(path.join(WEB, name), "utf8"));

/** The raw text of `key: <value>` for every occurrence of `key` in `src`. A
 *  value is an array literal or runs to the next comma, newline or brace. */
function valuesOf(src: string, key: string): string[] {
  const re = new RegExp(`\\b${key}\\s*:\\s*(\\[[^\\]]*\\]|[^,\\n}]+)`, "g");
  return [...src.matchAll(re)].map((m) => m[1].trim());
}

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (SKIP.has(e.name)) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(tsx?|mjs|js)$/.test(e.name) && !e.name.includes(".test.")) out.push(p);
    }
  };
  for (const folder of ["app", "components", "lib", "hooks", "scripts"]) {
    const dir = path.join(WEB, folder);
    if (fs.existsSync(dir)) walk(dir);
  }
  for (const top of fs.readdirSync(WEB)) {
    if (/\.(tsx?|mjs|js)$/.test(top) && !top.includes(".test.")) out.push(path.join(WEB, top));
  }
  return out;
}

test("the premise: the client config holds one replay integration and one init", () => {
  const src = read("sentry.client.config.ts");
  assert.equal((src.match(/Sentry\.init\(/g) ?? []).length, 1);
  assert.equal((src.match(/replayIntegration\(/g) ?? []).length, 1);
});

test("replay blocks media and masks text and inputs", () => {
  const src = read("sentry.client.config.ts");
  for (const [key, want] of [
    ["blockAllMedia", "true"],
    ["maskAllText", "true"],
    ["maskAllInputs", "true"],
  ] as const) {
    const values = valuesOf(src, key);
    assert.ok(values.length > 0, `${key} must be written out, not left to a default`);
    assert.deepEqual(values, values.map(() => want), `${key} must be ${want}`);
  }
});

test("replay does not capture request or response bodies", () => {
  const src = read("sentry.client.config.ts");
  const bodies = valuesOf(src, "networkCaptureBodies");
  assert.ok(bodies.length > 0, "networkCaptureBodies must be stated");
  assert.ok(bodies.every((v) => v === "false"), "a body is the API's JSON, which is the ledger");
  const allow = valuesOf(src, "networkDetailAllowUrls");
  assert.ok(allow.length > 0, "networkDetailAllowUrls must be stated");
  assert.ok(allow.every((v) => v.replace(/\s/g, "") === "[]"), "no URL may be allow-listed for network detail");
});

test("nothing is traced, sessions are not recorded, an error replay is bounded", () => {
  for (const file of AUDITED) {
    const traces = valuesOf(read(file), "tracesSampleRate");
    assert.ok(traces.length > 0, `${file} must state tracesSampleRate`);
    assert.ok(traces.every((v) => Number(v) === 0), `${file}: tracesSampleRate must be 0, got ${traces}`);
  }
  const src = read("sentry.client.config.ts");
  const session = valuesOf(src, "replaysSessionSampleRate");
  assert.ok(session.length > 0, "replaysSessionSampleRate must be stated");
  assert.ok(session.every((v) => Number(v) === 0), `ordinary sessions must not be recorded, got ${session}`);
  const onError = valuesOf(src, "replaysOnErrorSampleRate");
  assert.ok(onError.length > 0, "replaysOnErrorSampleRate must be stated");
  assert.ok(
    onError.every((v) => Number(v) > 0 && Number(v) <= 0.25),
    `an error replay is kept at a bounded rate (0, 0.25], got ${onError}`,
  );
});

test("no init turns default PII on, and each states it", () => {
  for (const file of AUDITED) {
    const pii = valuesOf(read(file), "sendDefaultPii");
    assert.ok(pii.length > 0, `${file} must state sendDefaultPii`);
    assert.ok(pii.every((v) => v === "false"), `${file}: sendDefaultPii must be false`);
  }
});

test("every Sentry init and replay integration is in an audited file, and canvas capture is nowhere", () => {
  const offenders: string[] = [];
  const canvas: string[] = [];
  for (const file of sourceFiles()) {
    const rel = path.relative(WEB, file);
    if (rel.startsWith(`scripts${path.sep}`)) continue; // this guard and its siblings name the calls in prose and regexes
    const src = stripComments(fs.readFileSync(file, "utf8"));
    if (/replayCanvasIntegration\s*\(/.test(src)) canvas.push(rel);
    const inits = /Sentry\.init\s*\(|\bsentryInit\s*\(|\breplayIntegration\s*\(|new\s+Replay\s*\(/.test(src);
    if (inits && !AUDITED.includes(rel)) offenders.push(rel);
  }
  assert.deepEqual(canvas, [], "canvas capture records pixels blockAllMedia does not cover");
  assert.deepEqual(
    offenders,
    [],
    "a Sentry init outside the audited files carries its own settings and walks round this guard",
  );
});
