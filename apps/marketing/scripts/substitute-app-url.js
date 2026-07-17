#!/usr/bin/env node
/**
 * Rewrites the app-origin URLs baked into the static homepage
 * (out/practicesync-homepage.html) to match NEXT_PUBLIC_APP_URL at build time.
 *
 * Why this exists: the homepage is served verbatim from a static HTML file
 * (public/practicesync-homepage.html) rather than rendered by Next, so — unlike
 * every React page on the marketing site — it can't read NEXT_PUBLIC_APP_URL
 * and interpolate it. Its "Start free trial" / "Client portal" links point at
 * the actual app (apps/web), a separate origin. Without this step that origin
 * would be permanently hardcoded, so the day the app moves to a custom domain
 * (e.g. app.practicesync.com) the homepage would keep sending people to the old
 * *.pages.dev URL while the React pages quietly followed the env var.
 *
 * Runs as part of `pnpm build`, AFTER `next build` (which is what produces
 * out/) — see package.json. Operating on out/ rather than public/ keeps the
 * committed source file valid and dev-usable on its own: `next dev` serves
 * public/ as-is, and DEFAULT_APP_URL below is the real production origin, so
 * local links work without this script ever running. Only the *built artifact*
 * gets customized, and only when an override is actually set.
 *
 * DEFAULT_APP_URL must stay in sync with two things: next.config.mjs's
 * production fallback for NEXT_PUBLIC_APP_URL, and the origin literally written
 * into public/practicesync-homepage.html's links. When no override is set the
 * two are identical and this is a no-op.
 */
const { readFileSync, writeFileSync, existsSync } = require("node:fs");
const path = require("node:path");

// The app origin baked into public/practicesync-homepage.html and the
// production default in next.config.mjs. Keep all three in agreement.
const DEFAULT_APP_URL = "https://caflow-ai.pages.dev";

// Resolve the target the same way next.config.mjs does for production. `out/`
// only ever comes from a production `next build`, so the localhost dev default
// is intentionally not considered here — we never want it baked into the
// shipped file. Trailing slash stripped so `${origin}/signup` stays clean.
const target = (process.env.NEXT_PUBLIC_APP_URL || DEFAULT_APP_URL).replace(/\/+$/, "");

const file = path.join(__dirname, "..", "out", "practicesync-homepage.html");

if (!existsSync(file)) {
  console.error(
    `[substitute-app-url] ${file} not found — did \`next build\` run first? ` +
      "This script must run after the static export is generated."
  );
  process.exit(1);
}

const html = readFileSync(file, "utf8");
const occurrences = html.split(DEFAULT_APP_URL).length - 1;

if (target === DEFAULT_APP_URL) {
  console.log(
    `[substitute-app-url] NEXT_PUBLIC_APP_URL matches the default (${DEFAULT_APP_URL}); ` +
      `${occurrences} link(s) left unchanged.`
  );
  process.exit(0);
}

if (occurrences === 0) {
  // An override was requested but there's nothing to rewrite — most likely the
  // homepage's links were edited to a different origin than DEFAULT_APP_URL.
  // Warn loudly rather than silently shipping stale URLs, but don't fail the
  // build over it.
  console.warn(
    `[substitute-app-url] WARNING: NEXT_PUBLIC_APP_URL is set to ${target}, but no ` +
      `occurrences of ${DEFAULT_APP_URL} were found in the homepage — nothing was ` +
      "rewritten. Check that the homepage's app links still use DEFAULT_APP_URL."
  );
  process.exit(0);
}

writeFileSync(file, html.split(DEFAULT_APP_URL).join(target), "utf8");
console.log(
  `[substitute-app-url] rewrote ${occurrences} app link(s) from ${DEFAULT_APP_URL} to ${target}.`
);
