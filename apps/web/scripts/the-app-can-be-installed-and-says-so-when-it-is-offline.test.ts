// The app can be installed on a phone and says so when it is offline (POST-A-131). Run with:
//   node --experimental-strip-types --test scripts/the-app-can-be-installed-and-says-so-when-it-is-offline.test.ts
//
// WHY THIS EXISTS
//     The manifest listed only SVG icons (whether that stops Chrome offering install was unconfirmed), the home-screen icon on iOS was the
//     page's screenshot, and a page navigated to while the device was offline was the browser's own error page. The service worker is the
//     one file where a mistake cannot be seen on any screen until the day a CA's connection drops, so it is exercised here by running the
//     real file in a sandbox with a cache and a network that can be made to fail.
//
// WHAT IS ASSERTED
//     1. The manifest names PNG icons at 192 and 512 for ordinary use and a 512 maskable one, every file exists and is the size it says it is
//        (a manifest that names a size its file does not have is refused by the browser's installability check), and the iOS icon is linked.
//     2. The offline page is one file with NOTHING loaded from anywhere (it must open with no network at all, and the worker stores that one
//        file and no other), says it cannot reach PracticeSync without claiming to know why, and has a button that retries.
//     3. The worker, run for real: the offline page is stored as a PLAIN response (Cloudflare Pages serves it at /offline and redirects
//        /offline.html, and a response marked redirected cannot answer a page navigation, which the browser turns into a network error); a
//        page navigation that fails offline gets it; a request for a script, an image or data does NOT (a page is not an answer to a script);
//        a failure to store it does not fail the install; data requests are never cached; old caches are deleted.
//
//     What is NOT proven here: that Chrome offers install and that the page shows in a real browser on a phone. That was checked once in
//     Chromium (Page.getInstallabilityErrors and a navigation with the network cut) and is written in the commit that added this file.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const root = path.resolve(import.meta.dirname, "..");
const pub = (rel: string) => path.join(root, "public", rel);
const read = (rel: string) => fs.readFileSync(pub(rel), "utf8");

/** Width and height from a PNG's IHDR chunk. */
function pngSize(file: string): [number, number] {
  const b = fs.readFileSync(file);
  assert.equal(b.subarray(1, 4).toString("ascii"), "PNG", `${file} is not a PNG`);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

type Icon = { src: string; sizes: string; type: string; purpose?: string };

test("the manifest names PNG icons of the size each file really is, one of them maskable", () => {
  const manifest = JSON.parse(read("manifest.json"));
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.start_url, "/");
  assert.ok(manifest.id && manifest.scope, "an id and a scope, so an install is the same app whichever URL it was started from");
  const icons: Icon[] = manifest.icons;
  assert.ok(icons.length >= 3, "the manifest was read");
  const png = icons.filter((i) => i.type === "image/png");
  const any = (size: string) => png.some((i) => i.sizes === size && (i.purpose ?? "any") === "any");
  assert.ok(any("192x192") && any("512x512"), "an ordinary PNG at 192 and at 512");
  assert.ok(png.some((i) => i.sizes === "512x512" && i.purpose === "maskable"), "a maskable PNG at 512");
  for (const icon of icons) {
    const file = pub(icon.src.replace(/^\//, ""));
    assert.ok(fs.existsSync(file), `${icon.src} is named and missing`);
    if (icon.type === "image/png") {
      const [w, h] = pngSize(file);
      assert.equal(`${w}x${h}`, icon.sizes, `${icon.src} says ${icon.sizes} and is ${w}x${h}`);
    }
  }
});

test("the iOS home-screen icon is linked and is 180 by 180", () => {
  const layout = fs.readFileSync(path.join(root, "app/layout.tsx"), "utf8");
  assert.match(layout, /<link rel="apple-touch-icon" href="\/apple-touch-icon\.png" \/>/);
  assert.deepEqual(pngSize(pub("apple-touch-icon.png")), [180, 180]);
});

test("the offline page is one file that needs nothing from the network, says it cannot reach the app, and can try again", () => {
  const html = read("offline.html");
  assert.ok(html.length > 500, "the page was read");
  assert.match(html, /<title>Can't reach PracticeSync<\/title>/);
  assert.match(html, /<h1>Can't reach PracticeSync<\/h1>/);
  assert.match(html, /Your device may be offline, or the connection was lost/, "it does not claim to know which: the worker only knows a fetch failed");
  assert.match(html, /<button type="button" id="retry">Try again<\/button>/);
  assert.match(html, /window\.location\.reload\(\)/);
  assert.match(html, /<meta name="viewport"/);
  assert.ok(!/(?:src|href)=["']https?:/i.test(html) && !/url\(\s*["']?https?:/i.test(html), "nothing is fetched from another origin");
  // it loads NOTHING: an image fetched from the app would be a broken box on exactly the day the page is shown, because the worker stores
  // this one file and no other for it (the icon is inline)
  const loaded = [...html.matchAll(/(?:src|href)=["']([^"']+)["']/g)].map((m) => m[1]);
  assert.deepEqual(loaded, [], "no src or href at all");
  assert.ok(!/<img\b/i.test(html) && /<svg\b/.test(html), "the icon is an inline svg");
});

// ── the worker, run for real ─────────────────────────────────────────────────────────────────────

type Listener = (event: any) => void;

/** Run public/sw.js with a fake network and a fake cache storage. `network(url)` returns a Response or throws. */
function loadWorker(network: (url: string, init?: any) => Promise<Response>, options: { putFails?: boolean } = {}) {
  const listeners: Record<string, Listener> = {};
  const stores = new Map<string, Map<string, Response>>();
  const key = (r: any) => new URL(typeof r === "string" ? r : r.url, "https://app.test").pathname;
  const cacheOf = (name: string) => {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name)!;
    return {
      async addAll(urls: string[]) { for (const u of urls) store.set(key(u), await network(u)); },
      async match(request: any) { return store.get(key(request)); },
      async put(request: any, response: Response) { if (options.putFails) throw new Error("QuotaExceededError"); store.set(key(request), response); },
    };
  };
  const caches = {
    open: async (name: string) => cacheOf(name),
    keys: async () => [...stores.keys()],
    delete: async (name: string) => stores.delete(name),
    match: async (request: any) => { for (const s of stores.values()) if (s.has(key(request))) return s.get(key(request)); return undefined; },
  };
  const self = {
    addEventListener: (type: string, fn: Listener) => { listeners[type] = fn; },
    skipWaiting: () => {},
    clients: { claim: async () => {} },
  };
  const sandbox = { self, caches, fetch: (r: any, init?: any) => network(typeof r === "string" ? r : r.url, init), Response, URL, Promise, console };
  vm.runInNewContext(fs.readFileSync(pub("sw.js"), "utf8"), sandbox);
  const settle = async (type: string, event: any) => { listeners[type](event); await event.done; };
  return {
    stores,
    install: async () => { const e: any = { waitUntil: (p: Promise<unknown>) => { e.done = p; } }; await settle("install", e); },
    activate: async () => { const e: any = { waitUntil: (p: Promise<unknown>) => { e.done = p; } }; await settle("activate", e); },
    fetch: async (request: any) => {
      const e: any = { request, respondWith: (p: Promise<Response>) => { e.done = p; } };
      listeners.fetch(e);
      return (await e.done) as Response;
    },
  };
}

const OFFLINE_HTML = fs.readFileSync(pub("offline.html"), "utf8");
const redirected = () => { const r = new Response(OFFLINE_HTML, { status: 200 }); Object.defineProperty(r, "redirected", { value: true }); return r; };
const down = async () => { throw new TypeError("Failed to fetch"); };
const nav = (u: string) => ({ url: `https://app.test${u}`, mode: "navigate", method: "GET" });
const sub = (u: string) => ({ url: `https://app.test${u}`, mode: "no-cors", method: "GET" });

test("install stores the offline page as a plain response even though the server redirected to it", async () => {
  const w = loadWorker(async (u) => (u === "/offline.html" ? redirected() : new Response("login", { status: 200 })));
  await w.install();
  const stored = [...w.stores.values()][0].get("/offline.html");
  assert.ok(stored, "the offline page is in the cache");
  assert.equal(stored.redirected, false, "a redirected response would answer a navigation with a network error");
  assert.equal(await stored.text(), OFFLINE_HTML);
});

test("a failure to fetch the offline page does not fail the install", async () => {
  const w = loadWorker(async (u) => { if (u === "/offline.html") throw new TypeError("nope"); return new Response("login"); });
  await w.install();                                  // resolves: an install that rejects would leave no worker at all
  assert.equal([...w.stores.values()][0].get("/offline.html"), undefined);
});

test("a page navigation that fails offline is answered with the offline page, as a plain 200", async () => {
  const w = loadWorker(async (u) => (u === "/offline.html" ? redirected() : new Response("login")));
  await w.install();
  const nowOffline = loadWorker(down);
  nowOffline.stores.set("practicesync-v5", [...w.stores.values()][0]);
  const answer = await nowOffline.fetch(nav("/clients/abc/overview/"));
  assert.equal(answer.status, 200);
  assert.equal(answer.redirected, false);
  assert.equal(await answer.text(), OFFLINE_HTML);
});

test("a stored copy that is marked redirected is still served as a plain response", async () => {
  const w = loadWorker(down);
  w.stores.set("practicesync-v5", new Map([["/offline.html", redirected()]]));      // whatever put it there, the answer is rebuilt from its bytes
  const answer = await w.fetch(nav("/anything/"));
  assert.equal(answer.status, 200);
  assert.equal(answer.redirected, false);
  assert.equal(await answer.text(), OFFLINE_HTML);
});

test("an ONLINE page navigation goes to the network and gets what the network sent, never the offline page", async () => {
  const w = loadWorker(async (u) => new Response(`real page ${u}`, { status: 200 }));
  await w.install();
  const answer = await w.fetch(nav("/clients/abc/overview/"));
  assert.equal(answer.status, 200);
  assert.match(await answer.text(), /^real page .*\/clients\/abc\/overview\/$/);
  const serverError = loadWorker(async () => new Response("boom", { status: 500 }));
  assert.equal((await serverError.fetch(nav("/clients/abc/overview/"))).status, 500, "a 5xx is the server's answer, not the offline page");
});

test("a 404 or an error page fetched at install is NOT stored as the offline page", async () => {
  const w = loadWorker(async (u) => (u === "/offline.html" ? new Response("not found", { status: 404 }) : new Response("login")));
  await w.install();
  assert.equal([...w.stores.values()][0].get("/offline.html"), undefined, "a 404 would be served later as a 200 offline page");
});

test("a cache that refuses the write (quota) does not fail the install", async () => {
  const w = loadWorker(async (u) => (u === "/offline.html" ? redirected() : new Response("login")), { putFails: true });
  await w.install();                                  // resolves although storing the page was refused: a rejected install leaves no worker at all
  assert.equal([...w.stores.values()][0].get("/offline.html"), undefined);
});

test("activation stores the offline page when installing could not", async () => {
  const w = loadWorker(async (u) => (u === "/offline.html" ? redirected() : new Response("login")));
  w.stores.set("practicesync-v5", new Map());          // installed without the page
  await w.activate();
  const stored = w.stores.get("practicesync-v5")!.get("/offline.html");
  assert.ok(stored && stored.redirected === false, "the second chance stored it, as a plain response");
  const already = loadWorker(down);
  already.stores.set("practicesync-v5", new Map([["/offline.html", new Response(OFFLINE_HTML)]]));
  await already.activate();                            // a page already stored is not fetched again (the network is down and nothing throws)
  assert.equal(await already.stores.get("practicesync-v5")!.get("/offline.html")!.text(), OFFLINE_HTML);
});

test("without the offline page cached a failed navigation is the 503 it always was, never an undefined", async () => {
  const w = loadWorker(down);
  const answer = await w.fetch(nav("/clients/abc/overview/"));
  assert.equal(answer.status, 503);
});

test("a failed request for a script, an image or a payload is NOT answered with the page", async () => {
  const w = loadWorker(async (u) => (u === "/offline.html" ? redirected() : new Response("login")));
  await w.install();
  const nowOffline = loadWorker(down);
  nowOffline.stores.set("practicesync-v5", [...w.stores.values()][0]);
  for (const u of ["/_next/static/chunks/app.js", "/logo.svg", "/clients/abc/overview/index.txt"]) {
    const answer = await nowOffline.fetch(sub(u));
    assert.equal(answer.status, 503, `${u} must stay a 503`);
  }
});

test("data requests (the API, the database, anything not a GET) go straight to the network and are never cached", async () => {
  const calls: string[] = [];
  const w = loadWorker(async (u, init) => { calls.push(`${init?.method ?? "GET"} ${u}`); return new Response("{}", { status: 200 }); });
  const post = await w.fetch({ url: "https://app.test/api/x", mode: "cors", method: "POST" });
  assert.equal(post.status, 200);
  const api = await w.fetch({ url: "https://practicesync-api.onrender.com/api/y", mode: "cors", method: "GET" });
  assert.equal(api.status, 200);
  assert.equal(w.stores.size, 0, "nothing was stored");
});

test("activating deletes every cache but the current one", async () => {
  const w = loadWorker(async () => new Response("x"));
  w.stores.set("practicesync-v1", new Map()); w.stores.set("practicesync-v4", new Map()); w.stores.set("practicesync-v5", new Map());
  await w.activate();
  assert.deepEqual([...w.stores.keys()], ["practicesync-v5"]);
});

test("the cache name moved on, so a worker that predates the offline page replaces itself", () => {
  assert.match(read("sw.js"), /const CACHE_NAME = 'practicesync-v5'/);
});

test("the bill upload offers the camera on a phone, only on a phone, and feeds the same file the Extract button reads", () => {
  const src = fs.readFileSync(path.join(root, "components/purchases/PurchaseBillEditor.tsx"), "utf8");
  assert.ok(src.length > 5000, "the editor was read");
  const camera = src.match(/<input ref=\{cameraInputRef\}[\s\S]*?\/>/)?.[0] ?? "";
  assert.ok(camera, "a camera input is there");
  assert.match(camera, /type="file"/);
  assert.match(camera, /capture="environment"/, "the rear camera");
  assert.match(camera, /accept="image\/jpeg,image\/png"/, "the image types the server reads, named (a wildcard would offer types it cannot)");
  assert.match(camera, /aria-label="Photograph the invoice to extract"/);
  assert.match(camera, /className="hidden"/, "the input itself is hidden, so it is not in the accessibility tree");
  assert.match(camera, /onChange=\{\(e\) => setUploadFile\(e\.target\.files\?\.\[0\] \?\? null\)\}/, "the photograph becomes the file Extract reads");
  const button = src.match(/<Button(?:(?!<Button)[\s\S])*?cameraInputRef\.current\?\.click\(\)[\s\S]*?>\s*Take photo/)?.[0] ?? "";
  assert.ok(button, "a visible button opens the camera input");
  assert.match(button, /aria-describedby="ai-disclosure-invoice-extraction"/, "the VISIBLE control carries the disclosure of who receives the file (the hidden input is not in the accessibility tree)");
  assert.match(button, /className="hidden \[@media\(pointer:coarse\)\]:inline-flex /, "shown on a touch device in either orientation and never on a desktop, where `capture` means nothing");
  assert.match(src, /flex flex-wrap items-center gap-2">\s*<input type="file" accept="\.pdf,\.png,\.jpg,\.jpeg"/, "the row wraps: three controls and a name do not fit one line at 390 px");
});

