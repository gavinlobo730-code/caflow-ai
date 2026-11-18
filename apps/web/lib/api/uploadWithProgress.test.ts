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

// THE RULE, NOT A LIST OF DOORS (POST-A-158, second half). Every multipart POST the browser makes leaves through
// `uploadForm` or `fetchUpload`, every `uploadForm` call hands on a progress callback, and every screen that calls an
// upload method which can take one passes it. The first half named three doors and the portal, the invoice reading,
// the statement check, the attachments, the notice, the logo and the shared workbook were all still bare `fetch`.
function sourceFiles(): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const walk = (d: string) => {
    for (const e of fs.readdirSync(path.join(WEB, d), { withFileTypes: true })) {
      const rel = path.posix.join(d, e.name);
      if (e.isDirectory()) { if (!["node_modules", "out", ".next"].includes(e.name)) walk(rel); }
      else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push([rel, fs.readFileSync(path.join(WEB, rel), "utf8")]);
    }
  };
  for (const d of ["app", "components", "lib"]) walk(d);
  return out;
}

/** The text of a call's arguments, from the "(" at `open` to its matching ")". */
function argsAt(src: string, open: number): string {
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) return src.slice(open + 1, i); }
  }
  return src.slice(open + 1);
}

/** The names a file binds to a FormData: `new FormData()` assignments and parameters typed `FormData`. */
function formDataNames(src: string): Set<string> {
  const names = new Set<string>();
  for (const m of src.matchAll(/(?:const|let|var)\s+(\w+)\s*=\s*new FormData\(/g)) names.add(m[1]);
  for (const m of src.matchAll(/(\w+)\??:\s*FormData\b/g)) names.add(m[1]);
  return names;
}

test("no multipart POST in the browser goes round the upload door", () => {
  const offenders: string[] = [];
  for (const [rel, src] of sourceFiles()) {
    if (rel === "lib/api/uploadWithProgress.ts") continue;
    const forms = formDataNames(src);
    if (forms.size === 0) continue;
    for (const m of src.matchAll(/\b(fetchPlain|fetch)\(/g)) {
      const at = m.index! + m[0].length - 1;
      // `uploadForm` itself falls back to fetchPlain when a caller passed no callback; that is the door, not a way round it.
      const fn = src.lastIndexOf("function ", at);
      if (rel === "lib/api/index.ts" && src.slice(fn, fn + "function uploadForm(".length) === "function uploadForm(") continue;
      const body = /\bbody:\s*(\w+)/.exec(argsAt(src, at));
      if (body && forms.has(body[1])) offenders.push(`${rel}: ${m[1]}(… body: ${body[1]})`);
    }
  }
  assert.deepEqual(offenders, [], "send a FormData through fetchUpload (or a lib/api method built on uploadForm) so the screen can show what has been sent");
});

/** A call's top-level arguments (commas inside brackets, braces, parentheses or quotes do not split). */
function splitArgs(text: string): string[] {
  const out: string[] = [];
  let depth = 0, quote: string | null = null, cur = "";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) { cur += ch; if (ch === "\\") { cur += text[++i] ?? ""; } else if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'" || ch === "`") { quote = ch; cur += ch; continue; }
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    if (ch === "," && depth === 0) { out.push(cur.trim()); cur = ""; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

/** Every lib/api method that takes a progress callback, as `group.method`, with the callback's parameter position. */
function uploadMethods(api: string): Map<string, number> {
  const out = new Map<string, number>();
  const re = /^ {4}(\w+): (?:async )?\(([^)]*?)onProgress\?: \(p: UploadProgress\) => void\)/gm;
  for (const m of api.matchAll(re)) {
    const group = [...api.slice(0, m.index).matchAll(/^ {2}(\w+): \{\s*$/gm)].pop()?.[1];
    if (!group) continue;
    out.set(`${group}.${m[1]}`, splitArgs(m[2]).length);
  }
  return out;
}

test("every uploadForm call hands on a progress callback, and every screen calling such a method passes one", () => {
  const api = fs.readFileSync(path.join(WEB, "lib/api/index.ts"), "utf8");
  const calls = [...api.matchAll(/\buploadForm\(/g)].map((m) => argsAt(api, m.index! + m[0].length - 1));
  assert.ok(calls.length >= 9, "the scan found the upload methods");
  for (const a of calls.slice(1)) assert.match(a, /,\s*onProgress\s*$/, `uploadForm(${a}) drops the callback`);
  const methods = uploadMethods(api);
  for (const [m, at] of [["documents.upload", 1], ["clientDocuments.upload", 1], ["banking.uploadStatement", 1],
    ["banking.inspectStatement", 1], ["banking.previewStatement", 1], ["accounting.shareReport", 1],
    ["incomeTax.attachToNotice", 3], ["branding.uploadLogo", 1]] as const) {
    assert.equal(methods.get(m), at, `${m} takes a progress callback as argument ${at + 1}`);
  }
  // Each call to such a method must reach the callback's own position, and the argument there must be a callback
  // (a setter or a passed-on onProgress), whatever its other arguments are (a notice's id comes first, not a file).
  const missing: string[] = [];
  let seen = 0;
  for (const [rel, src] of sourceFiles()) {
    if (!rel.startsWith("app/") && !rel.startsWith("components/")) continue;
    for (const [name, at] of methods) {
      for (const m of src.matchAll(new RegExp(`\\bapi\\.${name.replace(".", "\\.")}\\(`, "g"))) {
        seen++;
        const args = splitArgs(argsAt(src, m.index! + m[0].length - 1));
        if (args.length !== at + 1 || !/^(set\w+|onProgress)$/.test(args[at])) missing.push(`${rel}: ${name}(${args.join(", ")})`);
      }
    }
  }
  assert.ok(seen >= 10, `only ${seen} upload calls found on screens: the scan has gone blind`);
  assert.deepEqual(missing, [], "a screen that uploads a file says how much of it has been sent");
});

test("every direct fetchUpload on a screen passes its progress callback as the fourth argument", () => {
  const missing: string[] = [];
  let seen = 0;
  for (const [rel, src] of sourceFiles()) {
    if (!rel.startsWith("app/") && !rel.startsWith("components/")) continue;
    for (const m of src.matchAll(/\bfetchUpload\(/g)) {
      seen++;
      const args = splitArgs(argsAt(src, m.index! + m[0].length - 1));
      if (args.length !== 4 || !/^(set\w+|onProgress)$/.test(args[3])) missing.push(`${rel}: fetchUpload(${args.join(", ")})`);
    }
  }
  assert.ok(seen >= 3, `only ${seen} direct fetchUpload calls found: the scan has gone blind`);
  assert.deepEqual(missing, [], "the fourth argument is what lets the screen say how much has been sent");
});
