#!/usr/bin/env node
/**
 * Serves the static export in out/ the way Cloudflare Pages serves it, closely
 * enough for the marketing quality pass to measure this build before it is
 * deployed (POST-A-122).
 *
 *   node scripts/serve-out.mjs --root out --port 4173
 *
 * WHY NOT ANY STATIC SERVER. Lighthouse measures what it is sent. A server that
 * sends the JavaScript uncompressed makes every page look slower than the site
 * is, and one that ignores out/_headers makes the best-practices audit read a
 * site with no security headers. So this one, with no dependency:
 *
 *   - gzips text (HTML, CSS, JavaScript, JSON, SVG, XML) when the browser asks;
 *   - sends the headers out/_headers sets (scripts/security-headers.mjs writes
 *     it), for the paths each rule names, `*` matching anything;
 *   - answers `/pricing` with a 308 to `/pricing/`, serves a folder's
 *     index.html, and answers a path that is not there with out/404.html and a
 *     404, as Pages does for a site built with `trailingSlash: true`;
 *   - refuses a path that climbs out of the root.
 *
 * WHAT IT IS NOT. Cloudflare compresses with Brotli where a browser accepts it
 * and speaks HTTP/2 and HTTP/3 from a nearby edge; this is gzip over HTTP/1.1
 * from the same machine. out/_redirects (two old paths sent to /) is not read.
 * The workflow can measure the deployed site instead, which is the figure a
 * visitor gets; this server measures the build in front of it.
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import zlib from "node:zlib";
import { pathToFileURL } from "node:url";

export const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
};

const COMPRESSIBLE = /^(text\/|application\/(json|xml)|image\/svg)/;

/** `_headers` as rules: a path pattern on its own line, its headers indented beneath it. */
export function parseHeadersFile(text) {
  const rules = [];
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (!line.trim() || line.trim().startsWith("#")) continue;
    if (!/^\s/.test(line)) {
      rules.push({ pattern: line.trim(), headers: [] });
      continue;
    }
    const at = line.indexOf(":");
    if (at > 0 && rules.length) rules[rules.length - 1].headers.push([line.slice(0, at).trim(), line.slice(at + 1).trim()]);
  }
  return rules;
}

/** The headers every rule whose pattern matches `urlPath` sets, in file order. */
export function headersFor(rules, urlPath) {
  const out = [];
  for (const rule of rules) {
    const rx = new RegExp(`^${rule.pattern.split("*").map((p) => p.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*")}$`);
    if (rx.test(urlPath)) out.push(...rule.headers);
  }
  return out;
}

const isFile = (p) => fs.existsSync(p) && fs.statSync(p).isFile();
const isDir = (p) => fs.existsSync(p) && fs.statSync(p).isDirectory();

/** @typedef {{ status: number, file?: string, location?: string }} Answer */

/**
 * What a request path resolves to: `{ status, file }`, or `{ status: 308, location }`.
 * `root` must be an absolute path.
 *
 * @param {string} root
 * @param {string} rawPath
 * @returns {Answer}
 */
export function resolvePath(root, rawPath) {
  let urlPath;
  try {
    urlPath = decodeURIComponent(rawPath.split("?")[0]);
  } catch {
    return { status: 400 };
  }
  if (urlPath.includes("\0") || !urlPath.startsWith("/")) return { status: 400 };
  const normal = path.posix.normalize(urlPath);
  const abs = path.join(root, normal);
  if (abs !== root && !abs.startsWith(root + path.sep)) return notFound(root);
  if (normal.endsWith("/")) {
    const index = path.join(abs, "index.html");
    return isFile(index) ? { status: 200, file: index } : notFound(root);
  }
  if (isFile(abs)) return { status: 200, file: abs };
  if (isDir(abs) && isFile(path.join(abs, "index.html"))) return { status: 308, location: `${normal}/` };
  return notFound(root);
}

/** @param {string} root @returns {Answer} */
function notFound(root) {
  const page = path.join(root, "404.html");
  return isFile(page) ? { status: 404, file: page } : { status: 404 };
}

/** An http.Server answering from `root` (absolute). */
export function createServer(root) {
  const headersFile = path.join(root, "_headers");
  const rules = isFile(headersFile) ? parseHeadersFile(fs.readFileSync(headersFile, "utf8")) : [];
  const gzipped = new Map();
  return http.createServer((req, res) => {
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { Allow: "GET, HEAD" }).end();
      return;
    }
    const answer = resolvePath(root, req.url ?? "/");
    const urlPath = (req.url ?? "/").split("?")[0];
    for (const [name, value] of headersFor(rules, urlPath)) res.setHeader(name, value);
    if (answer.status === 308) {
      res.writeHead(308, { Location: answer.location }).end();
      return;
    }
    if (!answer.file) {
      res.writeHead(answer.status, { "Content-Type": "text/plain; charset=utf-8" }).end(String(answer.status));
      return;
    }
    const type = TYPES[path.extname(answer.file).toLowerCase()] ?? "application/octet-stream";
    let body = fs.readFileSync(answer.file);
    const headers = { "Content-Type": type };
    if (COMPRESSIBLE.test(type)) {
      headers.Vary = "Accept-Encoding";
      if (/\bgzip\b/.test(String(req.headers["accept-encoding"] ?? ""))) {
        // Keyed by the file's size and modification time as well as its path, so a rebuild under a running
        // server is served as built and not from the last build's compressed copy.
        const stat = fs.statSync(answer.file);
        const key = `${answer.file}:${stat.size}:${stat.mtimeMs}`;
        if (!gzipped.has(key)) gzipped.set(key, zlib.gzipSync(body));
        body = gzipped.get(key);
        headers["Content-Encoding"] = "gzip";
      }
    }
    headers["Content-Length"] = String(body.length);
    res.writeHead(answer.status, headers);
    res.end(req.method === "HEAD" ? undefined : body);
  });
}

function arg(name, fallback) {
  const at = process.argv.indexOf(`--${name}`);
  return at > 0 && process.argv[at + 1] ? process.argv[at + 1] : fallback;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const root = path.resolve(arg("root", "out"));
  if (!isFile(path.join(root, "index.html"))) {
    console.error(`serve-out: ${root} has no index.html — build the site first (pnpm build).`);
    process.exit(2);
  }
  const port = Number(arg("port", "4173"));
  const host = arg("host", "127.0.0.1");
  createServer(root).listen(port, host, () => console.log(`serve-out: ${root} on http://${host}:${port}/`));
}
