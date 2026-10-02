#!/usr/bin/env node
/**
 * Writes out/_headers: the security headers Cloudflare Pages sends with every page of the MARKETING site
 * (security_privacy-05). Run by `build` AFTER `next build`, which empties out/.
 *
 * It is the sibling of apps/web/scripts/security-headers.mjs and the reasoning is written once, there: why a
 * generator and not a file in public/, why 'unsafe-inline' for script and style in a static export, what
 * SECURITY_CSP_MODE is (what decides whether the policy is enforced: `report-only` by default until a person has
 * exercised the deployed app, `enforce` or `off` as a Cloudflare Pages build variable, then retry the deployment), why HSTS is 30 days with no includeSubDomains and no preload,
 * and what is not verified (whether Cloudflare applies `_headers` to a response it serves through a
 * `_redirects` rewrite — this site has none that matter, two 301s). `apps/api/tests/
 * test_the_two_sites_send_the_same_security_posture.py` holds the two scripts to the same header values from
 * the Python side, because this app has no test runner of its own.
 *
 * WHAT IS DIFFERENT HERE, and each is read off the code:
 *     connect-src   'self' and the API origin only. The site makes ONE cross-origin request, the demo form's
 *                   POST (and its GET of the firm-size options) to the API (components/DemoForm.tsx). It uses
 *                   no Supabase, no error tracker and no analytics (an owner decision a test holds).
 *     img-src       'self' and data: only. Its pictures are its own files (/hero, /og.jpg) and the SVG noise
 *                   behind the hero is a data: URI in CSS. A visitor's page loads no third-party image.
 *     font-src      'self': next/font downloads its families at build time and serves them from /_next.
 *     no worker-src, no blob: there is no service worker and nothing is made from a Blob.
 *     form-action   'self': the demo form is posted with fetch; if script fails, the browser's own submit
 *                   goes to the page itself.
 *     links out     (the app, mailto:, the demo form's email fallback) are navigations, which connect-src and
 *                   form-action do not govern.
 *
 * The API URL is read from next.config.mjs's `env` for the reason the web script gives: that file decides the
 * production fallback, so asking it agrees with the bundle by construction.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const HSTS = "max-age=2592000";
export const REFERRER_POLICY = "strict-origin-when-cross-origin";
export const X_FRAME_OPTIONS = "DENY";
export const PERMISSIONS_POLICY =
  "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()";

/** Cloudflare ignores a line over this length without a word. */
export const MAX_LINE = 2000;

export const CSP_MODES = ["enforce", "report-only", "off"];

/** What nobody decided means; the reasoning is written once, in apps/web/scripts/security-headers.mjs. */
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
  // whatever follows. A hostname is letters, digits, dots and hyphens; anything else is treated as missing.
  return ORIGIN_SHAPE.test(url.origin) ? url.origin : null;
}

const ORIGIN_SHAPE = /^https?:\/\/[A-Za-z0-9.-]+(:\d{1,5})?$/;

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
 * The site's policy. `connectOrigins` is the already-validated list of origins the bundle talks to.
 * @param {{ connectOrigins: string[] }} input
 */
export function contentSecurityPolicy({ connectOrigins }) {
  return serialise([
    ["default-src", ["'self'"]],
    ["script-src", ["'self'", "'unsafe-inline'"]],
    ["style-src", ["'self'", "'unsafe-inline'"]],
    ["img-src", ["'self'", "data:"]],
    ["font-src", ["'self'"]],
    ["connect-src", ["'self'", ...connectOrigins]],
    ["manifest-src", ["'self'"]],
    ["frame-src", ["'none'"]],
    ["object-src", ["'none'"]],
    ["base-uri", ["'self'"]],
    ["form-action", ["'self'"]],
    ["frame-ancestors", ["'none'"]],
  ]);
}

/**
 * The origins connect-src must name, and which could not be derived.
 * @param {{ apiUrl?: unknown }} env
 */
export function connectSources(env) {
  const api = originOf(env.apiUrl);
  return { origins: api ? [api] : [], missing: api ? [] : ["NEXT_PUBLIC_API_URL"] };
}

/**
 * The whole file. `mode` decides the CSP header's name or whether there is one.
 * @param {{ apiUrl?: unknown, mode?: unknown }} env
 * @returns {{ content: string, mode: string, origins: string[], missing: string[] }}
 */
export function buildHeadersFile(env) {
  const mode = cspMode(env.mode);
  const { origins, missing } = connectSources(env);
  const lines = [
    "# GENERATED FILE — do not hand-edit.",
    "# Produced by scripts/security-headers.mjs after `next build` (see package.json's \"build\"). The",
    "# connect-src origin is read from the same NEXT_PUBLIC_API_URL the bundle was built with. Read the",
    "# header of that script, and of apps/web/scripts/security-headers.mjs, before changing anything here.",
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

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(HERE, "..", "out");

async function main() {
  // `next build` sets NODE_ENV itself; this process runs after it and does not, and next.config.mjs reads it to
  // choose its production fallback for the API URL.
  process.env.NODE_ENV = process.env.NODE_ENV || "production";
  const { default: nextConfig } = await import("../next.config.mjs");
  const { content, mode, origins, missing } = buildHeadersFile({
    apiUrl: nextConfig.env?.NEXT_PUBLIC_API_URL,
    mode: process.env.SECURITY_CSP_MODE,
  });
  if (!fs.existsSync(OUT_DIR)) {
    console.error("security-headers: out/ does not exist — this runs after `next build`.");
    process.exit(1);
  }
  fs.writeFileSync(path.join(OUT_DIR, "_headers"), content);
  console.log(`security-headers: wrote out/_headers (CSP ${mode}; connect-src ${origins.join(" ") || "'self' only"})`);
  if (missing.length) {
    console.error(`security-headers: could not derive ${missing.join(", ")}; the policy omits it.`);
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch((err) => {
    console.error(`security-headers: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(1);
  });
}
