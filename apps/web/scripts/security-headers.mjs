#!/usr/bin/env node
/**
 * Writes out/_headers: the security headers Cloudflare Pages sends with every page of the product
 * (security_privacy-05). Run by `build` and `pages:build` AFTER `next build`, which empties out/.
 *
 * WHY A GENERATOR AND NOT A FILE IN public/
 *     A `_headers` file is static text, and the one value that makes a Content-Security-Policy worth having
 *     is not static: `connect-src` must name the API, Supabase and the error tracker EXACTLY. A wildcard
 *     (`*.onrender.com`, `*.supabase.co`) lets anybody who can create a service on either host receive what
 *     a script stole, which defeats the point of the directive (a CSP is the main mitigation for the Supabase
 *     session living in localStorage). Those three hosts are build-time `NEXT_PUBLIC_*` values, inlined into
 *     the bundle exactly as the bundle's own `fetch` calls read them, so the same values are read here.
 *
 *     The API URL is read from next.config.mjs's `env`, not from process.env: that file is what decides the
 *     production fallback ("https://practicesync-api.onrender.com" when the variable is missing), so asking
 *     it is what makes this agree with the bundle by construction instead of by a second copy of the rule.
 *
 * WHAT IS SENT, AND WHY EACH IS SAFE TO ENFORCE
 *     X-Content-Type-Options: nosniff                  Cloudflare already sends it; stated so it does not
 *                                                      depend on a default Cloudflare may change.
 *     X-Frame-Options: DENY                            nothing frames this app (the one iframe, the
 *                                                      engagement letter on /sign, is a srcdoc INSIDE it).
 *     Referrer-Policy: strict-origin-when-cross-origin the value Cloudflare already sends, stated. Other
 *                                                      origins see this one's origin and never a path, so
 *                                                      a client id or a signing token is not leaked.
 *     Permissions-Policy: camera=(), microphone=()...  none is used anywhere in apps/web (checked by a test).
 *     Strict-Transport-Security: max-age=2592000       30 days, no includeSubDomains, no preload — see
 *                                                      HSTS below.
 *     Content-Security-Policy                          see CSP below.
 *     Cache-Control is deliberately NOT here: Pages' own default (public, max-age=0, must-revalidate) is
 *     right for a static export and a rule here would override it for every asset.
 *
 * CSP
 *     script-src needs 'unsafe-inline': a Next static export puts its bootstrap and its flight payload in
 *     inline <script> elements and the layout registers the service worker inline. Hashes are per page and
 *     per build, and `_headers` allows a hundred rules, so a nonce or hash policy is not available to a
 *     static export. What the policy still buys, and why it is worth having with 'unsafe-inline':
 *       * connect-src: a script that runs cannot send the session, or anything else, to a host that is not
 *         ours — the exfiltration route an XSS in localStorage's threat model needs;
 *       * frame-ancestors / object-src / base-uri / form-action: clickjacking, plugin content, a <base>
 *         that re-points every relative URL, and a form that posts away.
 *     No 'unsafe-eval': the production bundle contains no eval and no `new Function` (checked on a real
 *     build; the polyfill's `Function("return this")` is behind a globalThis test that is always true).
 *     img-src allows https: because a firm's logo is an image URL a person recorded (settings > branding),
 *     and data:/blob: for the SVG backgrounds, the MFA QR code Supabase returns as a data URI and any
 *     preview made from a Blob.
 *     style-src needs 'unsafe-inline': React `style=` attributes, and the engagement letter's srcdoc
 *     iframe, which INHERITS this policy and carries its own <style>.
 *     frame-src is 'none': the engagement letter's sandboxed srcdoc iframe is not fetched, so it is not subject
 *     to it. Checked in Chromium against this exact policy on 02-10-2026: a srcdoc iframe with an inline
 *     <style> renders styled, and a PDF opened from a blob: URL in a new tab still gets the browser's PDF
 *     viewer under `object-src 'none'`. Firefox and Safari were not run.
 *
 *     SECURITY_CSP_MODE decides whether the policy is ENFORCED, and it needs no code change to move either
 *     way. `report-only` (THE DEFAULT, see below) sends Content-Security-Policy-Report-Only (the browser
 *     console says what WOULD have been blocked and nothing is); `enforce` sends Content-Security-Policy;
 *     `off` sends neither. Set it as a Cloudflare Pages build variable and retry the deployment — a static
 *     export has no runtime, so a rebuild is the switch. A value that is none of the three is read as unset
 *     (the default), the reading CLAUDE.md gives every safety flag, and the build prints which mode it chose.
 *     There is no report endpoint: nothing receives violations, so report-only is for a person with DevTools
 *     open.
 *
 *     WHY THE DEFAULT IS report-only AND NOT enforce. The policy was built and walked with every screen of
 *     the export in Chromium (170 screens, no violation, enforced), but the walk is same-origin by design:
 *     it never met the real Supabase, Render and error-tracker hosts, Safari or Firefox, or the screens it
 *     cannot drive (a real sign-in, an export, an invoice PDF opened in a new tab, MFA enrolment). A policy
 *     that is wrong and enforced stops sign-in for every user and says nothing, and nobody had yet exercised
 *     the deployed app with the console open, so the first deployment REPORTS and the other five headers are
 *     enforced. Moving to enforce is `SECURITY_CSP_MODE=enforce` after a person has done that on a real
 *     deployment and found no "Refused to ..." line; it is the one decision here that is not code.
 *
 * WHEN A HOST IS MISSING
 *     NEXT_PUBLIC_SUPABASE_URL unset makes the bundle fall back to https://placeholder.supabase.co, which is
 *     not a working app whatever the headers say; the CSP then simply omits Supabase and the build says so
 *     on stderr. NEXT_PUBLIC_SENTRY_DSN unset means the tracker never starts and no Sentry origin is added.
 *     A value that is not an http(s) URL is treated as missing and never copied into the header, so a typo
 *     cannot inject a directive: only `URL.origin` is ever written.
 *
 * HSTS
 *     pages.dev is on the browsers' preload list as part of the .dev TLD, so on today's hostnames the header
 *     changes nothing; it matters the day a custom domain is attached. 30 days and no includeSubDomains or
 *     preload, for the reason apps/api/middleware/security_headers.py gives: a browser told HSTS cannot be
 *     told otherwise, and nobody has shown that every sibling hostname is https-only.
 *
 * ⚠️ NOT VERIFIED HERE: whether Cloudflare applies `_headers` to a response it serves through a `_redirects`
 * 200 rewrite (every /clients/<id>/… page is one). The documentation says a redirect takes priority over a
 * header rule and is silent on a rewrite. If it does not, those pages carry no CSP — fail-safe, nothing
 * breaks — and `scripts/check-live-headers.mjs` is how to find out.
 *
 * Pure parts are exported and tested by scripts/the-sites-send-security-headers.test.ts.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const HSTS = "max-age=2592000";
export const REFERRER_POLICY = "strict-origin-when-cross-origin";
export const X_FRAME_OPTIONS = "DENY";
export const PERMISSIONS_POLICY =
  "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()";

/** Cloudflare ignores a line over this length without a word (the whole rule's header, in the worst case). */
export const MAX_LINE = 2000;

export const CSP_MODES = ["enforce", "report-only", "off"];

/** What nobody decided means. See "WHY THE DEFAULT IS report-only" in the header. */
export const DEFAULT_CSP_MODE = "report-only";

/**
 * @param {unknown} raw
 * @returns {string | null} `https://host[:port]`, or null for anything that is not an http(s) URL.
 */
export function originOf(raw) {
  const text = String(raw ?? "").trim();
  if (!text) return null;
  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  // `URL` accepts `;` and `,` inside a host, and either would end a CSP directive and start another from
  // whatever follows. A hostname is letters, digits, dots and hyphens; an origin that is anything else
  // (an IPv6 literal included, which nothing here uses) is treated as missing and never written.
  return ORIGIN_SHAPE.test(url.origin) ? url.origin : null;
}

const ORIGIN_SHAPE = /^https?:\/\/[A-Za-z0-9.-]+(:\d{1,5})?$/;

/** The ingest origin of a Sentry DSN (`https://<key>@o1.ingest.sentry.io/2`), or null. */
export function sentryOrigin(dsn) {
  return originOf(dsn);
}

/**
 * `SECURITY_CSP_MODE`, read the way every safety flag in this repository is: unset, blank and unrecognisable
 * are the same fact (nobody decided), and that fact has ONE answer, `DEFAULT_CSP_MODE`.
 * @param {unknown} raw
 */
export function cspMode(raw) {
  const value = String(raw ?? "").trim().toLowerCase();
  return CSP_MODES.includes(value) ? value : DEFAULT_CSP_MODE;
}

/** @param {Array<[string, string[]]>} directives */
function serialise(directives) {
  return directives.map(([name, values]) => `${name} ${values.join(" ")}`).join("; ");
}

/**
 * The product's policy. `connectOrigins` is the already-validated list of origins the bundle talks to.
 * @param {{ connectOrigins: string[] }} input
 */
export function contentSecurityPolicy({ connectOrigins }) {
  return serialise([
    ["default-src", ["'self'"]],
    ["script-src", ["'self'", "'unsafe-inline'"]],
    ["style-src", ["'self'", "'unsafe-inline'"]],
    ["img-src", ["'self'", "data:", "blob:", "https:"]],
    ["font-src", ["'self'"]],
    ["connect-src", ["'self'", ...connectOrigins]],
    ["worker-src", ["'self'"]],
    ["manifest-src", ["'self'"]],
    ["frame-src", ["'none'"]],
    ["object-src", ["'none'"]],
    ["base-uri", ["'self'"]],
    ["form-action", ["'self'"]],
    ["frame-ancestors", ["'none'"]],
  ]);
}

/**
 * The origins connect-src must name, and which of the three could not be derived.
 * @param {{ apiUrl?: unknown, supabaseUrl?: unknown, sentryDsn?: unknown }} env
 */
export function connectSources(env) {
  const wanted = [
    ["NEXT_PUBLIC_API_URL", originOf(env.apiUrl), true],
    ["NEXT_PUBLIC_SUPABASE_URL", originOf(env.supabaseUrl), true],
    // Optional: with no DSN the tracker never starts, so a missing one is not a gap.
    ["NEXT_PUBLIC_SENTRY_DSN", sentryOrigin(env.sentryDsn), false],
  ];
  const origins = [];
  const missing = [];
  for (const [name, origin, required] of wanted) {
    if (origin) {
      if (!origins.includes(origin)) origins.push(origin);
    } else if (required) {
      missing.push(name);
    }
  }
  return { origins, missing };
}

/**
 * The whole file. `mode` decides the CSP header's name or whether there is one.
 * @param {{ apiUrl?: unknown, supabaseUrl?: unknown, sentryDsn?: unknown, mode?: unknown }} env
 * @returns {{ content: string, mode: string, origins: string[], missing: string[] }}
 */
export function buildHeadersFile(env) {
  const mode = cspMode(env.mode);
  const { origins, missing } = connectSources(env);
  const lines = [
    "# GENERATED FILE — do not hand-edit.",
    "# Produced by scripts/security-headers.mjs after `next build` (see package.json's \"build\" and",
    "# \"pages:build\"). The connect-src origins are read from the same NEXT_PUBLIC_* values the bundle",
    "# was built with. Read the header of that script before changing anything here.",
    `# CSP mode: ${mode}${missing.length ? ` — NOT DERIVED: ${missing.join(", ")}` : ""}`,
    "/*",
    "  X-Content-Type-Options: nosniff",
    `  X-Frame-Options: ${X_FRAME_OPTIONS}`,
    `  Referrer-Policy: ${REFERRER_POLICY}`,
    `  Permissions-Policy: ${PERMISSIONS_POLICY}`,
    `  Strict-Transport-Security: ${HSTS}`,
  ];
  if (mode !== "off") {
    const name = mode === "report-only" ? "Content-Security-Policy-Report-Only" : "Content-Security-Policy";
    lines.push(`  ${name}: ${contentSecurityPolicy({ connectOrigins: origins })}`);
  }
  for (const line of lines) {
    if (line.length > MAX_LINE) {
      throw new Error(`a line of _headers is ${line.length} characters; Cloudflare ignores any over ${MAX_LINE}`);
    }
  }
  return { content: lines.join("\n") + "\n", mode, origins, missing };
}

/**
 * Parses what Cloudflare reads: a path pattern on an unindented line, then indented `Name: value` lines.
 * Only the subset this repository writes is accepted — `/*` and literal paths, plus `*` splats — and anything
 * else THROWS, because a consumer that silently skipped a rule it did not understand would tell a test the
 * headers were fine.
 * @param {string} text
 * @returns {Array<{ pattern: string, headers: Array<[string, string]> }>}
 */
export function parseHeadersFile(text) {
  const rules = [];
  let current = null;
  for (const raw of text.split(/\r?\n/)) {
    if (!raw.trim() || raw.trimStart().startsWith("#")) continue;
    if (/^\s/.test(raw)) {
      if (!current) throw new Error(`a header line before any path: ${raw.trim()}`);
      if (raw.trim().startsWith("!")) throw new Error(`a detach rule is not understood here: ${raw.trim()}`);
      const at = raw.indexOf(":");
      if (at < 0) throw new Error(`not a "Name: value" line: ${raw.trim()}`);
      const name = raw.slice(0, at).trim();
      current.headers.push([name, raw.slice(at + 1).trim()]);
    } else {
      const pattern = raw.trim();
      if (/:[A-Za-z]/.test(pattern.replace(/^https?:\/\//, ""))) {
        throw new Error(`a placeholder path is not understood here: ${pattern}`);
      }
      current = { pattern, headers: [] };
      rules.push(current);
    }
  }
  return rules;
}

/** Whether a `_headers` path pattern matches a request path. `*` matches any run of characters. */
export function patternMatches(pattern, requestPath) {
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`).test(requestPath);
}

/**
 * The headers Cloudflare would add to a response for `requestPath`. A header named by more than one matching
 * rule is joined with a comma, as the documentation says.
 * @param {Array<{ pattern: string, headers: Array<[string, string]> }>} rules
 * @param {string} requestPath
 * @returns {Record<string, string>} lower-case name -> value
 */
export function headersFor(rules, requestPath) {
  /** @type {Record<string, string>} */
  const out = {};
  for (const rule of rules) {
    if (!patternMatches(rule.pattern, requestPath)) continue;
    for (const [name, value] of rule.headers) {
      const key = name.toLowerCase();
      out[key] = out[key] ? `${out[key]}, ${value}` : value;
    }
  }
  return out;
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(HERE, "..", "out");

async function main() {
  // `next build` sets NODE_ENV itself; this process runs after it and does not, and next.config.mjs reads it to
  // choose its production fallback for the API URL. Without this the generator would resolve the dev default
  // (http://localhost:8000) while the bundle was built with the production one.
  process.env.NODE_ENV = process.env.NODE_ENV || "production";
  const { default: nextConfig } = await import("../next.config.mjs");
  const { content, mode, origins, missing } = buildHeadersFile({
    apiUrl: nextConfig.env?.NEXT_PUBLIC_API_URL,
    supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL,
    sentryDsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    mode: process.env.SECURITY_CSP_MODE,
  });
  if (!fs.existsSync(OUT_DIR)) {
    console.error("security-headers: out/ does not exist — this runs after `next build`.");
    process.exit(1);
  }
  fs.writeFileSync(path.join(OUT_DIR, "_headers"), content);
  console.log(`security-headers: wrote out/_headers (CSP ${mode}; connect-src ${origins.join(" ") || "'self' only"})`);
  if (missing.length) {
    console.error(
      `security-headers: could not derive ${missing.join(", ")} from the build environment; the policy omits it. ` +
        `If this is a production build the app cannot reach that host either.`,
    );
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch((err) => {
    console.error(`security-headers: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(1);
  });
}
