// The backend URL is written in two files. They must agree. Run with:
//   node --experimental-strip-types --test scripts/api-url.test.ts
//
// THE MISTAKE THIS EXISTS TO CATCH
//     apps/web is a static export (`output: "export"`), so NEXT_PUBLIC_API_URL
//     is INLINED into the JavaScript bundle at build time. There is no runtime
//     config to correct it afterwards — a wrong value ships to every browser
//     and the only fix is another build.
//
//     Two files decide that value:
//
//       wrangler.toml   [vars] — what Cloudflare Pages actually builds with,
//                       and (because pages_build_output_dir makes this project
//                       config-as-code) what the dashboard shows READ-ONLY.
//       next.config.mjs        — the production fallback used when the var is
//                       absent, so a missing var cannot silently degrade to
//                       the localhost dev default.
//
//     The fallback is the dangerous half. If the two drift, nothing fails:
//     the build succeeds, the bundle is valid, and the app simply talks to the
//     wrong backend. That is exactly what happened during the Oregon ->
//     Singapore move, where the two candidate hostnames were
//
//         practicesync-ai .onrender.com   (Oregon, retired)
//         practicesync-api.onrender.com   (Singapore, current)
//
//     — one character apart. A typo in either file is invisible on inspection
//     and produces a working build pointed at a dead host.
//
// WHAT IT DOES NOT DO
//     It cannot tell you the URL is CORRECT, only that the repo says one thing
//     with one voice. Confirming the host is the right one is a human step.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

const read = (f: string) => fs.readFileSync(path.join(WEB, f), "utf8");

/** `NEXT_PUBLIC_API_URL = "..."` from wrangler's [vars]. Deliberately not a
 *  TOML parser: adding a dependency to read one line would be the larger risk,
 *  and the vacuity guard below fails loudly if this stops matching. */
function wranglerApiUrl(): string | null {
  const m = read("wrangler.toml").match(
    /^\s*NEXT_PUBLIC_API_URL\s*=\s*"([^"]+)"/m,
  );
  return m ? m[1] : null;
}

/** The production arm of the ternary in next.config.mjs. */
function configFallbackApiUrl(): string | null {
  const m = read("next.config.mjs").match(
    /NODE_ENV\s*===\s*"production"\s*\?\s*"([^"]+)"/,
  );
  return m ? m[1] : null;
}

test("both sources are still parseable", () => {
  // Vacuity guard. If either returns null the equality check below compares
  // null to null and passes through any amount of drift.
  assert.notEqual(wranglerApiUrl(), null, "no NEXT_PUBLIC_API_URL in wrangler.toml");
  assert.notEqual(configFallbackApiUrl(), null, "no production fallback in next.config.mjs");
});

test("wrangler.toml and next.config.mjs name the same backend", () => {
  assert.equal(
    configFallbackApiUrl(),
    wranglerApiUrl(),
    "next.config.mjs's production fallback disagrees with wrangler.toml's " +
      "[vars]. Whichever is wrong, the build still succeeds and the app talks " +
      "to the wrong backend — change both or neither.",
  );
});

test("the production URL is a real https origin", () => {
  for (const [where, url] of [
    ["wrangler.toml", wranglerApiUrl()],
    ["next.config.mjs", configFallbackApiUrl()],
  ] as const) {
    assert.ok(url!.startsWith("https://"), `${where}: ${url} is not https`);
    assert.ok(
      !/localhost|127\.0\.0\.1/.test(url!),
      `${where}: ${url} is a dev address — it would ship to every browser`,
    );
    assert.ok(!url!.endsWith("/"), `${where}: ${url} has a trailing slash; callers append "/api/..."`);
  }
});
