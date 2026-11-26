// The platform administration site's rules (POST-B-351). Run with: node --test scripts/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { build, headersFor, settingsFrom } from "./build.mjs";

const ROOT = path.join(import.meta.dirname, "..");
const src = (f) => fs.readFileSync(path.join(ROOT, "src", f), "utf8");
const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const ANON = `${b64({ alg: "HS256" })}.${b64({ role: "anon" })}.signaturesignature`;
const GOOD = { PLATFORM_API_URL: "https://api.example.com", SUPABASE_URL: "https://abc.supabase.co", SUPABASE_ANON_KEY: ANON };

test("a build with its three settings writes the page, its settings and its headers", () => {
  const out = build(GOOD, fs.mkdtempSync(path.join(os.tmpdir(), "padmin-")));
  for (const f of ["index.html", "app.js", "style.css", "robots.txt", "config.js", "_headers"]) {
    assert.ok(fs.existsSync(path.join(out, f)), f);
  }
  const config = fs.readFileSync(path.join(out, "config.js"), "utf8");
  assert.match(config, /"apiUrl":"https:\/\/api\.example\.com"/);
  assert.match(config, /Object\.freeze/);
});

test("a missing, non-https or service key setting stops the build", () => {
  const service = `${b64({ alg: "HS256" })}.${b64({ role: "service_role" })}.signaturesignature`;
  for (const [name, env] of [
    ["no api", { ...GOOD, PLATFORM_API_URL: "" }],
    ["http api", { ...GOOD, PLATFORM_API_URL: "http://api.example.com" }],
    ["api with a path", { ...GOOD, PLATFORM_API_URL: "https://api.example.com/x" }],
    ["wildcard", { ...GOOD, SUPABASE_URL: "https://*.supabase.co" }],
    ["no key", { ...GOOD, SUPABASE_ANON_KEY: "" }],
    ["service key", { ...GOOD, SUPABASE_ANON_KEY: service }],
    ["new-style secret key", { ...GOOD, SUPABASE_ANON_KEY: "sb_secret_abcdefghijklmnopqrstuvwxyz" }],
  ]) {
    assert.ok(settingsFrom(env).problems.length > 0, name);
    assert.throws(() => build(env, fs.mkdtempSync(path.join(os.tmpdir(), "padmin-"))), name);
  }
});

test("the page may talk to the API and the sign-in service exactly, and to nothing else", () => {
  const headers = headersFor(settingsFrom(GOOD).settings);
  assert.match(headers, /connect-src https:\/\/api\.example\.com https:\/\/abc\.supabase\.co;/);
  assert.match(headers, /default-src 'none'/);
  assert.match(headers, /script-src 'self';/);
  assert.match(headers, /frame-ancestors 'none'/);
  assert.match(headers, /X-Robots-Tag: noindex/);
  assert.match(headers, /Cache-Control: no-store/);
  const csp = headers.split("\n").find((l) => l.includes("Content-Security-Policy"));
  assert.doesNotMatch(csp, /\*|unsafe-inline|unsafe-eval/, "no wildcard host and no inline code");
});

test("the page keeps no session anywhere but its own memory", () => {
  const app = code(src("app.js"));
  assert.doesNotMatch(app, /localStorage|sessionStorage|indexedDB|document\.cookie/);
  assert.match(app, /credentials: "omit"/);
});

test("text from the server reaches the page as text, never as markup", () => {
  const app = code(src("app.js"));
  assert.doesNotMatch(app, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function/);
});

test("the page loads nothing from another site and runs no inline script", () => {
  const html = src("index.html");
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/, "an inline script would need 'unsafe-inline'");
  assert.doesNotMatch(html, /\bstyle="/, "an inline style would need 'unsafe-inline'");
  assert.doesNotMatch(html, /(src|href)="(https?:)?\/\//, "everything is served by the site itself");
  assert.match(html, /noindex, nofollow/);
  assert.equal(src("robots.txt").trim(), "User-agent: *\nDisallow: /");
});

test("every destructive action asks for a code first, and the permanent one for the firm's name", () => {
  const app = code(src("app.js"));
  for (const fn of ["suspend", "softDelete", "purge"]) {
    const body = app.slice(app.indexOf(`async function ${fn}(`), app.indexOf("\n}\n", app.indexOf(`async function ${fn}(`)));
    assert.match(body, /withCode\(answer/, fn);
  }
  const purge = app.slice(app.indexOf("async function purge("));
  assert.match(purge.slice(0, 400), /typedName: f\.name/);
});

test("an idle session ends and a reload starts again from the password", () => {
  const app = code(src("app.js"));
  assert.match(app, /const IDLE_MS = 15 \* 60 \* 1000;/);
  assert.match(app, /let session = null;/);
});

test("the code check sends a body, sign-out ends only this session, and Escape is a cancel", () => {
  const app = code(src("app.js"));
  assert.match(app, /\/challenge`, \{ method: "POST", token: session\.token, body: \{\} \}/);
  assert.match(app, /\/logout\?scope=local/);
  assert.match(app, /dialog\.oncancel = \(\) => resolve\(null\)/);
  const start = app.indexOf("function confirmAction");
  assert.doesNotMatch(app.slice(start, app.indexOf("\n}\n", start)), /\bfail\(/, "the dialog speaks inside itself");
});

test("the build reads its own folder without import.meta.dirname, and asks for Node 22", () => {
  const b = code(fs.readFileSync(path.join(ROOT, "scripts", "build.mjs"), "utf8"));
  assert.doesNotMatch(b, /import\.meta\.dirname/);
  assert.equal(fs.readFileSync(path.join(ROOT, ".nvmrc"), "utf8").trim(), "22");
});
