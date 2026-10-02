#!/usr/bin/env node
/**
 * Asks the LIVE sites whether the security headers are actually being served (security_privacy-05).
 *
 * WHY IT EXISTS
 *     `scripts/security-headers.mjs` writes out/_headers after `next build`, and everything between that file
 *     and a browser is somebody else's: the Cloudflare Pages build command has to run the script (package.json's
 *     `build` and `pages:build` do; a dashboard command that calls `next build` directly does not), Pages has to
 *     accept the file (a line over 2,000 characters is ignored without a word), and Pages has to apply it to the
 *     response (it documents that a redirect takes priority over a header rule and is silent about the `200`
 *     rewrite every /clients/<id>/… page is). Every check in the repository on this file is static. This asks
 *     the site, the same reason check-live-redirects.mjs exists.
 *
 * WHAT IT CHECKS, per site
 *     the six headers the generator writes. A missing one is a FAILURE: `x-content-type-options` alone is not
 *     evidence (Cloudflare sends it by default), so the others are what show the file was applied. The CSP is
 *     reported as enforced, REPORT-ONLY or none; none is a warning and not a failure, because
 *     SECURITY_CSP_MODE=off is the documented way back and must not turn a monitor red for ever.
 *     For the product, also one URL that Pages serves through a rewrite; headers missing THERE is a warning
 *     naming the gap, not a failure, since whether Pages applies them to a rewrite is the open question.
 *
 *     Usage: node scripts/check-live-headers.mjs <product-url> [--marketing]
 *     `--marketing` also checks the marketing site (MARKETING_URL below), a different Cloudflare project with its
 *     own build; the workflow leaves it off for a product deployment, which changes nothing there.
 *     Exit 0: both sites carry the headers (warnings are printed). Exit 1: a header is missing. Exit 2: usage.
 *
 * It sends GET requests to public sites, writes nothing and holds no secret. Not a required check.
 */
import { pathToFileURL } from "node:url";

/** The path the product serves through a `_redirects` 200 rewrite to its built `_placeholder` page. */
export const REWRITTEN_PATH = "/clients/00000000-0000-4000-8000-000000000001/accounting/";

/** The marketing site, which is apps/marketing and its own Cloudflare Pages project. */
export const MARKETING_URL = "https://practicesync.pages.dev";

export const REQUIRED = [
  "x-content-type-options",
  "x-frame-options",
  "referrer-policy",
  "permissions-policy",
  "strict-transport-security",
];

/**
 * @param {Record<string, string>} headers lower-case name -> value
 * @returns {{ errors: string[], csp: "enforced" | "report-only" | "none" }}
 */
export function assessHeaders(headers) {
  const errors = [];
  for (const name of REQUIRED) {
    if (!headers[name]) errors.push(`missing ${name}`);
  }
  if (headers["x-content-type-options"] && headers["x-content-type-options"].toLowerCase() !== "nosniff") {
    errors.push(`x-content-type-options is ${JSON.stringify(headers["x-content-type-options"])}, not nosniff`);
  }
  if (headers["x-frame-options"] && headers["x-frame-options"].toUpperCase() !== "DENY") {
    errors.push(`x-frame-options is ${JSON.stringify(headers["x-frame-options"])}, not DENY`);
  }
  const hsts = headers["strict-transport-security"];
  if (hsts) {
    if (!/^max-age=\d+/.test(hsts)) errors.push(`strict-transport-security is malformed: ${hsts}`);
    if (/preload/i.test(hsts) || /includesubdomains/i.test(hsts)) {
      errors.push("strict-transport-security carries preload or includeSubDomains, which nobody decided");
    }
  }
  const csp = headers["content-security-policy"]
    ? "enforced"
    : headers["content-security-policy-report-only"]
      ? "report-only"
      : "none";
  if (csp === "enforced" && !/frame-ancestors 'none'/.test(headers["content-security-policy"])) {
    errors.push("the enforced CSP has no frame-ancestors 'none'");
  }
  return { errors, csp };
}

/** @param {Headers} h */
function toRecord(h) {
  /** @type {Record<string, string>} */
  const out = {};
  h.forEach((value, name) => {
    out[name.toLowerCase()] = value;
  });
  return out;
}

async function fetchHeaders(url, attempts = 3, pauseMs = 10_000) {
  let last;
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(20_000) });
      await res.arrayBuffer().catch(() => undefined);
      return { status: res.status, headers: toRecord(res.headers) };
    } catch (err) {
      last = err;
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, pauseMs));
    }
  }
  throw last;
}

async function main(argv) {
  const product = argv.find((a) => !a.startsWith("--"));
  const marketing = argv.includes("--marketing") ? MARKETING_URL : undefined;
  if (!product) {
    console.error("usage: check-live-headers.mjs <product-url> [--marketing]");
    process.exit(2);
  }
  const targets = [
    { label: "product /login/", url: new URL("/login/", product).href, failing: true },
    { label: "product, through a rewrite", url: new URL(REWRITTEN_PATH, product).href, failing: false },
  ];
  if (marketing) targets.push({ label: "marketing /", url: new URL("/", marketing).href, failing: true });

  let failed = false;
  for (const t of targets) {
    let result;
    try {
      const { status, headers } = await fetchHeaders(t.url);
      result = { status, ...assessHeaders(headers) };
    } catch (err) {
      console.log(`${t.failing ? "FAIL" : "warn"}  ${t.label}: unreachable (${err instanceof Error ? err.message : err})`);
      if (t.failing) failed = true;
      continue;
    }
    const verdict = result.errors.length ? (t.failing ? "FAIL" : "warn") : "ok  ";
    console.log(`${verdict}  ${t.label}: HTTP ${result.status}, CSP ${result.csp}` +
      (result.errors.length ? ` — ${result.errors.join("; ")}` : ""));
    if (result.csp === "none") console.log(`warn  ${t.label}: no Content-Security-Policy is being served`);
    if (result.errors.length) {
      if (t.failing) failed = true;
      if (process.env.GITHUB_ACTIONS === "true") {
        const kind = t.failing ? "error" : "warning";
        console.log(`::${kind} title=Security headers: ${t.label}::${result.errors.join("; ").slice(0, 300)}`);
      }
    }
  }
  process.exit(failed ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main(process.argv.slice(2)).catch((err) => {
    console.error(`check-live-headers: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(2);
  });
}
