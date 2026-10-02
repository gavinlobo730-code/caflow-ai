// The product site and the marketing site send security headers, the Content-Security-Policy names exactly the
// hosts the code talks to, and nothing in the code needs what the policy forbids (security_privacy-05).
// Run with: node --experimental-strip-types --test scripts/the-sites-send-security-headers.test.ts
//
// THE FINDING
//     No Content-Security-Policy, HSTS, X-Frame-Options, X-Content-Type-Options or Referrer-Policy anywhere: no
//     `_headers` file in either app's public/, no headers() in next.config.mjs (ignored under `output: "export"`
//     anyway). Add a Cloudflare Pages `_headers` for both sites with frame-ancestors 'none', object-src 'none',
//     base-uri 'self', a connect-src allowlist (API, Supabase, Sentry), nosniff, Referrer-Policy and
//     Permissions-Policy. Static export needs inline scripts, so script-src needs 'unsafe-inline'.
//
// WHAT THIS HOLDS, AS RULES
//   * the generator's own contract: only a real http(s) origin ever reaches the header (a `;` smuggled through a
//     hostname would end a directive and start another), a missing REQUIRED host is named and omitted and never
//     guessed, a wildcard is never written into connect-src, and a line that Cloudflare would ignore for being
//     over 2,000 characters fails the build instead;
//   * SECURITY_CSP_MODE is the way back: enforce, report-only (the other header NAME, and nothing enforced),
//     off, and an unrecognisable value is read as unset;
//   * what production will send, given the configuration production declares: wrangler.toml's API and Supabase
//     URLs are exactly what connect-src names — so a rename of either host moves the policy with it;
//   * the build runs the generator AFTER `next build` in EVERY script that runs `next build`, in both apps,
//     because next build empties out/ and a script that forgot would ship no headers and say nothing;
//   * there is no hand-written `_headers` in either public/, which the generator would silently overwrite;
//   * the policy and the code agree, derived from the tree and not from a list of today's files: nothing in
//     apps/web opens a socket, an event stream, a worker, a beacon or a Realtime channel (each needs a
//     directive this policy does not grant), every iframe is a sandboxed srcdoc (which is why frame-src is
//     'none'), nothing uses eval or `new Function`, and none of the features Permissions-Policy switches off is
//     used. Each failure says what to change in the generator.
//
// NEGATIVE CONTROLS — each applied, then reverted:
//
//   | control                                                                   | fails |
//   |---------------------------------------------------------------------------|-------|
//   | contentSecurityPolicy: put "*.onrender.com" in connect-src                | 1     |
//   | originOf: return url.origin without the shape test                        | 1     |
//   | remove the generator from package.json's "pages:build"                    | 1     |
//   | add `new WebSocket(` to a component                                       | 1     |
//   | add a public/_headers                                                     | 1     |
//
// NOT HELD HERE: that Cloudflare applies the file (scripts/check-live-headers.mjs asks the live site), that the
// product renders under the policy (scripts/smoke-walk.mjs applies out/_headers and fails on a violation), and
// anything about the marketing app's own build, which has no test runner (the Python side reads its script).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_CSP_MODE,
  HSTS,
  MAX_LINE,
  PERMISSIONS_POLICY,
  REFERRER_POLICY,
  buildHeadersFile,
  connectSources,
  contentSecurityPolicy,
  cspMode,
  headersFor,
  originOf,
  parseHeadersFile,
  patternMatches,
} from "./security-headers.mjs";
import { assessHeaders, REQUIRED } from "./check-live-headers.mjs";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = path.join(WEB, "..", "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

const API = "https://practicesync-api.onrender.com";
const SUPABASE = "https://abcdefghij.supabase.co";
const SENTRY = "https://o123.ingest.sentry.io";

function directive(csp: string, name: string): string[] {
  const found = csp.split(";").map((d) => d.trim()).find((d) => d.startsWith(name + " "));
  assert.ok(found, `no ${name} directive in: ${csp}`);
  return found.split(/\s+/).slice(1);
}

// ═══ origins ═════════════════════════════════════════════════════════════════

test("an origin is scheme, host and port and nothing else", () => {
  assert.equal(originOf("https://practicesync-api.onrender.com/api/x?y=1#z"), API);
  assert.equal(originOf("  https://abcdefghij.supabase.co/  "), SUPABASE);
  assert.equal(originOf("http://127.0.0.1:4319/__api"), "http://127.0.0.1:4319");
  assert.equal(originOf("https://example.com:443/"), "https://example.com", "the default port is not written");
  assert.equal(originOf("https://abc123@o123.ingest.sentry.io/456"), SENTRY, "a DSN reduces to its ingest origin");
});

test("what is not an http(s) origin is refused, and nothing that could end a directive gets through", () => {
  for (const bad of [
    "", "   ", undefined, null, "not a url", "ftp://example.com", "javascript:alert(1)", "data:text/html,x",
    "https://a.com; script-src *", "https://a.com;b.com", "https://a.com,b.com", "https://a.com'b",
    "https://[::1]:8000",
  ]) {
    assert.equal(originOf(bad), null, `${JSON.stringify(bad)} must not become a source`);
  }
});

test("connect-src is derived from the three build values, deduped, and a missing REQUIRED one is named", () => {
  assert.deepEqual(
    connectSources({ apiUrl: API, supabaseUrl: SUPABASE, sentryDsn: "https://k@o123.ingest.sentry.io/9" }),
    { origins: [API, SUPABASE, SENTRY], missing: [] },
  );
  assert.deepEqual(connectSources({ apiUrl: API, supabaseUrl: API }).origins, [API], "one origin is listed once");
  assert.deepEqual(connectSources({ apiUrl: API }).missing, ["NEXT_PUBLIC_SUPABASE_URL"]);
  assert.deepEqual(connectSources({ supabaseUrl: SUPABASE }).missing, ["NEXT_PUBLIC_API_URL"]);
  // Sentry is optional: with no DSN the tracker never starts, so its absence is not a gap.
  assert.deepEqual(connectSources({ apiUrl: API, supabaseUrl: SUPABASE }).missing, []);
});

// ═══ the policy ══════════════════════════════════════════════════════════════

test("the policy has the directives the finding asks for, at their strictest values", () => {
  const csp = contentSecurityPolicy({ connectOrigins: [API, SUPABASE] });
  assert.deepEqual(directive(csp, "frame-ancestors"), ["'none'"]);
  assert.deepEqual(directive(csp, "object-src"), ["'none'"]);
  assert.deepEqual(directive(csp, "base-uri"), ["'self'"]);
  assert.deepEqual(directive(csp, "form-action"), ["'self'"]);
  assert.deepEqual(directive(csp, "default-src"), ["'self'"]);
  assert.deepEqual(directive(csp, "connect-src"), ["'self'", API, SUPABASE]);
});

test("no source in connect-src is a wildcard or a bare scheme: a host anybody can register defeats the directive", () => {
  const csp = contentSecurityPolicy({ connectOrigins: [API, SUPABASE, SENTRY] });
  for (const source of directive(csp, "connect-src")) {
    assert.ok(source === "'self'" || /^https?:\/\/[A-Za-z0-9.-]+(:\d+)?$/.test(source), `connect-src names ${source}`);
    assert.ok(!source.includes("*"), `connect-src names a wildcard: ${source}`);
  }
});

test("script-src carries 'unsafe-inline' because a static export needs it, and no 'unsafe-eval'", () => {
  const csp = contentSecurityPolicy({ connectOrigins: [API] });
  const script = directive(csp, "script-src");
  assert.ok(script.includes("'unsafe-inline'"), "the Next bootstrap and flight payload are inline scripts");
  assert.ok(!csp.includes("unsafe-eval"), "the production bundle contains no eval and no new Function");
  assert.ok(!script.some((s) => s === "*" || s.startsWith("http")), "no script host");
});

test("https: is allowed for images only, because a firm's logo is a URL a person recorded", () => {
  const csp = contentSecurityPolicy({ connectOrigins: [API] });
  assert.ok(directive(csp, "img-src").includes("https:"));
  const others = csp.split(";").map((d) => d.trim()).filter((d) => d && !d.startsWith("img-src"));
  assert.ok(!others.some((d) => /\bhttps?:(?!\/\/)/.test(d)), `a bare scheme outside img-src: ${others}`);
});

// ═══ the file ════════════════════════════════════════════════════════════════

test("the file carries the six headers on every path, and none of its lines is one Cloudflare would ignore", () => {
  // `mode: "enforce"`: this test is about the six headers' presence and shape, and the policy header is only
  // named `Content-Security-Policy` when it is enforced (what NOBODY having decided sends is its own test below).
  const { content } = buildHeadersFile({ apiUrl: API, supabaseUrl: SUPABASE, mode: "enforce" });
  const rules = parseHeadersFile(content);
  assert.equal(rules.length, 1);
  assert.equal(rules[0].pattern, "/*");
  const served = headersFor(rules, "/clients/anything/accounting/");
  assert.equal(served["x-content-type-options"], "nosniff");
  assert.equal(served["x-frame-options"], "DENY");
  assert.equal(served["referrer-policy"], REFERRER_POLICY);
  assert.equal(served["permissions-policy"], PERMISSIONS_POLICY);
  assert.equal(served["strict-transport-security"], HSTS);
  assert.ok(served["content-security-policy"]);
  for (const line of content.split("\n")) assert.ok(line.length <= MAX_LINE, `a ${line.length}-character line`);
});

test("Cache-Control is not touched: Pages' own default is right for a static export", () => {
  assert.ok(!/cache-control/i.test(buildHeadersFile({ apiUrl: API, supabaseUrl: SUPABASE }).content));
});

test("HSTS is 30 days and binds no other host and asks for no preload entry", () => {
  const seconds = Number(/max-age=(\d+)/.exec(HSTS)?.[1]);
  assert.ok(seconds >= 86400 && seconds <= 31536000, "30 days is the deliberate first step");
  assert.ok(!/includesubdomains/i.test(HSTS) && !/preload/i.test(HSTS));
});

test("a line over Cloudflare's limit fails the build instead of being dropped silently", () => {
  const huge = "https://" + "a".repeat(2100) + ".example.com";
  assert.throws(() => buildHeadersFile({ apiUrl: huge, supabaseUrl: SUPABASE }), /2000|characters/);
});

test("SECURITY_CSP_MODE: report-only until somebody says enforce, report-only changes the header's name, off sends none", () => {
  // Nobody having decided is ONE answer, DEFAULT_CSP_MODE, and it is report-only: the policy has not met the real
  // hosts or Safari and Firefox, and a wrong enforced policy stops sign-in silently (see the generator's header).
  for (const unread of [undefined, "", "  ", "enforced", "yes", "Report Only", "0"]) {
    assert.equal(cspMode(unread), DEFAULT_CSP_MODE, `${JSON.stringify(unread)} is read as unset`);
  }
  assert.equal(DEFAULT_CSP_MODE, "report-only");
  assert.equal(cspMode("ENFORCE"), "enforce", "enforcing is a deliberate act and is spelled out");
  assert.equal(cspMode("REPORT-ONLY"), "report-only");
  assert.equal(cspMode(" off "), "off");
  // An unset mode through the whole builder sends the REPORT-ONLY header and enforces nothing.
  const unset = buildHeadersFile({ apiUrl: API, supabaseUrl: SUPABASE }).content;
  assert.match(unset, /^ {2}Content-Security-Policy-Report-Only: /m);
  assert.ok(!/^ {2}Content-Security-Policy: /m.test(unset), "nobody having decided must not enforce");

  const env = { apiUrl: API, supabaseUrl: SUPABASE };
  const enforce = buildHeadersFile({ ...env, mode: "enforce" }).content;
  assert.match(enforce, /^ {2}Content-Security-Policy: /m);
  assert.ok(!/Report-Only/.test(enforce));

  const report = buildHeadersFile({ ...env, mode: "report-only" }).content;
  assert.match(report, /^ {2}Content-Security-Policy-Report-Only: /m);
  assert.ok(!/^ {2}Content-Security-Policy: /m.test(report), "report-only must enforce nothing");

  const off = buildHeadersFile({ ...env, mode: "off" }).content;
  assert.ok(!/Content-Security-Policy/.test(off));
  // Every other header survives the way back: a rollback of the CSP is not a rollback of nosniff.
  for (const name of ["X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy", "Strict-Transport-Security"]) {
    assert.ok(off.includes(name), `${name} must not depend on the CSP mode`);
  }
});

test("a build that could not derive a host says so in the file and still sends the rest", () => {
  const built = buildHeadersFile({ apiUrl: API });
  assert.deepEqual(built.missing, ["NEXT_PUBLIC_SUPABASE_URL"]);
  assert.match(built.content, /NOT DERIVED: NEXT_PUBLIC_SUPABASE_URL/);
  assert.ok(built.content.includes("X-Frame-Options"));
});

// ═══ the parser the walk and these tests share ═══════════════════════════════

test("the parser reads what Cloudflare reads and refuses what it does not understand", () => {
  const rules = parseHeadersFile("# c\n/a/*\n  X-A: 1\n  X-B: two: parts\n\n/a/b\n  X-A: 3\n");
  assert.deepEqual(rules[0].headers, [["X-A", "1"], ["X-B", "two: parts"]]);
  assert.equal(headersFor(rules, "/a/b")["x-a"], "1, 3", "a header named by two matching rules is comma-joined");
  assert.deepEqual(headersFor(rules, "/z"), {});
  assert.throws(() => parseHeadersFile("  X-A: 1\n"), /before any path/);
  assert.throws(() => parseHeadersFile("/x/:id\n  X-A: 1\n"), /placeholder/);
  assert.throws(() => parseHeadersFile("/x\n  ! X-A\n"), /detach/);
  assert.ok(patternMatches("/*", "/"), "/* matches the root");
  assert.ok(patternMatches("/*", "/clients/x/"));
  assert.ok(!patternMatches("/a", "/a/b"));
});

// ═══ the live check's judgement ══════════════════════════════════════════════

test("the live check fails on a missing header and tells the three CSP states apart", () => {
  const good = Object.fromEntries(REQUIRED.map((n) => [n, "x"]));
  Object.assign(good, {
    "x-content-type-options": "nosniff", "x-frame-options": "DENY", "strict-transport-security": HSTS,
  });
  assert.deepEqual(assessHeaders(good), { errors: [], csp: "none" });
  assert.equal(assessHeaders({ ...good, "content-security-policy-report-only": "default-src 'self'" }).csp, "report-only");
  assert.equal(assessHeaders({ ...good, "content-security-policy": "frame-ancestors 'none'" }).csp, "enforced");
  for (const name of REQUIRED) {
    const broken = { ...good };
    delete (broken as Record<string, string>)[name];
    assert.ok(assessHeaders(broken).errors.some((e) => e.includes(name)), `${name} missing must fail`);
  }
  assert.ok(assessHeaders({ ...good, "strict-transport-security": HSTS + "; preload" }).errors.length > 0);
  assert.ok(assessHeaders({ ...good, "content-security-policy": "default-src 'self'" }).errors.length > 0);
});

// ═══ what production will send ═══════════════════════════════════════════════

function wranglerVar(name: string): string {
  const m = read("wrangler.toml").match(new RegExp(`^\\s*${name}\\s*=\\s*"([^"]+)"`, "m"));
  assert.ok(m, `no ${name} in wrangler.toml`);
  return m[1];
}

test("given the configuration production declares, connect-src names exactly its API and its Supabase", () => {
  const built = buildHeadersFile({
    apiUrl: wranglerVar("NEXT_PUBLIC_API_URL"),
    supabaseUrl: wranglerVar("NEXT_PUBLIC_SUPABASE_URL"),
  });
  assert.deepEqual(built.missing, []);
  assert.deepEqual(built.origins, [
    originOf(wranglerVar("NEXT_PUBLIC_API_URL")),
    originOf(wranglerVar("NEXT_PUBLIC_SUPABASE_URL")),
  ]);
  assert.ok(built.origins.every((o) => o?.startsWith("https://")), "production talks to https hosts only");
});

// ═══ the build runs it, in both apps, after next build ═══════════════════════

function scriptsOf(pkg: string): Record<string, string> {
  return JSON.parse(fs.readFileSync(pkg, "utf8")).scripts;
}

for (const [app, pkgPath] of [
  ["apps/web", path.join(WEB, "package.json")],
  ["apps/marketing", path.join(REPO, "apps", "marketing", "package.json")],
] as const) {
  test(`${app}: every script that runs \`next build\` runs the header generator AFTER it`, () => {
    const scripts = scriptsOf(pkgPath);
    const building = Object.entries(scripts).filter(([, cmd]) => /next build/.test(cmd));
    assert.ok(building.length >= 1, "vacuous: no script runs next build");
    for (const [name, cmd] of building) {
      const build = cmd.indexOf("next build");
      const gen = cmd.indexOf("scripts/security-headers.mjs");
      assert.ok(gen > build, `${app} "${name}" runs \`next build\` and not the header generator after it: ${cmd}`);
    }
  });

  test(`${app}: there is no hand-written _headers in public/ for the generator to overwrite`, () => {
    const file = path.join(path.dirname(pkgPath), "public", "_headers");
    assert.ok(!fs.existsSync(file), `${file} exists: out/_headers is generated and this would be overwritten or, if the generator is skipped, served stale`);
  });
}

test("the smoke build runs the generator too, so the walk is of the product as served", () => {
  assert.match(scriptsOf(path.join(WEB, "package.json"))["smoke:build"], /npm run build/);
});

// ═══ the policy and the code agree ═══════════════════════════════════════════

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(path.join(WEB, dir))) {
    const rel = path.join(dir, entry);
    const st = fs.statSync(path.join(WEB, rel));
    if (st.isDirectory()) {
      if (entry === "node_modules" || entry === ".next" || entry === "out") continue;
      walk(rel, out);
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.(ts|tsx)$/.test(entry)) {
      out.push(rel);
    }
  }
  return out;
}

const SOURCES = ["app", "components", "lib"].flatMap((d) => walk(d)).map((rel) => ({
  rel, code: stripComments(read(rel)),
}));

function offenders(pattern: RegExp): string[] {
  return SOURCES.filter((s) => pattern.test(s.code)).map((s) => s.rel);
}

test("the source set is not empty", () => {
  assert.ok(SOURCES.length > 300);
});

test("nothing opens a socket, an event stream, a Realtime channel, a worker or a beacon", () => {
  // Each needs a directive the policy does not grant (connect-src has no wss:, worker-src is 'self'), and the
  // failure would be silent in a browser nobody has open.
  const found = offenders(/new\s+WebSocket\s*\(|new\s+EventSource\s*\(|navigator\.sendBeacon|new\s+(Shared)?Worker\s*\(|\.channel\s*\(\s*["'`]|\brealtime\b/i);
  assert.deepEqual(found, [], "update contentSecurityPolicy in scripts/security-headers.mjs (and the marketing sibling if it applies) in the same change");
});

test("every iframe is a sandboxed srcdoc, which is why frame-src is 'none'", () => {
  for (const s of SOURCES) {
    for (const tag of s.code.match(/<iframe\b[^>]*>/g) ?? []) {
      assert.ok(/srcDoc=/.test(tag), `${s.rel}: an iframe that loads a URL needs frame-src: ${tag}`);
      assert.ok(/sandbox=/.test(tag), `${s.rel}: an iframe without sandbox: ${tag}`);
    }
    assert.ok(!/<(object|embed)\b/.test(s.code), `${s.rel}: <object>/<embed> are forbidden by object-src 'none'`);
  }
});

test("nothing uses eval or `new Function`, which the policy has no 'unsafe-eval' for", () => {
  const found = offenders(/(^|[^.\w$])eval\s*\(|new\s+Function\s*\(/);
  assert.deepEqual(found, []);
});

test("nothing uses a feature Permissions-Policy switches off", () => {
  const found = offenders(/getUserMedia|mediaDevices|navigator\.geolocation|PaymentRequest|navigator\.usb|DeviceMotionEvent|DeviceOrientationEvent|new\s+(Accelerometer|Gyroscope|Magnetometer)\b/);
  assert.deepEqual(found, [], "remove it from PERMISSIONS_POLICY in both generators in the same change");
});

test("a form that posts anywhere posts to this origin (form-action 'self')", () => {
  for (const s of SOURCES) {
    for (const tag of s.code.match(/<form\b[^>]*>/g) ?? []) {
      assert.ok(!/action=\{?["'`]?https?:/.test(tag), `${s.rel}: ${tag}`);
    }
  }
});
