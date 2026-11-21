/**
 * Writes public/version.json: the one fact a tab needs to learn that a newer build of the site is live (POST-A-529).
 *
 * WHY A FILE
 *     Every merge republishes the site, and a tab opened before it keeps the pages it loaded. The tab's own bundle carries
 *     the id of the build it came from (`NEXT_PUBLIC_BUILD_ID`, which next.config.mjs reads FROM THIS FILE, so the two
 *     cannot disagree), and the live site serves this file, so a tab compares the two (lib/version). A static export has
 *     no server to ask anything else of.
 *
 * WHAT THE ID IS
 *     The commit Cloudflare is building (`CF_PAGES_COMMIT_SHA`), which is what makes two builds of one commit the same
 *     version. With none (a build on a laptop, the smoke build in CI) the id is the moment of the build, so such a build
 *     still has an id and the browser scenarios can drive the notice. It is an identifier and never shown to a person.
 *
 * Run BEFORE `next build` (package.json `build` and `pages:build`): the file must be in `public/` when the export copies
 * it and when the config is read. It is generated, so it is not committed (.gitignore).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const target = path.join(here, "..", "public", "version.json");

/** The id for this build. Exported for the test. */
export function buildVersion(env, now) {
  const commit = String(env.CF_PAGES_COMMIT_SHA || "").trim();
  if (/^[0-9a-f]{7,64}$/i.test(commit)) return commit.toLowerCase();
  return `local-${now.toString(36)}`;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const version = buildVersion(process.env, Date.now());
  fs.writeFileSync(target, JSON.stringify({ version }) + "\n");
  console.log(`write-build-version: public/version.json is ${version}`);
}
