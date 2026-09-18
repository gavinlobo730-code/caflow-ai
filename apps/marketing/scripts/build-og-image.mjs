/**
 * Render public/og.png — the picture people see when the site is shared.
 *
 * WHY THIS EXISTS. The marketing site had `openGraph` metadata with a title and
 * a description and NO image, and no `metadataBase` for a relative one to
 * resolve against. So a link forwarded on WhatsApp or posted on LinkedIn — which
 * is how a product for accountants actually spreads — rendered as a bare line of
 * text. Owner review, 18-09-2026, on being shown the three findings: "Yep do all
 * three".
 *
 * WHY IT IS RENDERED IN A BROWSER RATHER THAN DRAWN. The card has to be in the
 * site's own typefaces — Manrope and Instrument Serif — and carry the real logo
 * mark. Drawing it with an image library would have meant a substitute font,
 * because the brand faces are woff2 and nothing here can convert them; this
 * environment has no fontTools and no network to fetch it. Rendering the card
 * against the BUILT SITE instead means it uses the very stylesheet and the very
 * font files the pages use, so the picture in a WhatsApp preview is set in the
 * same type as the page behind the link.
 *
 * It therefore needs a build to exist first:
 *
 *     pnpm build && node scripts/build-og-image.mjs
 *
 * The page is written into `out/`, screenshotted and removed again — it is
 * never part of the deployed site, only a fixture the renderer can reach so
 * that `/hero/space-earth.webp` and the built CSS resolve by their real paths.
 *
 * 1200x630 is the size every consumer crops from: Facebook and LinkedIn use it
 * whole, WhatsApp and iMessage take a centre square out of it, and Twitter's
 * `summary_large_image` letterboxes it. So the mark, the wordmark and the
 * headline all sit inside the middle 630x630, and only the artwork runs to the
 * edges.
 */

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");
const OUT = path.join(ROOT, "out");
const TARGET = path.join(ROOT, "public", "og.jpg");

if (!fs.existsSync(OUT)) {
  console.error("out/ is missing — run `pnpm build` first, this renders against it.");
  process.exit(1);
}

// The built stylesheet, so the card gets Manrope, Instrument Serif and the
// site's own tokens rather than a lookalike.
const cssDir = path.join(OUT, "_next", "static", "css");
const css = fs
  .readdirSync(cssDir)
  .filter((f) => f.endsWith(".css"))
  .map((f) => `/_next/static/css/${f}`);
if (css.length === 0) {
  console.error("no built CSS found in out/_next/static/css");
  process.exit(1);
}

/* THE FONT VARIABLE CLASSES ARE READ OUT OF THE BUILD, NOT HARD-CODED.
   `next/font` emits the families behind CSS custom properties and hangs them on
   a generated class — `__variable_1f5468` — whose hash changes whenever the
   font configuration does. Tailwind's `font-manrope` and `font-display` resolve
   `var(--font-manrope)` / `var(--font-instrument-serif)`, so without those
   classes on an ancestor the variables are simply undefined and the browser
   falls back to a system sans. The first render of this card did exactly that
   and produced a headline in Helvetica, which looked like a plausible design
   choice rather than a bug. */
const fontClasses = [
  ...new Set(
    (fs.readFileSync(path.join(OUT, "index.html"), "utf8").match(/__variable_[a-z0-9]+/g) ?? [])
  ),
].join(" ");
if (!fontClasses) {
  console.error(
    "no `__variable_*` font classes found in out/index.html — the card would " +
    "render in a system font. Has next/font been removed?"
  );
  process.exit(1);
}

/* The logo mark, copied from components/Logo.tsx with the accent arc at its
   RESTED angle. On the site the arc animates from -230deg to -50deg on load and
   the CSS holds it at -50; a still image has to state that end position itself,
   or the mark is rendered mid-animation. */
const MARK = `
<svg width="64" height="64" viewBox="0 0 64 64" fill="none">
  <circle cx="32" cy="32" r="24" stroke="#ffffff" stroke-opacity="0.2" stroke-width="3"/>
  <circle cx="32" cy="32" r="24" stroke="#4f71cc" stroke-width="5" stroke-linecap="round"
          stroke-dasharray="29.3 121.5" transform="rotate(-50 32 32)"/>
  <path d="M20,33 L28,41 L45,22" stroke="#ffffff" stroke-width="6.5"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
${css.map((h) => `<link rel="stylesheet" href="${h}">`).join("\n")}
<style>
  html,body { margin:0; padding:0; background:#020a18; }
  .card { position:relative; width:1200px; height:630px; overflow:hidden; background:#020a18; }
  .art  { position:absolute; inset:0; }
  .art img { width:100%; height:100%; object-fit:cover; object-position:62% center; }
  /* The same two-gradient scrim the hero uses, so the type sits on the same
     floor it does on the page. */
  .scrim { position:absolute; inset:0;
    background:
      linear-gradient(100deg, rgba(2,8,22,0.94) 0%, rgba(2,8,22,0.82) 26%, rgba(2,8,22,0.36) 48%, rgba(2,8,22,0) 66%),
      radial-gradient(60% 60% at 4% 100%, rgba(2,8,22,0.8), rgba(2,8,22,0) 72%); }
  .body { position:absolute; inset:0; padding:64px 72px; display:flex; flex-direction:column;
          justify-content:space-between; color:#fff; }
  .lockup { display:flex; align-items:center; gap:18px; }
  .wordmark { font-weight:700; font-size:38px; letter-spacing:-0.02em; line-height:1; }
  .eyebrow { font-size:17px; font-weight:600; letter-spacing:0.18em; text-transform:uppercase;
             color:rgba(255,255,255,0.55); }
  h1 { margin:18px 0 0; font-size:62px; line-height:1.04; letter-spacing:-0.02em; font-weight:400;
       max-width:15ch; }
  h1 em { font-style:italic; }
  .chips { margin-top:26px; font-size:19px; color:rgba(255,255,255,0.62); }
</style></head>
<body>
  <div class="card ${fontClasses} font-manrope">
    <div class="art"><img src="/hero/space-earth.webp" alt=""></div>
    <div class="scrim"></div>
    <div class="body">
      <div class="lockup">${MARK}<span class="wordmark">PracticeSync</span></div>
      <div>
        <div class="eyebrow">The AI-first platform for Indian CA firms</div>
        <h1 class="font-display">Run your entire practice <em>on one intelligent platform.</em></h1>
        <div class="chips">GST &middot; Income Tax &middot; TDS &middot; MCA &middot; Accounting &middot; Payroll</div>
      </div>
    </div>
  </div>
</body></html>`;

const fixture = path.join(OUT, "__og.html");
fs.writeFileSync(fixture, html);

// Serve `out/` so the artwork and the stylesheets resolve at their real paths.
const types = { ".html": "text/html", ".css": "text/css", ".webp": "image/webp",
                ".woff2": "font/woff2", ".js": "text/javascript", ".svg": "image/svg+xml" };
const server = createServer((req, res) => {
  const file = path.join(OUT, decodeURIComponent(req.url.split("?")[0]));
  if (!file.startsWith(OUT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404).end();
    return;
  }
  res.writeHead(200, { "content-type": types[path.extname(file)] ?? "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;

const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM ?? "/opt/pw-browsers/chromium",
  args: ["--no-sandbox"],
});
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
await page.goto(`http://127.0.0.1:${port}/__og.html`, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(400);
// JPEG, not PNG: the card is a photograph with type over it, and the PNG
// of it came out at 1021KB. Several consumers refuse a large preview
// outright and every one of them is fetched before the page is.
await page.screenshot({ path: TARGET, type: "jpeg", quality: 88 });
await browser.close();
server.close();
fs.unlinkSync(fixture);

const kb = Math.round(fs.statSync(TARGET).size / 1024);
console.log(`public/og.jpg  1200x630  ${kb} KB  (fonts: ${fontClasses})`);
