#!/usr/bin/env node
/**
 * Open every screen in a real browser and report the ones that break.
 *
 * WHY THIS EXISTS. The client workspace is being rebuilt around a module hub.
 * The two static guards beside this one — the-redesign-cannot-lose-a-screen and
 * every-screen-has-a-way-in — prove a screen still EXISTS and is still LINKED.
 * Neither proves it still renders. A converted page that throws on mount, or
 * imports a component that no longer exports what it used to, passes both and
 * shows a CA a blank white rectangle.
 *
 * WHAT IT DOES. Builds nothing itself — run `pnpm build` first — then serves
 * `out/` (the Cloudflare static export, which is what a CA is actually served)
 * and loads all 159 routes in Chromium. Per route it records:
 *
 *   * an uncaught exception (`pageerror`) — always a failure;
 *   * a `console.error` — a failure, with the message, because that is where
 *     React reports a render it could not finish;
 *   * an empty body — a failure: something rendered nothing at all;
 *   * a request that escaped the stub — reported, not failed, so a screen
 *     reaching a host nobody expected is visible.
 *
 * IT NEEDS ITS OWN BUILD, and the reason is worth knowing before someone
 * "simplifies" it. The first version stubbed the real hosts with Playwright's
 * page.route(). That does not work: every authenticated call carries an
 * Authorization header, which makes it a non-simple cross-origin request, and
 * **Chromium does not surface a CORS preflight to page.route()** — the OPTIONS
 * goes to the real network, fails, and the GET behind it fails with
 * net::ERR_FAILED before the stub is ever consulted. Every screen then reports
 * "TypeError: Failed to fetch" and the walk says the whole product is broken.
 * The fix is to remove the cross-origin condition entirely: build with the API
 * and Supabase URLs pointing at this script's own server, so every call is
 * same-origin and no preflight exists.
 *
 *   pnpm smoke:build && node scripts/smoke-walk.mjs
 *
 * WHAT IT STUBS, AND WHY THAT IS HONEST. Every request to the API and to
 * Supabase is answered by the local server: `{success: true, data: [], error:
 * null}` for the API, `[]` for PostgREST, and a fake but well-formed session
 * for auth. So
 * this checks that a screen renders CORRECTLY WITH NO DATA — the empty-state
 * path, which is exactly the path a redesign is most likely to break and the
 * one a developer with a seeded database never sees. It does NOT check that
 * the numbers are right; the backend suite does that, and the two together are
 * the net.
 *
 * A dynamic segment is walked as `_placeholder`, which is the literal value
 * Cloudflare rewrites a real id to (see generate-redirects.js) — so this walks
 * the same HTML a CA's browser gets.
 *
 * NOT A CI CHECK. It needs a Chromium and a completed build, and it is meant
 * to be run BEFORE and AFTER converting a module, by the person converting it.
 *
 *   pnpm smoke:build && node scripts/smoke-walk.mjs
 *   node scripts/smoke-walk.mjs --only /clients --shots
 *
 * --only <prefix>  walk just the routes under a prefix
 * --shots          write a PNG per route to .smoke/ (the visual baseline —
 *                  NOT a regression gate; these are supposed to change)
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";


/**
 * Playwright is deliberately NOT a dependency of this package.
 *
 * It is a ~40MB install and CI never runs this walk, so adding it would put a
 * download on every frontend job to serve a tool only a developer converting a
 * module uses. Imported here instead, with the install instruction in the
 * failure — which is also the honest shape: this script needs a browser on the
 * machine, and a package.json entry would not have provided one.
 */
async function loadChromium() {
  try {
    const pw = await import("@playwright/test");
    return pw.chromium ?? pw.default?.chromium;
  } catch {
    console.error(
      "@playwright/test is not installed.\n" +
      "  cd apps/web && pnpm add -D @playwright/test\n" +
      "Then remove it again before committing — it is not a project dependency;\n" +
      "see the comment above loadChromium() for why.");
    process.exit(2);
  }
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const OUT = path.join(WEB, "out");
const SHOT_DIR = path.join(WEB, ".smoke");

// Playwright's own download is disabled in this environment
// (PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1) and the installed build may not be the
// one this @playwright/test version expects. Prefer whatever is on disk.
function installedChromium() {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  if (!fs.existsSync(root)) return undefined;
  for (const dir of fs.readdirSync(root).filter((d) => d.startsWith("chromium-")).sort().reverse()) {
    for (const rel of ["chrome-linux/chrome", "chrome-linux64/chrome"]) {
      const p = path.join(root, dir, rel);
      if (fs.existsSync(p)) return p;
    }
  }
  return undefined;
}

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
  ".ico": "image/x-icon", ".txt": "text/plain", ".woff2": "font/woff2",
};

/** The port smoke:build bakes into the bundle. Fixed, because the URLs are
 *  compiled in — a random port would not match what the pages call. */
const PORT = Number(process.env.SMOKE_PORT || 4319);

const FAKE_USER = {
  id: "00000000-0000-4000-8000-000000000001",
  aud: "authenticated", role: "authenticated",
  email: "smoke@example.invalid", app_metadata: {}, user_metadata: {},
  created_at: "2026-01-01T00:00:00Z",
};

const FAKE_SESSION = {
  access_token: "smoke.walk.token", token_type: "bearer", expires_in: 3600,
  expires_at: 4102444800, refresh_token: "smoke.refresh", user: FAKE_USER,
};

function sendJson(res, body, status = 200) {
  const s = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(s) });
  res.end(s);
}

/**
 * Serve out/ the way Cloudflare Pages does (/a/b/ -> out/a/b/index.html), and
 * answer the two stub prefixes the smoke build points the app at.
 *
 * The API answers the house envelope and the PostgREST prefix answers an empty
 * row set, so every screen renders its NO-DATA state. That is the state a
 * developer with a seeded database never looks at and a redesign most often
 * breaks — a table that assumes at least one row, a total that divides by a
 * length, a chart handed an empty series.
 */
function serve(root) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const url = decodeURIComponent(req.url.split("?")[0]);

      if (url.startsWith("/__supabase/auth/v1/")) {
        if (url.endsWith("/user")) return sendJson(res, FAKE_USER);
        if (url.endsWith("/logout")) return sendJson(res, {});
        return sendJson(res, { ...FAKE_SESSION });
      }
      if (url.startsWith("/__supabase/rest/v1/")) return sendJson(res, []);
      if (url.startsWith("/__supabase/storage/")) return sendJson(res, []);
      if (url.startsWith("/__supabase/")) return sendJson(res, {});
      if (url.startsWith("/__api/")) {
        return sendJson(res, { success: true, data: [], error: null });
      }

      let file = path.join(root, url);
      if (!path.extname(file)) file = path.join(file, "index.html");
      if (!file.startsWith(root) || !fs.existsSync(file)) {
        res.writeHead(404, { "content-type": "text/plain" });
        return res.end("not found");
      }
      res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
      fs.createReadStream(file).pipe(res);
    });
    server.listen(PORT, "127.0.0.1", () => resolve(server));
  });
}

/**
 * Refuse, and record, anything that is not this server.
 *
 * Belt to the same-origin braces: if a screen hard-codes a host, or a future
 * build forgets the smoke env, the walk says so by name rather than quietly
 * reaching the live API. NEXT_PUBLIC_API_URL in a normal build is the real
 * production service, so this is not hypothetical.
 */
async function sealOff(page, escaped) {
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (url.startsWith(`http://127.0.0.1:${PORT}`)) return route.continue();
    if (url.startsWith("data:") || url.startsWith("blob:")) return route.continue();
    try { escaped.add(new URL(url).host); } catch { escaped.add(url.slice(0, 40)); }
    return route.abort();
  });
}

/** supabase-js keys its persisted session on the URL's first hostname label,
 *  so a build pointed at 127.0.0.1 stores under "sb-127-auth-token". The
 *  others are written too: one of them is right for whatever URL the build
 *  actually carried, and an unread key costs nothing. */
function sessionScript() {
  const refs = ["127", "localhost", "placeholder"];
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const m = url.match(/https?:\/\/([^.:/]+)/);
  if (m) refs.push(m[1]);
  return `(() => { try {
    for (const ref of ${JSON.stringify(refs)})
      localStorage.setItem("sb-" + ref + "-auth-token", ${JSON.stringify(JSON.stringify(FAKE_SESSION))});
  } catch {} })();`;
}

const args = process.argv.slice(2);
const only = args.includes("--only") ? args[args.indexOf("--only") + 1] : null;
const shots = args.includes("--shots");

const routes = JSON.parse(fs.readFileSync(path.join(__dirname, "screens.snapshot.json"), "utf8"))
  .map((r) => r.replace(/:[^/]+/g, "_placeholder"))
  .filter((r) => (only ? r.startsWith(only) : true));

const escaped = new Set();
const captured = [];

if (!fs.existsSync(OUT)) {
  console.error("out/ does not exist — run `pnpm smoke:build` first.");
  process.exit(2);
}
// A build made without the smoke env still walks, but every call in it points
// at the real hosts, so sealOff aborts them and the walk reports the product
// as broken rather than the build as wrong. Say which it is.
if (!fs.readFileSync(path.join(OUT, "404.html"), "utf8").includes("__api")
    && !fs.readdirSync(path.join(OUT, "_next", "static", "chunks"))
         .some((f) => f.endsWith(".js") &&
               fs.readFileSync(path.join(OUT, "_next", "static", "chunks", f), "utf8").includes("/__api"))) {
  console.error(
    "This build does not point at the smoke server — its API URL is a real\n" +
    "host, so every screen would fail on an aborted request. Rebuild with:\n" +
    "  pnpm smoke:build");
  process.exit(2);
}

const server = await serve(OUT);
const chromium = await loadChromium();
const browser = await chromium.launch({ executablePath: installedChromium() });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await context.addInitScript(sessionScript());
if (shots) fs.mkdirSync(SHOT_DIR, { recursive: true });

const broken = [];
let walked = 0;

for (const route of routes) {
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`threw: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console.error: ${m.text().slice(0, 200)}`);
  });
  await sealOff(page, escaped);
  const url = `http://127.0.0.1:${PORT}${route.endsWith("/") ? route : route + "/"}`;
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });
    // Give effects that fetch-then-setState a beat to land.
    await page.waitForTimeout(400);
    const text = (await page.evaluate(() => document.body.innerText || "")).trim();
    if (!text) errors.push("rendered an empty body");
    if (shots) {
      // JPEG rather than PNG, and the reason is not disk: a full-page PNG of a
      // dense table is 1-2MB, and 159 of them cannot be carried anywhere as a
      // set — which is the only thing a baseline is for. At q72 the same page
      // is ~150KB and every difference a design review cares about survives.
      const name = (route === "/" ? "root" : route.slice(1).replace(/\//g, "_")) + ".jpg";
      await page.screenshot({
        path: path.join(SHOT_DIR, name), fullPage: true, type: "jpeg", quality: 72,
      });
      captured.push({ route, file: name });
    }
  } catch (e) {
    errors.push(`navigation failed: ${e.message.split("\n")[0]}`);
  }
  await page.close();
  walked++;
  if (errors.length) {
    broken.push({ route, errors: [...new Set(errors)] });
    process.stdout.write("X");
  } else {
    process.stdout.write(".");
  }
  if (walked % 60 === 0) process.stdout.write(` ${walked}\n`);
}

await browser.close();
server.close();

console.log(`\n\n${walked} screens walked, ${broken.length} with a problem.`);
for (const b of broken) {
  console.log(`\n  ${b.route}`);
  for (const e of b.errors.slice(0, 4)) console.log(`      ${e}`);
}
if (escaped.size) {
  console.log(
    `\nBLOCKED — a screen reached for a host that is not the smoke server: ` +
    `${[...escaped].join(", ")}.\nNothing was contacted; the request was aborted. ` +
    `A hard-coded host is a real defect.`);
}
if (shots) {
  // A contact sheet, so the set can be looked at as a set. This is the review
  // artifact the plan calls a "visual baseline": NOT a regression gate — these
  // are supposed to change — but the before-and-after a person judges.
  const cards = captured.map(({ route, file }) =>
    `<figure><a href="${file}"><img src="${file}" loading="lazy" alt="${route}"></a>` +
    `<figcaption>${route}</figcaption></figure>`).join("\n");
  fs.writeFileSync(path.join(SHOT_DIR, "index.html"),
    `<!doctype html><meta charset="utf-8"><title>PracticeSync screens</title>` +
    `<style>body{font:14px system-ui;margin:0;padding:24px;background:#F8FAFC;color:#0F172A}` +
    `h1{font-size:18px;margin:0 0 4px}p{color:#64748B;margin:0 0 24px}` +
    `.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}` +
    `figure{margin:0;background:#fff;border:1px solid #E2E8F0;border-radius:10px;overflow:hidden}` +
    `img{display:block;width:100%;height:220px;object-fit:cover;object-position:top}` +
    `figcaption{padding:8px 10px;font-size:12px;color:#334155;border-top:1px solid #F1F5F9;` +
    `overflow:hidden;text-overflow:ellipsis;white-space:nowrap}</style>` +
    `<h1>${captured.length} screens</h1><p>Rendered with no data, at 1440x900. ` +
    `Click a card for the full page.</p><div class="grid">${cards}</div>`);
  console.log(`\n${captured.length} screenshots and a contact sheet in ${SHOT_DIR}`);
}
process.exit(broken.length ? 1 : 0);
