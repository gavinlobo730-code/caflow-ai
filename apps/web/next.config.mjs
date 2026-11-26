import fs from "node:fs";

/**
 * The id of this build, and the guarantee that the live site serves the same id at /version.json (POST-A-529).
 *
 * ON CLOUDFLARE the id is the commit being built (`CF_PAGES_COMMIT_SHA`), and this function WRITES the file itself when
 * it does not already say so. That is deliberate: which build command the Pages project runs is a dashboard setting this
 * repository cannot read, and a command that calls `next build` directly never runs scripts/write-build-version.mjs. The
 * config is loaded before the export copies `public/`, in every process of a build, and each writes the same bytes.
 * ANYWHERE ELSE the id is whatever the script wrote (the moment of the build), or "" when there is no file: an empty id
 * is unknown, and a tab that does not know its own build is never told anything.
 */
function readBuildVersion() {
  const file = new URL("./public/version.json", import.meta.url);
  const commit = String(process.env.CF_PAGES_COMMIT_SHA || "").trim().toLowerCase();
  if (/^[0-9a-f]{7,64}$/.test(commit)) {
    const want = JSON.stringify({ version: commit }) + "\n";
    try {
      if (!fs.existsSync(file) || fs.readFileSync(file, "utf8") !== want) fs.writeFileSync(file, want);
    } catch {
      // The bundle still carries the id; with no file the live site answers nothing and the tab stays silent.
    }
    return commit;
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    return typeof parsed?.version === "string" && /^[A-Za-z0-9._-]{1,80}$/.test(parsed.version) ? parsed.version : "";
  } catch {
    return "";
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  env: {
    // Build-time guarantee for the public backend URL. NEXT_PUBLIC_* values are
    // INLINED at build time (a static export can't read runtime env), so a
    // production build that somehow lacks the env var must NOT silently fall
    // back to the localhost dev default — that would make every FastAPI call
    // (e.g. /platform's admin check) fail in the browser. An explicit
    // NEXT_PUBLIC_API_URL (Cloudflare build var / wrangler [vars]) always wins;
    // otherwise production gets the real backend and dev keeps localhost.
    //
    // KEEP THIS IN STEP WITH apps/web/wrangler.toml — scripts/api-url.test.ts
    // fails if they disagree. They are not redundant: wrangler [vars] is what
    // Cloudflare actually builds with, and this is the last line of defence if
    // that var goes missing. If they drift, the fallback quietly aims the whole
    // app at the wrong backend and the build still succeeds.
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL ||
      (process.env.NODE_ENV === "production"
        ? "https://practicesync-api.onrender.com"
        : "http://localhost:8000"),

    // The id of THIS build, so a tab can learn that a newer one is live (POST-A-529; lib/version). Read from the file
    // scripts/write-build-version.mjs wrote before this config was loaded, which is the same file the live site serves, so
    // the id in the bundle and the id at /version.json cannot disagree. With no file (a `next dev`, a build that skipped
    // the script) it is empty, and an empty id is unknown: the tab is never told anything.
    NEXT_PUBLIC_BUILD_ID: readBuildVersion(),

    // Browser error reporting (ops-09; lib/monitoring). The DSN itself is NEXT_PUBLIC_SENTRY_DSN, set
    // as a Cloudflare Pages build variable and INLINED like every NEXT_PUBLIC_ value — with none, the
    // tracker never starts. These two are derived here because Cloudflare's own build variables are
    // not NEXT_PUBLIC_ and so would never reach the browser: CF_PAGES_COMMIT_SHA is documented as the
    // value to hand an error tracker, and CF_PAGES_BRANCH says production from a preview.
    NEXT_PUBLIC_SENTRY_RELEASE:
      process.env.NEXT_PUBLIC_SENTRY_RELEASE || process.env.CF_PAGES_COMMIT_SHA || "",
    NEXT_PUBLIC_SENTRY_ENVIRONMENT:
      process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ||
      (process.env.CF_PAGES_BRANCH
        ? process.env.CF_PAGES_BRANCH === "main"
          ? "production"
          : "preview"
        : process.env.NODE_ENV === "production"
          ? "production"
          : "development"),
  },
};

export default nextConfig;
