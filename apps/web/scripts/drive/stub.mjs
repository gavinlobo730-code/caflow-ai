/**
 * The server the drive talks to: the static export, a PostgREST that answers from a table map, and an API that
 * answers from a route table and WRITES DOWN every write it is sent.
 *
 * WHY A SECOND SERVER AND NOT THE WALK'S. The walk's stub answers every read `[]` on purpose: it checks that a
 * screen renders with NO data. A money editor cannot be driven that way: Post Entry needs an account to post to,
 * an invoice drawer needs an invoice to open. This stub answers the same URLs with rows, and, the part the walk
 * has no use for, keeps a LOG of every write (an API POST, PUT, PATCH or DELETE, and a PostgREST write) with
 * its body and the moment it arrived. "Exactly one write" is a statement about that log, not about a button's
 * `disabled` attribute.
 *
 * It is built the way the walk's is, and for the same reasons: the smoke build points the API and Supabase at
 * THIS origin, so every call is same-origin and no CORS preflight exists to defeat a stub (the walk's header has
 * the long version); `out/_headers` is applied to every static response exactly as Cloudflare Pages would, so a
 * Content-Security-Policy that stops a screen working is found here; a dynamic segment is served the one page the
 * export built for its route shape (`/clients/<uuid>/…` and `/…/<id>/edit`).
 *
 * WHAT IT DOES NOT DO. It does not filter. A PostgREST read of `client_sales_invoices` returns every row in the
 * table map whatever `.eq()` says, because the tables hold one client's worth and a filter engine would be a
 * reimplementation of PostgREST. It pages the way PostgREST does at its edges (a `Range` that starts past zero,
 * or a keyset `id=gt.…`, gets nothing), because `selectAll` and `fetch_all` loop until a short page and a stub
 * that answered the same rows for ever would loop with them.
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { headersFor } from "../security-headers.mjs";
import { FAKE_SESSION, FAKE_USER } from "./fixtures.mjs";

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain",
  ".woff2": "font/woff2",
};

function sendJson(res, body, status = 200) {
  const text = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(text) });
  res.end(text);
}

/** The house envelope, which is what `lib/api` unwraps. */
export const ok = (data) => ({ success: true, data, error: null });
/**
 * A refusal the way the API gives one: an HTTP error status and FastAPI's `{"detail": "<a sentence for the CA>"}`.
 * Spread into a route (`stub.route({ method, re, ...refuse("…") })`). It is the real shape on purpose. `request()`
 * in lib/api throws on a non-2xx and hands the sentence on, while a `200` carrying `success: false` is returned
 * as data for the caller to check; a stub that refused the second way would drive a path the server does not take
 * and miss a screen that only handles the first.
 */
export const refuse = (detail, status = 422) => ({ status, reply: () => ({ detail }) });

/**
 * @param {object} o
 * @param {string} o.root           the static export (`out/`)
 * @param {number} o.port           the port the smoke build baked into the bundle
 * @param {Array}  o.headerRules    parsed `out/_headers`, or [] to serve without
 * @param {(url: string) => string | null} o.resolveBuilt  the file the export serves for a URL
 */
export function createStub({ root, port, headerRules, resolveBuilt }) {
  /** table name -> rows. Replaced wholesale by `reset()`. */
  let tables = {};
  /** API routes, first match wins: { method, re, reply(req, body, url), delay, status }. */
  let routes = [];
  /** Every write, in arrival order. */
  let writes = [];
  /** How long a write is held before it is answered. Long enough that a second click lands first. */
  let writeDelayMs = 700;
  let inFlight = 0;
  /** Refusals this stub sent ON PURPOSE (a route given a 4xx or 5xx status), so the runner can tell the browser's
   *  own "Failed to load resource" line for one of them from a request that failed for a reason nobody planned. */
  let refusals = 0;
  let lastActivity = Date.now();

  const touch = () => { lastActivity = Date.now(); };

  function readTable(name, req, url) {
    const wantsObject = String(req.headers.accept || "").includes("vnd.pgrst.object+json");
    if (name === "users") {
      const rows = tables.users ?? [];
      return wantsObject ? (rows[0] ?? null) : rows;
    }
    let rows = tables[name] ?? [];
    // The edges of paging, as PostgREST answers them: a page that starts past the first (an OFFSET reader
    // asks `Range: 1000-1999`) or a keyset step (`id=gt.<last>`) comes back empty, so a pager stops.
    const range = String(req.headers.range || "");
    if ((range && !range.startsWith("0-")) || String(url.searchParams.get("id") ?? "").startsWith("gt.")) rows = [];
    return wantsObject ? (rows[0] ?? null) : rows;
  }

  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://stub");
    const pathname = decodeURIComponent(url.pathname);
    const siteHeaders = headersFor(headerRules, pathname);

    if (pathname.startsWith("/__supabase/auth/v1/")) {
      if (pathname.endsWith("/user")) return sendJson(res, FAKE_USER);
      if (pathname.endsWith("/logout")) return sendJson(res, {});
      return sendJson(res, { ...FAKE_SESSION });
    }

    if (pathname.startsWith("/__supabase/rest/v1/")) {
      const table = pathname.split("/").pop();
      if (req.method !== "GET" && req.method !== "HEAD") {
        let body = "";
        req.on("data", (d) => { body += d; });
        req.on("end", () => {
          writes.push({ t: Date.now(), via: "postgrest", method: req.method, path: pathname, table, search: url.search, body });
          touch();
          sendJson(res, [], 201);
        });
        return;
      }
      return sendJson(res, readTable(table, req, url));
    }

    if (pathname.startsWith("/__supabase/storage/")) return sendJson(res, []);
    if (pathname.startsWith("/__supabase/")) return sendJson(res, {});

    if (pathname.startsWith("/__api/")) {
      let body = "";
      req.on("data", (d) => { body += d; });
      req.on("end", () => {
        const target = pathname + url.search;
        const route = routes.find((r) => (!r.method || r.method === req.method) && r.re.test(target));
        const isWrite = req.method !== "GET" && req.method !== "HEAD" && req.method !== "OPTIONS";
        if (isWrite) {
          writes.push({ t: Date.now(), via: "api", method: req.method, path: pathname, search: url.search, body });
          inFlight += 1;
          touch();
        }
        const out = route
          ? route.reply(req, body, url)
          : ok(req.method === "GET" ? [] : { id: "new-1" });
        const delay = !isWrite ? (route?.delay ?? 0) : (route?.delay ?? writeDelayMs);
        // /health is the keep-alive's own ping and never waits.
        const wait = pathname.startsWith("/__api/health") ? 0 : delay;
        setTimeout(() => {
          if (isWrite) { inFlight -= 1; touch(); }
          if (res.destroyed || res.writableEnded) return;
          if ((route?.status ?? 200) >= 400) refusals += 1;
          sendJson(res, out, route?.status ?? 200);
        }, wait);
      });
      return;
    }

    const file = resolveBuilt(pathname);
    if (!file) {
      res.writeHead(404, { ...siteHeaders, "content-type": "text/plain" });
      return res.end("not found");
    }
    res.writeHead(200, { ...siteHeaders, "content-type": MIME[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });

  return {
    /** Listen, and resolve when it is ready. */
    start: () => new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve())),
    stop: () => new Promise((resolve) => { server.closeAllConnections?.(); server.close(() => resolve()); }),

    /** Back to a known state before each scenario: the baseline tables and no routes, writes or delay change. */
    reset(baseline) {
      tables = Object.fromEntries(Object.entries(baseline).map(([k, v]) => [k, structuredClone(v)]));
      routes = [];
      writes = [];
      writeDelayMs = 700;
      inFlight = 0;
      refusals = 0;
      touch();
    },
    refusalsServed: () => refusals,
    setTable(name, rows) { tables[name] = rows; },
    /** Register an API route ahead of the defaults. */
    route(spec) { routes.unshift({ method: undefined, delay: undefined, status: undefined, ...spec }); },
    setWriteDelay(ms) { writeDelayMs = ms; },

    /** Every write whose path matches, optionally by method. */
    writesTo(re, method) {
      return writes.filter((w) => re.test(w.path + w.search) && (!method || w.method === method));
    },
    allWrites: () => writes.slice(),

    /**
     * Resolves when no write is being held and nothing has been written for `quietMs`, counted FROM THIS CALL.
     *
     * Counting from the call and not from the last write is what makes "exactly one" mean something. A click's
     * write does not reach the server on the same tick: the handler validates, awaits the session token and only
     * then sends, so a check that asked "has anything happened lately?" before the first write arrived would
     * answer yes and count zero. Starting the clock here gives the first write `quietMs` to show up, and a second
     * write (the defect) the same again after the first is answered.
     */
    async quiet({ quietMs = 900, timeoutMs = 12_000 } = {}) {
      touch();
      const started = Date.now();
      for (;;) {
        if (inFlight === 0 && Date.now() - lastActivity >= quietMs) return;
        if (Date.now() - started > timeoutMs) throw new Error(`the stub never went quiet (${inFlight} write(s) still held)`);
        await new Promise((r) => setTimeout(r, 40));
      }
    },
  };
}
