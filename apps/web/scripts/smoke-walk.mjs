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
 *   * landing somewhere else — a failure naming the destination, because a
 *     guard that redirects is how this walk spent four days photographing the
 *     onboarding wizard and calling it green;
 *   * a body that too many OTHER routes also render — a failure at the end of
 *     the run, for the same reason one route cannot see;
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
 *   node scripts/smoke-walk.mjs --only /login --shots --anon
 *
 * --only <prefix>  walk just the routes under a prefix
 * --anon          do NOT sign in, so the sign-in screens render as
 *                 themselves. Looking only — see `anon` below.
 * --shots          write a PNG per route to .smoke/ (the visual baseline —
 *                  NOT a regression gate; these are supposed to change)
 */
import crypto from "node:crypto";
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

/**
 * THE ONE ROW WITHOUT WHICH THIS WALK SEES NOTHING.
 *
 * AuthGuard sits in the ROOT layout, so it wraps every screen.
 * `resolveUserContext` (lib/auth/AuthContext.tsx) reads the `users` table for
 * the signed-in auth id and sets `hasFirm` from `!!data?.firm_id`;
 * `mayRenderProtected` (lib/auth/guardDecision.ts) then returns false for
 * `hasFirm === false`, and AuthGuard renders null and redirects to
 * /onboarding.
 *
 * With this read answered `[]` — as every PostgREST read was until 16 Sep 2026
 * — that branch fires on every protected route, so the page component is never
 * invoked and the walk photographs the onboarding wizard instead of the
 * screen. Measured on the 12 Sep artefacts: 148 of 159 screenshots byte-
 * identical, zero of the fourteen modules ever rendered, and the run reported
 * green because a wizard has a non-empty body and throws nothing.
 *
 * Partner because it is the only role `core/permissions.py` gives every
 * resource: a narrower role would hide action controls and the walk would then
 * be proving that a screen renders with its buttons missing.
 */
const FAKE_USERS_ROW = {
  id: "00000000-0000-4000-8000-000000000002",
  auth_user_id: FAKE_USER.id,
  role: "Partner",
  firm_id: "00000000-0000-4000-8000-0000000000f1",
  full_name: "Smoke Walker",
};

/**
 * THE SECOND ROW, AND THE CHECK THAT FOUND IT.
 *
 * `app/DashboardContent.tsx` reads `firms.name` for the signed-in firm and
 * does `if (!firmMeta?.name) router.replace("/onboarding")`. With that read
 * answered null the product's FRONT DOOR bounced to the wizard — and so did
 * /login and /login/forgot-password, which send a signed-in visitor to /
 * and inherit its redirect.
 *
 * Nothing in the walk could see that until the landing check went in on
 * 16 Sep: the onboarding wizard renders, has a non-empty body and throws
 * nothing, so / passed every per-route check while never once photographing
 * the dashboard. That is the same defect as the users row, one read further
 * in, which is the argument for a check that asks WHERE you ended up rather
 * than whether something appeared.
 *
 * `name` is the only column read. This is still not a seeded product — T2 is
 * — it is the second row the guard chain needs to let a screen run.
 */
const FAKE_FIRM_ROW = {
  id: FAKE_USERS_ROW.firm_id,
  name: "Smoke & Co., Chartered Accountants",
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
      if (url.startsWith("/__supabase/rest/v1/")) {
        // `.single()` / `.maybeSingle()` ask PostgREST for ONE OBJECT via the
        // Accept header, and supabase-js does not unwrap an array when it did.
        // Discriminating on the header rather than on the path is how
        // PostgREST itself decides, so this stays right for a caller added
        // later.
        const wantsObject = String(req.headers.accept || "")
          .includes("vnd.pgrst.object+json");
        if (url.startsWith("/__supabase/rest/v1/users")) {
          return sendJson(res, wantsObject ? FAKE_USERS_ROW : [FAKE_USERS_ROW]);
        }
        if (url.startsWith("/__supabase/rest/v1/firms")) {
          return sendJson(res, wantsObject ? FAKE_FIRM_ROW : [FAKE_FIRM_ROW]);
        }
        // Everything else stays EMPTY, deliberately. The no-data state is the
        // one a developer with a seeded database never looks at and the one a
        // redesign most often breaks — see the note above `serve`. This row
        // exists to get past the guard, not to seed the product.
        return sendJson(res, wantsObject ? null : []);
      }
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

/**
 * HOW MANY ROUTES MAY RENDER THE SAME THING BEFORE THAT IS THE FINDING.
 *
 * On 12 September this walk exited 0 with 148 of its 159 screenshots byte-
 * identical. Every protected route had been redirected to the onboarding
 * wizard by AuthGuard, and a wizard has a non-empty body and throws nothing,
 * so every per-route check passed. Nothing in the run could see the shape of
 * the SET, which is where that failure lived.
 *
 * Five is not a tolerance for sameness — it is the point past which sameness
 * stops being a coincidence. Real duplicates exist and are legitimate: a
 * handful of routes render the same "not found" body because the walk feeds
 * every :id a placeholder that resolves to nothing. Those come in twos and
 * threes. A guard that could not survive them would be turned off.
 *
 * The digest is of the body TEXT, not of the screenshot, although the plan
 * item said md5-of-screenshot. Text is available on every run and the
 * screenshot only under --shots, so a JPEG rule would have been off by
 * default — which is exactly the shape of defect this is for. It is also the
 * more honest comparison: two screens can differ by a chart and agree on
 * every word, and it is the words that say which screen you are on.
 *
 * WHAT THE HEADROOM ACTUALLY IS TODAY: one group of five, and it sits exactly
 * on the limit. /clients/_placeholder/{overview, sales, purchases, inventory,
 * accounting/journal/_placeholder/edit} all render the workspace shell over
 * "Loading…" and nothing else, because the walk feeds every :id the string
 * "_placeholder" and the workspace never resolves a client. A seeded demo
 * firm (T2) is what fixes that; until then a SIXTH such screen trips this
 * check, and it should — six screens showing a CA nothing but navigation is
 * the finding, not the false alarm.
 */
const MAX_ROUTES_PER_DIGEST = 5;

/**
 * THE ROUTES THAT LEGITIMATELY SEND YOU SOMEWHERE ELSE, AND WHERE TO.
 *
 * The landing check is only worth having if it cannot be satisfied by
 * "something rendered". These six are the redirects this product actually
 * means, each pinned to its DESTINATION — so the day one of them starts
 * bouncing somewhere new, the run still fails and says where.
 *
 * Every one of them was MEASURED by turning the check on, not written from
 * memory. The first run also caught three that were not legitimate at all —
 * /, /login and /login/forgot-password all landed on /onboarding, because
 * DashboardContent reads `firms.name` and the stub answered null. That is
 * fixed at the stub (see FAKE_FIRM_ROW), not excused here.
 */
const EXPECTED_LANDINGS = {
  // A signed-in visitor has no business on the sign-in pages.
  "/login": "/",
  "/login/forgot-password": "/",
  // …nor in the wizard, once their user row carries a firm.
  "/onboarding": "/",
  // Self-gated above the firm: not on the platform_admins allowlist, so it
  // sends you back to the product. See app/platform/page.tsx.
  "/platform": "/",
  // An index that has no page of its own.
  "/portal": "/portal/dashboard",
  // The walk feeds every :id the string "_placeholder", which resolves to no
  // client, and the workspace index returns to the list rather than showing a
  // shell for a client that is not there. A seeded demo firm (T2) is what
  // removes this entry, not a change here.
  "/clients/_placeholder": "/clients",
};

const args = process.argv.slice(2);
const only = args.includes("--only") ? args[args.indexOf("--only") + 1] : null;
const shots = args.includes("--shots");
/**
 * THE SIX SCREENS EVERY USER SEES FIRST ARE THE SIX THIS WALK COULD NOT SEE.
 *
 * The walk signs in — `sessionScript()` puts a session in localStorage before
 * the first paint — because that is what makes the other 154 routes render at
 * all. The cost is exactly the signed-OUT surface: `/login` and
 * `/login/forgot-password` bounce to `/`, so their shots are pictures of the
 * dashboard, and EXPECTED_LANDINGS pins that bounce as correct. Found while
 * converting the auth family's type sizes (D12): four of its six screens could
 * be photographed and two could not, and those two are the product's front
 * door.
 *
 * `--anon` skips the session. It is for LOOKING, not for gating: signed out,
 * every protected route redirects to the same sign-in page, so the landing
 * pins and the duplicate-body check are both meaningless and are SKIPPED
 * rather than quietly satisfied — a run that reported "150 distinct bodies"
 * while photographing one page 154 times would be worse than no run. Use it
 * with `--only`, and the run says so if you do not.
 */
const anon = args.includes("--anon");

const routes = JSON.parse(fs.readFileSync(path.join(__dirname, "screens.snapshot.json"), "utf8"))
  .map((r) => r.replace(/:[^/]+/g, "_placeholder"))
  .filter((r) => (only ? r.startsWith(only) : true));

const escaped = new Set();
const captured = [];
const rendered = [];
const redirected = [];

const trim = (p) => (p.endsWith("/") && p !== "/" ? p.slice(0, -1) : p);
// Whitespace is collapsed so a reflow cannot read as a different screen.
const digestOf = (text) => crypto.createHash("sha1")
  .update(text.replace(/\s+/g, " ").trim()).digest("hex").slice(0, 12);

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
if (!anon) await context.addInitScript(sessionScript());
if (anon) {
  console.log("--anon: signed out. Landing pins and the duplicate-body check " +
              "are skipped — see the comment on `anon`." +
              (only ? "" : "  NO --only: every protected route will redirect " +
               "to the sign-in page, which is not a walk of anything."));
}
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

    // WHERE IT LANDED, not whether something rendered. AuthGuard, an
    // onboarding gate or a module index that bounces elsewhere all leave a
    // perfectly good page on screen — somebody else's.
    const landed = trim(new URL(page.url()).pathname);
    const expected = EXPECTED_LANDINGS[route];
    // Signed out, every pin in that map describes a redirect that only holds
    // for a signed-IN visitor. Asserting them here would fail the run for
    // behaving correctly.
    if (!anon && landed !== trim(new URL(url).pathname)) {
      if (expected === undefined) {
        errors.push(`landed on ${landed}, not the route asked for`);
      } else if (landed !== trim(expected)) {
        errors.push(`redirects to ${landed}; it is pinned to ${expected}`);
      } else {
        redirected.push({ route, to: landed });
      }
    }
    // A route that redirects renders the DESTINATION's body, so counting it
    // among the duplicates would report the allowlist back to us as a herd.
    if (landed === trim(new URL(url).pathname)) {
      rendered.push({ route, digest: digestOf(text), sample: text.slice(0, 60) });
    }
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

// THE CHECK NO SINGLE ROUTE CAN MAKE. See MAX_ROUTES_PER_DIGEST above.
const byDigest = new Map();
for (const r of rendered) {
  if (!byDigest.has(r.digest)) byDigest.set(r.digest, []);
  byDigest.get(r.digest).push(r);
}
const herds = [...byDigest.values()]
  .filter((g) => g.length > MAX_ROUTES_PER_DIGEST)
  .sort((a, b) => b.length - a.length);
if (redirected.length) {
  console.log(`\n${redirected.length} routes redirected as pinned: ` +
              redirected.map((r) => `${r.route} -> ${r.to}`).join(", "));
}

const groups = [...byDigest.values()].sort((a, b) => b.length - a.length);
console.log(`${byDigest.size} distinct bodies across the ${rendered.length} routes that stayed put.`);
// Every group of three or more is printed even when it passes, so the headroom
// under MAX_ROUTES_PER_DIGEST is visible rather than something a reader has to
// go and measure. A run that is one route away from the limit should say so.
for (const g of groups.filter((g) => g.length >= 3 && g.length <= MAX_ROUTES_PER_DIGEST)) {
  console.log(`  ${g.length} routes share a body (allowed ${MAX_ROUTES_PER_DIGEST}), ` +
              `beginning ${JSON.stringify(g[0].sample)}:`);
  console.log(`      ${g.map((r) => r.route).join(", ")}`);
}
for (const herd of herds) {
  console.log(
    `\n  ${herd.length} routes render the SAME body — more than ` +
    `${MAX_ROUTES_PER_DIGEST}, so this is a redirect or a shared refusal, ` +
    `not a coincidence:`);
  console.log(`      it begins: ${JSON.stringify(herd[0].sample)}`);
  for (const r of herd.slice(0, 8)) console.log(`      ${r.route}`);
  if (herd.length > 8) console.log(`      ...and ${herd.length - 8} more`);
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
process.exit(broken.length || (!anon && herds.length) ? 1 : 0);
