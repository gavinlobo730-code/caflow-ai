import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fetchUpload, percentSent } from "./uploadWithProgress.ts";

class FakeXhr {
  static last: FakeXhr;
  headers: Record<string, string> = {};
  upload: { onprogress: ((e: { loaded: number; total: number; lengthComputable: boolean }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 200; statusText = "OK"; responseText = "{\"success\":true}"; responseType = "";
  opened: [string, string] | null = null; sent = 0;
  constructor() { FakeXhr.last = this; }
  open(m: string, u: string) { this.opened = [m, u]; }
  setRequestHeader(k: string, v: string) { this.headers[k] = v; }
  getAllResponseHeaders() { return "content-type: application/json\r\nx-request-id: r1\r\n"; }
  send() { this.sent++; }
}

test("percentSent never draws an unknown size as 0 and never passes 100", () => {
  assert.equal(percentSent({ loaded: 5, total: 0 }), null);
  assert.equal(percentSent({ loaded: 5, total: Number.NaN }), null);
  assert.equal(percentSent({ loaded: 50, total: 200 }), 25);
  assert.equal(percentSent({ loaded: 999, total: 200 }), 100);
});

test("an upload reports progress, resolves an ordinary Response and is sent exactly once", async () => {
  (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest = FakeXhr;
  const seen: Array<[number, number]> = [];
  const p = fetchUpload("https://x/api/u", { headers: { Authorization: "Bearer t" }, body: new FormData() }, "write", (e) => seen.push([e.loaded, e.total]));
  const x = FakeXhr.last;
  x.upload.onprogress?.({ loaded: 10, total: 100, lengthComputable: true });
  x.upload.onprogress?.({ loaded: 5, total: 0, lengthComputable: false });
  x.onload?.();
  const res = await p;
  assert.deepEqual(seen, [[10, 100], [5, 0]]);
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { success: true });
  assert.equal(res.headers.get("x-request-id"), "r1");
  assert.deepEqual(x.opened, ["POST", "https://x/api/u"]);
  assert.equal(x.headers.Authorization, "Bearer t");
  assert.equal(x.headers["Content-Type"], undefined, "the browser sets the multipart boundary");
  assert.equal(x.sent, 1, "an upload is never sent twice");
});

test("a refusal keeps its status and body, and a dropped connection becomes the product's sentence", async () => {
  (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest = FakeXhr;
  const a = fetchUpload("https://x/api/u", { body: new FormData() }, "write");
  FakeXhr.last.status = 422; FakeXhr.last.responseText = "{\"detail\":\"no\"}";
  FakeXhr.last.onload?.();
  const res = await a;
  assert.equal(res.status, 422);
  assert.equal(res.ok, false);
  const b = fetchUpload("https://x/api/u", { body: new FormData() }, "write");
  FakeXhr.last.onerror?.();
  await assert.rejects(b, (e: Error) => /write|saved|answer|connection|went through/i.test(e.message) && !/Failed to fetch/.test(e.message));
});

const WEB = path.resolve(import.meta.dirname, "../..");
test("XMLHttpRequest is used in one place only, and the upload methods that take a callback say so", () => {
  const users: string[] = [];
  const walk = (d: string) => {
    for (const e of fs.readdirSync(path.join(WEB, d), { withFileTypes: true })) {
      const rel = path.posix.join(d, e.name);
      if (e.isDirectory()) { if (!["node_modules", "out", ".next"].includes(e.name)) walk(rel); }
      else if (/\.(ts|tsx)$/.test(e.name) && !e.name.endsWith(".test.ts")) {
        if (/new XMLHttpRequest\(/.test(fs.readFileSync(path.join(WEB, rel), "utf8"))) users.push(rel);
      }
    }
  };
  for (const d of ["app", "components", "lib"]) walk(d);
  assert.deepEqual(users, ["lib/api/uploadWithProgress.ts"]);
  const api = fs.readFileSync(path.join(WEB, "lib/api/index.ts"), "utf8");
  for (const m of ["/api/documents/upload", "/api/client-documents/upload", "/api/banking/statements/upload"]) {
    assert.match(api, new RegExp(`uploadForm\\(\`\\$\\{BASE_URL\\}${m.replace(/\//g, "\\/")}\`, token, form, onProgress\\)`), `${m} must take a progress callback`);
  }
});
