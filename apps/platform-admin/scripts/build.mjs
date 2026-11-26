// Builds the platform administration site into dist/ (POST-B-351). Run by the site's own Cloudflare Pages project:
//   build command: node scripts/build.mjs      output directory: dist      root directory: apps/platform-admin
//
// It needs three settings, given to that Pages project and to nothing else:
//   PLATFORM_API_URL        the API's address, e.g. https://<the API's host>
//   SUPABASE_URL            the sign-in service's address, https://<project>.supabase.co
//   SUPABASE_ANON_KEY       the PUBLIC key the product's web app already ships to every browser (never the service key)
// A missing or non-https value stops the build: a site built without them would ask for a password it cannot check.
// The two hosts are written into the page's Content-Security-Policy EXACTLY, so the page can talk to nothing else.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Not import.meta.dirname: it needs Node 20.11, and an older Cloudflare build image runs Node 18 (.nvmrc asks for 22).
const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

export function settingsFrom(env) {
  const out = {};
  const problems = [];
  for (const [key, name] of [["apiUrl", "PLATFORM_API_URL"], ["supabaseUrl", "SUPABASE_URL"]]) {
    const raw = (env[name] || "").trim().replace(/\/+$/, "");
    if (!/^https:\/\/[a-z0-9.-]+$/i.test(raw)) problems.push(`${name} must be an https address with nothing after the host`);
    out[key] = raw;
  }
  const anon = (env.SUPABASE_ANON_KEY || "").trim();
  if (!/^[A-Za-z0-9._-]{20,}$/.test(anon)) problems.push("SUPABASE_ANON_KEY is missing or not a key");
  if (/^sb_secret_/.test(anon)) problems.push("SUPABASE_ANON_KEY is a SECRET key; it must never reach a browser");
  if (/service_role/.test(Buffer.from(anon.split(".")[1] || "", "base64").toString("utf8"))) {
    problems.push("SUPABASE_ANON_KEY is the SERVICE key; it must never reach a browser");
  }
  out.supabaseAnonKey = anon;
  return { settings: out, problems };
}

export function headersFor(settings) {
  const csp = [
    "default-src 'none'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self'",
    `connect-src ${settings.apiUrl} ${settings.supabaseUrl}`,
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
  ].join("; ");
  return [
    "/*",
    `  Content-Security-Policy: ${csp}`,
    "  X-Frame-Options: DENY",
    "  X-Content-Type-Options: nosniff",
    "  Referrer-Policy: no-referrer",
    "  X-Robots-Tag: noindex, nofollow",
    "  Cache-Control: no-store",
    "  Permissions-Policy: camera=(), microphone=(), geolocation=()",
    "  Strict-Transport-Security: max-age=31536000",
    "",
  ].join("\n");
}

export function build(env, outDir = path.join(ROOT, "dist")) {
  const { settings, problems } = settingsFrom(env);
  if (problems.length) throw new Error(`The platform administration site was not built:\n  ${problems.join("\n  ")}`);
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });
  for (const f of ["index.html", "app.js", "style.css", "robots.txt"]) {
    fs.copyFileSync(path.join(ROOT, "src", f), path.join(outDir, f));
  }
  fs.writeFileSync(path.join(outDir, "config.js"), `window.PLATFORM_CONFIG = Object.freeze(${JSON.stringify(settings)});\n`);
  fs.writeFileSync(path.join(outDir, "_headers"), headersFor(settings));
  return outDir;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    console.log(`built ${build(process.env)}`);
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}
