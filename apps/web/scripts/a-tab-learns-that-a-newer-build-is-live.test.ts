// A signed-in tab learns that a newer build of the site is live, and loads it only at the person's own move (POST-A-529).
//
// The rule itself is `lib/version/newVersion.ts` and its own test. This file holds the WIRING, which is where such a thing
// quietly stops working: the build must write the id before the pages are built, the bundle and the served file must take
// the id from one place, the service worker must never answer the file from a cache, and the component must load the new
// build in exactly two places (the move and the button) and never on a timer.
//
// NOT HELD HERE: which build command the Cloudflare Pages project runs is a dashboard setting. next.config.mjs writes the
// file itself when Cloudflare's commit id is present for that reason; that the live site really serves /version.json is
// only knowable by asking it after a deploy.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const web = path.join(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(web, rel), "utf8");
const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

test("every build writes its id before the pages are built", () => {
  const scripts = JSON.parse(read("package.json")).scripts as Record<string, string>;
  for (const name of ["build", "pages:build"]) {
    const steps = scripts[name].split("&&").map((s) => s.trim());
    const write = steps.indexOf("node scripts/write-build-version.mjs");
    const build = steps.findIndex((s) => s === "next build");
    assert.ok(write >= 0, `${name} does not write the build's id`);
    assert.ok(build > write, `${name} builds the pages before the id is written, so the bundle would carry no id`);
  }
  assert.match(scripts["smoke:build"], /npm run build$/, "the smoke build no longer goes through `build`, so the browser scenarios would have no id");
});

test("the bundle and the served file take the id from one place, and the file is generated and not committed", () => {
  const config = code(read("next.config.mjs"));
  assert.match(config, /NEXT_PUBLIC_BUILD_ID:\s*readBuildVersion\(\)/);
  assert.match(config, /public\/version\.json/);
  // On Cloudflare the config writes the file itself, whatever build command ran.
  assert.match(config, /CF_PAGES_COMMIT_SHA[\s\S]*writeFileSync\(file, want\)/);
  assert.match(read(".gitignore"), /^\/public\/version\.json$/m);
  assert.equal(fs.existsSync(path.join(web, "public/version.json")) && execFileSync("git", ["ls-files", "public/version.json"], { cwd: web }).toString().trim() !== "", false,
    "public/version.json is committed: every build would then start from somebody else's id");
});

test("the script writes a file the browser's rule accepts", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "build-version-"));
  fs.mkdirSync(path.join(dir, "scripts"));
  fs.mkdirSync(path.join(dir, "public"));
  fs.copyFileSync(path.join(web, "scripts/write-build-version.mjs"), path.join(dir, "scripts/write-build-version.mjs"));
  execFileSync(process.execPath, [path.join(dir, "scripts/write-build-version.mjs")], { env: { ...process.env, CF_PAGES_COMMIT_SHA: "0123abc0123abc0123abc0123abc0123abc01234" } });
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, "public/version.json"), "utf8")), { version: "0123abc0123abc0123abc0123abc0123abc01234" });
  fs.rmSync(dir, { recursive: true, force: true });
});

test("the notice is the signed-in shell's, asks the site's own origin without credentials or a cache, and loads only at a move or a press", () => {
  const shell = read("components/AppShell.tsx");
  assert.match(shell, /<NewVersionNotice pathname=\{realPathname\} \/>/);
  assert.ok(shell.indexOf("<NewVersionNotice") > shell.indexOf("if (!showShell)"), "the notice is drawn on the pages outside the shell too");
  const notice = code(read("components/shell/NewVersionNotice.tsx"));
  assert.match(notice, /fetchBounded\(`\$\{VERSION_PATH\}\?t=\$\{lastLookAt\.current\}`, \{ cache: "no-store", credentials: "omit" \}, "read"\)/);
  assert.doesNotMatch(notice, /[^A-Za-z.]fetch\(/, "the notice calls fetch itself: an unanswered look would never end");
  // A look the browser calls a failure (an outage, no network) or that throws says nothing: it never reaches `setLive`.
  const look = notice.slice(notice.indexOf("const look = useCallback("), notice.indexOf("}, []);"));
  assert.match(look, /if \(!res\.ok\) return;\s*const answered = readLiveVersion\(await res\.json\(\)\);\s*if \(isNewer\(BUILT, answered\)\) setLive\(answered\);/);
  assert.match(look, /\} catch \{\s*\} finally \{/);
  assert.equal([...look.matchAll(/setLive\(/g)].length, 1);
  assert.equal([...notice.matchAll(/window\.location\.reload\(\)/g)].length, 2, "the new build is loaded somewhere other than the move and the button");
  // The interval only LOOKS. A reload inside it would take a form away from somebody typing.
  const interval = notice.slice(notice.indexOf("window.setInterval("), notice.indexOf("document.addEventListener("));
  assert.doesNotMatch(interval, /reload|location/);
  assert.doesNotMatch(notice, /setTimeout/);
  // Remembered BEFORE the load, and no load when it cannot be remembered.
  const move = notice.slice(notice.indexOf("arrivedAt.current = pathname;"), notice.lastIndexOf("}, [pathname, live]);"));
  assert.match(move, /mayLoadOnMove\(live, loadedFor\(\)\)/);
  assert.match(move, /try \{ window\.sessionStorage\.setItem\(RELOADED_FOR_KEY, live\); \} catch \{ return; \}\s*window\.location\.reload\(\);/);
  // The card says nothing a person cannot use: no build id is drawn.
  assert.doesNotMatch(notice, /\{live\}|\{BUILT\}/);
  assert.match(notice, /print:hidden/);
});

test("the service worker never answers the version file from a cache", () => {
  const worker = read("public/sw.js");
  const isStatic = worker.match(/const isStaticAsset =([\s\S]*?);\n/);
  assert.ok(isStatic, "the worker no longer says what a static asset is");
  assert.doesNotMatch(isStatic[1], /json/, "a .json file is a static asset to the worker now: /version.json could be served stale");
  assert.doesNotMatch(worker, /version\.json/);
});
