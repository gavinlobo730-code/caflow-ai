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
 * WITH THE HEADERS IT SHIPS (security_privacy-05). `out/_headers` is applied to every static response exactly
 * as Cloudflare Pages would apply it, and a `securitypolicyviolation` event (enforced OR report-only) is a
 * broken screen, beside the console error an enforced violation also logs. A Content-Security-Policy that is
 * wrong takes every screen down and says so only in a console nobody has open; this is the place it is caught.
 * The build writes the file (`security-headers.mjs`, after `next build`); a build without it is refused,
 * and `--no-headers` walks without one on purpose. Same-origin stubs mean the walk cannot prove that the
 * REAL API and Supabase hosts are in connect-src — the generator's tests hold that, from the deployed
 * configuration — only that nothing the screens do needs a directive the policy lacks.
 *
 * A dynamic segment is walked as `_placeholder`, which is the literal value
 * Cloudflare rewrites a real id to (see generate-redirects.js) — so this walks
 * the same HTML a CA's browser gets.
 *
 * NOT A PULL-REQUEST CHECK, AND NOT A REQUIRED ONE. It needs a Chromium and a
 * completed build, so it does not run on every PR. It is meant to be run BEFORE
 * and AFTER converting a module, by the person converting it, and it ALSO runs
 * by itself: nightly and on demand in `.github/workflows/smoke-walk.yml`
 * (engineering-15), which builds the export, installs Playwright in that job
 * only, and uploads the `--report` below. Thirteen screens crashed the first
 * time this walk could render them (CLAUDE.md), and nothing had walked it since
 * but a person: a blank screen could ship and wait for a CA to find it.
 *
 *   pnpm smoke:build && node scripts/smoke-walk.mjs
 *   node scripts/smoke-walk.mjs --only /clients --real-client --shots
 *   node scripts/smoke-walk.mjs --only /login --shots --anon
 *   node scripts/smoke-walk.mjs --report .smoke/report.json
 *
 * ACCESSIBILITY AND THE SLOW SERVER (frontend_ux-03, frontend_ux-05). The walk also scans pages with axe and
 * drives the slow-server notice, and both change the verdict:
 *
 *   * axe (`scripts/axeAudit.mjs` has the rules): the SIX NAMED SCREENS — sign in, sign up, the dashboard,
 *     a client's sales, the journal editor, the firm menu opened — fail on any serious or critical WCAG A/AA
 *     violation, with no allowlist; every other walked route is held by `scripts/axe-baseline.json`, a ratchet
 *     that may only shrink. It needs `@axe-core/playwright`, which the workflow adds to the walk's own job
 *     (never a dependency of the product). Missing locally it is SKIPPED WITH A LOUD LINE; missing in CI it
 *     exits 2; a run that scanned no page exits 2. `--no-axe` turns it off, `--axe-init` writes the first
 *     baseline (and refuses to overwrite one), `--axe-shrink` lowers it and never raises it.
 *   * the slow-server notice: on a full walk the stub API is held for 24 s on /tasks and the run asserts the
 *     waking-up sentence appears once at about three seconds, a Retry at about twenty, and that both go with
 *     the data. `--slow-server` forces it on a partial walk, `--no-slow-server` skips it (about half a minute).
 *
 * --only <prefix>  walk just the routes under a prefix
 * --report <file>  also write the verdict as JSON (every broken route and its
 *                  errors, the herds, the redirects, how long each screen took),
 *                  and, under GitHub Actions, a table on the run's summary page.
 *                  The exit code is unchanged: 1 when any screen is broken.
 * --no-headers    walk WITHOUT out/_headers (the build is then not the product as served)
 * --anon          do NOT sign in, so the sign-in screens render as
 *                 themselves. Looking only — see `anon` below.
 * --shots          write a PNG per route to .smoke/ (the visual baseline —
 *                  NOT a regression gate; these are supposed to change)
 * --real-client    put a UUID in /clients/:id instead of the static-export
 *                  placeholder, so the CLIENT WORKSPACE renders its own shell.
 *                  Without it every client screen wears the firm chrome and
 *                  this walk cannot see the workspace at all — see `realClient`
 */
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { screenRoutes } from "./refresh-screen-snapshot.js";
import { headersFor, parseHeadersFile } from "./security-headers.mjs";
import {
  AXE_PACKAGE_VERSION, NAMED_ROUTE_PATHS, auditPage, axeMode, compareToBaseline, describeFailure,
  initialBaseline, loadAxeBuilder, parseBaseline, serialiseBaseline, settleVerdict, shrinkBaseline,
  summaryMarkdown,
} from "./axeAudit.mjs";
import { auditNamedScreens, slowServerScenario } from "./walkAudits.mjs";


/**
 * Playwright is deliberately NOT a dependency of this package.
 *
 * It is a ~40MB install, and the frontend CI job that runs on every pull request
 * does not need it: adding it would put a download on every one of those jobs to
 * serve a walk that runs nightly and on demand. The workflow that runs the walk
 * (`.github/workflows/smoke-walk.yml`) installs it in its OWN job, with a pinned
 * version, and the script imports it here with the install instruction in the
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
 * What the slow-server scenario turns up and reads back (frontend_ux-05).
 *
 * `apiDelayMs` holds back every DATA answer — the API and the PostgREST reads — by that long, which is what a
 * sleeping Render instance does to a screen. It is 0 for the whole route walk. The two reads the sign-in guard
 * needs (`users`, `firms`) and the auth endpoints are never held, so the screen itself renders and only its
 * data is slow, which is the case being tested. `requests` is every data request seen, so the scenario can
 * say that pressing Retry really asked the server again.
 */
const stub = { apiDelayMs: 0, requests: [] };

/** Answer a data request, after the scenario's delay if it has set one. A request the browser has already
 *  abandoned (the page closed) is not answered. */
function sendData(res, body, status = 200) {
  if (stub.apiDelayMs <= 0) return sendJson(res, body, status);
  setTimeout(() => { if (!res.destroyed && !res.writableEnded) sendJson(res, body, status); }, stub.apiDelayMs);
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
function serve(root, headerRules = []) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const url = decodeURIComponent(req.url.split("?")[0]);
      // The headers Cloudflare Pages would add to a static asset (security_privacy-05): the SAME file the
      // deploy ships, parsed by the same function the generator's tests use, applied to every static
      // response and not to the two stub prefixes (they stand in for other hosts, not for assets).
      const siteHeaders = headersFor(headerRules, url);

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
        stub.requests.push(url);
        return sendData(res, wantsObject ? null : []);
      }
      if (url.startsWith("/__supabase/storage/")) return sendJson(res, []);
      if (url.startsWith("/__supabase/")) return sendJson(res, {});
      if (url.startsWith("/__api/")) {
        stub.requests.push(url);
        // /health is the keep-alive's own ping and must stay instant whatever the scenario is doing.
        return url.startsWith("/__api/health")
          ? sendJson(res, { success: true, data: [], error: null })
          : sendData(res, { success: true, data: [], error: null });
      }

      // Cloudflare serves EVERY /clients/<uuid>/… from the one _placeholder
      // build (that rewrite is what D10's redirect budget pays for), and this
      // server did not — so a uuid URL 404'd and the walk could only ever ask
      // for /clients/_placeholder/…, which `isClientWorkspacePath` deliberately
      // rejects. The consequence is worth spelling out: for the whole life of
      // this tool it rendered the FIRM chrome over every client screen and so
      // could not see the client workspace at all — the half its own header
      // says it exists for. Mirroring the rewrite is what `--real-client` needs.
      // …and so does every OTHER dynamic segment (an entry id, an invoice id): a
      // static export builds one page per route SHAPE, and `_redirects` sends any
      // real id to it. The named-screen scan asks for `/journal/new/edit`, the
      // create-mode sentinel, and that has to land on the one built page.
      const file = resolveBuiltFile(root, url);
      if (!file) {
        res.writeHead(404, { ...siteHeaders, "content-type": "text/plain" });
        return res.end("not found");
      }
      res.writeHead(200, { ...siteHeaders, "content-type": MIME[path.extname(file)] || "application/octet-stream" });
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
  // Three more that were deliberate before this walk ran by itself and that the list had not
  // caught up with (engineering-15: the first full run on a clean tree reported exactly these
  // three and nothing else, which on a nightly would have been a red run on day one for a
  // false alarm). Each is pinned to what its OWN file says:
  //   /signup: a signed-in visitor who already has a firm is bounced, the mirror of /login
  //     (lib/auth/guardDecision `shouldBounceFromSignup`; sweep-auth-and-public-02).
  "/signup": "/",
  //   the two redirect stubs, kept so a bookmark or an emailed link still lands somewhere (a
  //   static export has no server-side redirect to issue).
  "/onboarding/checklist": "/clients/onboarding",
  "/team/work-allocation": "/team/workload",
  // The walk feeds every :id the string "_placeholder", which resolves to no
  // client, and the workspace index returns to the list rather than showing a
  // shell for a client that is not there. A seeded demo firm (T2) is what
  // removes this entry, not a change here.
  "/clients/_placeholder": "/clients",
};

const args = process.argv.slice(2);
const only = args.includes("--only") ? args[args.indexOf("--only") + 1] : null;
const shots = args.includes("--shots");
/** `--no-axe` skips the accessibility scan; `--axe-init` / `--axe-shrink` write scripts/axe-baseline.json (see
 *  axeAudit.mjs). `--slow-server` / `--no-slow-server` force or skip the slow-server scenario. */
const noAxe = args.includes("--no-axe");
const axeInit = args.includes("--axe-init");
const axeShrink = args.includes("--axe-shrink");
const BASELINE_FILE = path.join(__dirname, "axe-baseline.json");
if (axeInit && axeShrink) {
  console.error("--axe-init and --axe-shrink are two different writes; pass one.");
  process.exit(2);
}
if ((axeInit || axeShrink) && noAxe) {
  console.error("--axe-init and --axe-shrink need the scan; drop --no-axe.");
  process.exit(2);
}
const reportPath = args.includes("--report") ? args[args.indexOf("--report") + 1] : null;
if (args.includes("--report") && (!reportPath || reportPath.startsWith("--"))) {
  console.error("--report needs a file path, e.g. --report .smoke/report.json");
  process.exit(2);
}
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

/**
 * `--real-client` walks the client workspace AS A CA SEES IT.
 *
 * `isClientWorkspacePath` requires a real UUID, precisely so the static-export
 * placeholder cannot be mistaken for a workspace — so at
 * /clients/_placeholder/… the shell renders the FIRM panel, and every client
 * screen this walk has ever photographed was wearing the wrong chrome. With a
 * UUID in the URL the shell renders the client's own sections, which is what
 * needs looking at whenever the workspace changes.
 *
 * Only the CLIENT id becomes a uuid. Every other dynamic segment stays
 * `_placeholder`, because those are record ids (an invoice, a journal entry)
 * and the build has one page per shape, not per record.
 */
const realClient = args.includes("--real-client");
const CLIENT_UUID = "00000000-0000-4000-8000-000000000001";

/**
 * ⚠️ THE ROUTE LIST IS THE LIVE `app/` TREE, AND IT USED TO BE
 * `screens.snapshot.json`. Those answer different questions and the walk was
 * asking the wrong one.
 *
 * The snapshot is a RECORD of the screens the product had when somebody last
 * looked — `the-redesign-cannot-lose-a-screen.test.ts` uses it to catch a
 * DELETION, and additions pass by design, because a redesign is expected to
 * add screens. Nothing regenerates it. So on 24-09 three new pages were built,
 * rendered, linked and passed every test in the repository while this walk
 * silently never visited one of them — the shots said the module was fine and
 * the module had three screens nobody had looked at.
 *
 * What a smoke walk is for is "render everything that exists NOW", which is
 * exactly `screenRoutes(app/)` — the same function that WRITES the snapshot,
 * so the two cannot disagree about what a route looks like. The snapshot keeps
 * its own job and needs no refresh for this one.
 */
const allRoutes = screenRoutes(path.join(__dirname, "..", "app"));

/**
 * `--at <path>` walks exactly the paths given, verbatim, INCLUDING A QUERY
 * STRING — and it exists because of a hole this walk has always had.
 *
 * ⚠️ THE WALK PHOTOGRAPHS ONE TAB PER ROUTE. A tabbed screen keeps its tab in
 * `?tab=`, and the route list carries no query, so the client accounting page
 * — twelve tabs — has only ever been looked at on `dashboard`. Eleven panels
 * behind it, and the same on GST, sales, payroll and the rest, have never
 * appeared in a single shot. That is exactly where a panel can render a header
 * over nothing and no walk notice, which is the defect this run was written to
 * catch on `/practice/profitability` and did.
 *
 * This is the SPOT CHECK, not the fix. Walking every tab means reading each
 * page's own `TABS` const out of its source, which is a real piece of work and
 * its own change; `--at` lets a person look at the one they just built. A run
 * using it is deliberately NOT a clean-tree run: the floor below is skipped
 * for the same reason `--only` skips it.
 */
const at = args.reduce(
  (acc, a, i) => (a === "--at" && args[i + 1] ? [...acc, args[i + 1]] : acc),
  [],
);

const routes = at.length
  ? at
  : allRoutes
      .map((r) => (realClient ? r.replace("/clients/:id", `/clients/${CLIENT_UUID}`) : r))
      .map((r) => r.replace(/:[^/]+/g, "_placeholder"))
      .filter((r) => (only ? r.startsWith(only) : true));

/** A walk of part of the product: nothing that needs the whole set (the floor, the duplicate-body check, the
 *  baseline's writes) is judged on it. */
const partial = Boolean(only) || at.length > 0;
if ((axeInit || axeShrink) && (partial || anon)) {
  console.error("--axe-init and --axe-shrink rewrite the baseline from what was found, so they need a full signed-in " +
    "walk: no --only, no --at, no --anon.");
  process.exit(2);
}
/** The slow-server scenario holds the API for ~25 s, so it runs on a full walk and on request, not on a spot check. */
const runSlowServer = args.includes("--slow-server") ||
  (!args.includes("--no-slow-server") && !partial && !anon);

// A truncated tree makes every assertion below vacuous, the same floor the
// snapshot guard keeps. 120 was its number on a tree of 159.
if (!only && !at.length && allRoutes.length < 120) {
  console.error(
    `smoke-walk: only ${allRoutes.length} routes found under app/ — the tree ` +
      `walk has probably broken. Refusing to report a clean run over nothing.`,
  );
  process.exit(1);
}

/** Any /clients/<uuid>/ prefix, which the server rewrites to the one built
 *  _placeholder page exactly as Cloudflare does. */
const CLIENT_UUID_SEG =
  /^\/clients\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\//i;

/** Each dynamic route shape and the one page the export built for it (`:id` -> `_placeholder`). */
const DYNAMIC_ROUTES = allRoutes.filter((r) => r.includes(":")).map((r) => ({
  shape: new RegExp(`^${r.replace(/:[^/]+/g, "[^/]+")}/?$`),
  built: r.replace(/:[^/]+/g, "_placeholder"),
}));

/** The file the export serves for `url`, as Cloudflare would: the page as asked, then the client-uuid rewrite,
 *  then any dynamic route's placeholder page. null is a 404. */
function resolveBuiltFile(root, url) {
  const attempts = [url.replace(CLIENT_UUID_SEG, "/clients/_placeholder/")];
  const shaped = DYNAMIC_ROUTES.find((d) => d.shape.test(url));
  if (shaped) attempts.push(shaped.built);
  for (const attempt of attempts) {
    let file = path.join(root, attempt);
    if (!path.extname(file)) file = path.join(file, "index.html");
    if (file.startsWith(root) && fs.existsSync(file)) return file;
  }
  return null;
}

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

// THE PRODUCT IS WALKED WITH THE HEADERS IT SHIPS (security_privacy-05). A Content-Security-Policy that is
// wrong takes every screen down and says so only in a console nobody has open, so the walk applies
// out/_headers exactly as Cloudflare would and counts a policy violation as a broken screen (below).
// `pnpm build` and `pnpm smoke:build` both write the file. A build without it is not the product as served,
// so the walk refuses it rather than quietly walking something else; `--no-headers` is the explicit way out.
let headerRules = [];
let cspState = "not applied (--no-headers)";
if (args.includes("--no-headers")) {
  console.log("--no-headers: walking WITHOUT out/_headers. This is not the product as it is served.");
} else {
  const headersFile = path.join(OUT, "_headers");
  if (!fs.existsSync(headersFile)) {
    console.error(
      "out/_headers does not exist, so this build is not the product as served.\n" +
      "  pnpm smoke:build     (writes it after `next build`)\n" +
      "or pass --no-headers to walk without them on purpose.");
    process.exit(2);
  }
  headerRules = parseHeadersFile(fs.readFileSync(headersFile, "utf8"));
  const served = headersFor(headerRules, "/");
  cspState = served["content-security-policy"] ? "enforced"
    : served["content-security-policy-report-only"] ? "REPORT-ONLY" : "ABSENT";
  console.log(`Security headers: ${Object.keys(served).length} applied to every static response; CSP ${cspState}.`);
}

const server = await serve(OUT, headerRules);
const chromium = await loadChromium();
const browser = await chromium.launch({ executablePath: installedChromium() });
const VIEWPORT = { width: 1440, height: 900 };
const context = await browser.newContext({ viewport: VIEWPORT });

// The accessibility scan (frontend_ux-03; scripts/axeAudit.mjs has the rules). Decided BEFORE the walk so a run
// that cannot scan says so first, and in CI says so by failing.
const axeLoaded = noAxe ? { error: "--no-axe" } : await loadAxeBuilder();
const axe = axeMode({
  disabled: noAxe, loaded: Boolean(axeLoaded.AxeBuilder), ci: process.env.GITHUB_ACTIONS === "true",
});
console.log(axe.line);
if (axe.fatal) {
  await browser.close();
  server.close();
  process.exit(2);
}
// Signed out, every protected route is the sign-in page, so a route-by-route scan would be a scan of one page
// 170 times. The six named screens are scanned in their own contexts either way.
const scanRoutes = axe.run && !anon;
if (axe.run && anon) console.log("axe: the route walk is signed out, so only the six named screens are scanned.");
/** route -> serious/critical findings, for every walked route axe scanned. */
const axeFound = new Map();
/** Pages axe could not scan, which make the run unable to certify anything about them. */
const axeUnaudited = [];
if (!anon) await context.addInitScript(sessionScript());
// A policy violation is an EVENT as well as a console line, and a report-only policy produces the event with
// no console error at all, so the console listener below cannot be the only thing that sees one. Registered
// before any page script runs, read back per route.
await context.addInitScript(() => {
  document.addEventListener("securitypolicyviolation", (e) => {
    const w = /** @type {any} */ (window);
    (w.__cspViolations = w.__cspViolations || []).push(
      `${e.effectiveDirective} blocked ${e.blockedURI || "inline"} (${e.disposition})`);
  });
});
if (anon) {
  console.log("--anon: signed out. Landing pins and the duplicate-body check " +
              "are skipped — see the comment on `anon`." +
              (only ? "" : "  NO --only: every protected route will redirect " +
               "to the sign-in page, which is not a walk of anything."));
}
if (shots) fs.mkdirSync(SHOT_DIR, { recursive: true });

const broken = [];
const timings = [];            // how long each screen took to settle, for --report
const walkStarted = Date.now();
let walked = 0;

for (const route of routes) {
  const routeStarted = Date.now();
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`threw: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console.error: ${m.text().slice(0, 200)}`);
  });
  await sealOff(page, escaped);
  // ⚠️ THE TRAILING SLASH GOES ON THE PATH, NOT AFTER THE QUERY. The static
  // export serves directory-style paths, so every route needs one — but
  // `route + "/"` on `/x/accounting?tab=reports` yields `?tab=reports/`, and
  // the value that reaches the screen is `reports/`, which matches no tab id
  // and silently falls back to the default. The first `--at` run photographed
  // the Dashboard tab believing it was Reports, which is exactly the kind of
  // quiet wrong answer this walk exists to stop.
  const [routePath, routeQuery = ""] = route.split("?");
  const withSlash = routePath.endsWith("/") ? routePath : routePath + "/";
  const url =
    `http://127.0.0.1:${PORT}${withSlash}${routeQuery ? "?" + routeQuery : ""}`;
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });
    // Give effects that fetch-then-setState a beat to land.
    await page.waitForTimeout(400);
    const text = (await page.evaluate(() => document.body.innerText || "")).trim();
    if (!text) errors.push("rendered an empty body");
    const violations = await page.evaluate(() => /** @type {any} */ (window).__cspViolations || []);
    for (const v of violations) errors.push(`CSP violation: ${String(v).slice(0, 200)}`);

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
      // The accessibility scan, on the page as it stands: only where it STAYED PUT (a redirect is the
      // destination's page, scanned under its own route) and not on a route a named screen covers (that scan is
      // stricter and its own).
      if (scanRoutes && text && !NAMED_ROUTE_PATHS.has(trim(routePath))) {
        const scan = await auditPage(axeLoaded.AxeBuilder, page);
        if (scan.error) axeUnaudited.push({ route: trim(routePath), error: scan.error });
        else axeFound.set(trim(routePath), scan.findings);
      }
    }
    if (shots) {
      // JPEG rather than PNG, and the reason is not disk: a full-page PNG of a
      // dense table is 1-2MB, and 159 of them cannot be carried anywhere as a
      // set — which is the only thing a baseline is for. At q72 the same page
      // is ~150KB and every difference a design review cares about survives.
      const name = (route === "/" ? "root" : route.slice(1).replace(/[/?=&]/g, "_")) + ".jpg";
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
  timings.push({ route, ms: Date.now() - routeStarted });
  if (errors.length) {
    broken.push({ route, errors: [...new Set(errors)] });
    process.stdout.write("X");
  } else {
    process.stdout.write(".");
  }
  if (walked % 60 === 0) process.stdout.write(` ${walked}\n`);
}

// The six named screens, each on a page of its own and in the context it needs (signed out for the two
// sign-in screens). They are scanned whatever the route walk did, and a screen that did not land where it was
// asked is a failure, not a clean row.
let axeNamed = [];
if (axe.run) {
  process.stdout.write("\n\naxe: scanning the six named screens … ");
  axeNamed = await auditNamedScreens({
    browser, AxeBuilder: axeLoaded.AxeBuilder, port: PORT, clientId: CLIENT_UUID, viewport: VIEWPORT,
    sessionScript, sealOff, escaped,
  });
  console.log("done.");
}

// The slow-server notice, against an API that takes 24 s (frontend_ux-05). Holds the walk for about half a minute.
let slowProblems = null;
if (runSlowServer) {
  process.stdout.write("slow-server notice: holding the API for 24 s on /tasks … ");
  slowProblems = await slowServerScenario({ context, port: PORT, stub, sealOff, escaped });
  console.log(slowProblems.length ? "FAILED." : "held.");
}

await browser.close();
server.close();

console.log(`\n\n${walked} screens walked, ${broken.length} with a problem.`);
for (const b of broken) {
  console.log(`\n  ${b.route}`);
  for (const e of b.errors.slice(0, 4)) console.log(`      ${e}`);
}
if (process.env.GITHUB_ACTIONS === "true") {
  // The route NAME on the run's summary page, not only in the log. GitHub shows
  // ten annotations per step, so the first ten; --report's table has them all.
  for (const b of broken.slice(0, 10)) {
    const first = b.errors[0].replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
    console.log(`::error title=Smoke walk: ${b.route} is broken::${first.slice(0, 300)}`);
  }
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
// ── The accessibility verdict (frontend_ux-03; scripts/axeAudit.mjs) ─────────────────────────────────────
//
// The six named screens fail outright. Every other walked route is held by scripts/axe-baseline.json, a
// ratchet that may only shrink. `--axe-init` writes the first one and refuses to overwrite; `--axe-shrink`
// lowers counts and deletes fixed lines and never adds or raises.
let axeVerdict = null;
if (axe.run) {
  let entries = [];
  const baselineText = fs.existsSync(BASELINE_FILE) ? fs.readFileSync(BASELINE_FILE, "utf8") : null;
  if (baselineText !== null) {
    try { entries = parseBaseline(baselineText); } catch (e) {
      console.error(`axe: ${e.message}`);
      process.exit(2);
    }
  }
  if (axeInit) {
    if (baselineText !== null) {
      console.error("axe: --axe-init refuses to overwrite scripts/axe-baseline.json. Delete it on purpose if a " +
        "fresh baseline is what you mean (it should only ever shrink).");
      process.exit(2);
    }
    if (axeUnaudited.length) {
      console.error(`axe: --axe-init needs every page scanned, and ${axeUnaudited.length} could not be.`);
      process.exit(2);
    }
    entries = initialBaseline(axeFound);
    fs.writeFileSync(BASELINE_FILE, serialiseBaseline(entries));
    console.log(`axe: wrote ${entries.length} baseline line(s) to scripts/axe-baseline.json.`);
  } else if (axeShrink) {
    const shrunk = shrinkBaseline(axeFound, entries);
    fs.writeFileSync(BASELINE_FILE, serialiseBaseline(shrunk));
    console.log(`axe: baseline ${entries.length} -> ${shrunk.length} line(s); counts only ever lowered.`);
    entries = shrunk;
  } else if (baselineText === null && scanRoutes) {
    console.log("axe: scripts/axe-baseline.json is missing, so every finding on a route counts as new.");
  }
  axeVerdict = settleVerdict({
    named: axeNamed,
    comparison: scanRoutes ? compareToBaseline(axeFound, entries) : null,
    auditedRoutes: axeFound.size,
    unaudited: axeUnaudited,
    partial: partial || anon,
  });
  console.log(`\naxe: ${axeVerdict.audited} page(s) scanned — ${axeVerdict.ok ? "no failures" : `${axeVerdict.failures.length} failure(s)`}.`);
  for (const f of axeVerdict.failures) console.log(`  ${describeFailure(f)}`);
  if (axeVerdict.lowerable.length) {
    console.log(`  ${axeVerdict.lowerable.length} baseline count(s) can be lowered with --axe-shrink.`);
  }
  if (axeVerdict.nothingAudited) console.log("  NO PAGE WAS AUDITED — that is not a clean run.");
  if (process.env.GITHUB_ACTIONS === "true") {
    for (const f of axeVerdict.failures.slice(0, 10)) {
      const msg = describeFailure(f).replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
      console.log(`::error title=axe: ${(f.screen ?? f.route).replace(/[,:]/g, " ")}::${msg.slice(0, 300)}`);
    }
  }
}
if (slowProblems) {
  for (const p of slowProblems) console.log(`  slow-server notice: ${p}`);
  if (process.env.GITHUB_ACTIONS === "true") {
    for (const p of slowProblems.slice(0, 5)) console.log(`::error title=Slow-server notice::${p.replace(/[%\r\n]/g, " ").slice(0, 300)}`);
  }
}

const failed = Boolean(
  broken.length || (!anon && herds.length) || (axeVerdict && !axeVerdict.ok) || (slowProblems && slowProblems.length),
);

if (reportPath) {
  // The verdict as data, so a nightly run leaves something a person can open
  // without scrolling a log, and a run a week later can be compared with it.
  const report = {
    generated_at: new Date().toISOString(),
    commit: process.env.GITHUB_SHA || null,
    mode: { only, anon, realClient, at },
    csp: cspState,
    routes_walked: walked,
    ok: !failed,
    broken: broken.map((b) => ({ route: b.route, errors: b.errors })),
    herds: herds.map((h) => ({
      count: h.length, sample: h[0].sample, routes: h.map((r) => r.route),
    })),
    redirected,
    distinct_bodies: byDigest.size,
    blocked_hosts: [...escaped],
    duration_ms: Date.now() - walkStarted,
    screen_ms: timings,
    // frontend_ux-03. `ran: false` carries the reason, so an absent scan is never read as a clean one.
    axe: axe.run
      ? {
        ran: true,
        package_version: AXE_PACKAGE_VERSION,
        ok: axeVerdict.ok,
        pages_scanned: axeVerdict.audited,
        named: axeNamed.map((n) => ({
          id: n.id, route: n.route, error: n.error ?? null,
          findings: n.findings.map((f) => ({ rule: f.rule, impact: f.impact, nodes: f.nodes })),
        })),
        failures: axeVerdict.failures.map((f) => ({ ...f, description: describeFailure(f) })),
        lowerable: axeVerdict.lowerable,
      }
      : { ran: false, reason: axe.line },
    // frontend_ux-05. null means the scenario was not asked for on this run.
    slow_server: slowProblems === null ? null : { ok: slowProblems.length === 0, problems: slowProblems },
  };
  fs.mkdirSync(path.dirname(path.resolve(reportPath)), { recursive: true });
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  console.log(`\nreport written to ${reportPath}`);

  if (process.env.GITHUB_STEP_SUMMARY) {
    const slowest = [...timings].sort((a, b) => b.ms - a.ms).slice(0, 5)
      .map((t) => `${t.route} ${t.ms} ms`).join(", ");
    const lines = [
      `### Smoke walk: ${failed ? "FAILED" : "clean"}`,
      "",
      `${walked} screens walked, ${broken.length} broken, ${herds.length} herd(s) of identical bodies. ` +
        `Slowest to settle: ${slowest}.`,
      "",
    ];
    if (broken.length) {
      lines.push("| route | first problem |", "|---|---|");
      for (const b of broken) {
        lines.push(`| \`${b.route}\` | ${b.errors[0].replace(/\|/g, "\\|").replace(/\s+/g, " ")} |`);
      }
    }
    lines.push(axeVerdict ? summaryMarkdown(axeVerdict, `${axeNamed.length} named screens + ${axeFound.size} routes`) : `### Accessibility (axe): NOT RUN\n\n${axe.line}\n`);
    if (slowProblems) {
      lines.push(`### Slow-server notice: ${slowProblems.length ? "FAILED" : "held"}`, "",
        ...(slowProblems.length ? slowProblems.map((p) => `- ${p}`) : ["The sentence appeared once at about three seconds, Retry at about twenty, and both went with the data."]), "");
    }
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");
  }
}

// 2, the repository's "I could not tell" code, for a walk that was asked for accessibility and audited no page.
process.exit(axeVerdict?.nothingAudited ? 2 : failed ? 1 : 0);
