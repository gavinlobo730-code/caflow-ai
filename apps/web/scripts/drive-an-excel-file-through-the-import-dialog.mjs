#!/usr/bin/env node
/**
 * MANUAL TOOL, NOT A TEST: choose a real Excel workbook in the import dialog, in a
 * real browser, and read what the preview made of it (PRE-A-001, 08-10-2026).
 *
 *   pnpm smoke:build && node scripts/drive-an-excel-file-through-the-import-dialog.mjs
 *   node scripts/drive-an-excel-file-through-the-import-dialog.mjs --shots     # screenshots in .drive/
 *
 * It is not wired into `pnpm test`, no workflow runs it and it is not a required
 * check: it needs a completed `smoke:build` and Playwright, which — like the
 * smoke walk (`scripts/smoke-walk.mjs`, whose header says why) — is not a
 * dependency of this package. Install it beside the build when you want to run
 * this:  cd apps/web && pnpm add -D @playwright/test   (and do not commit it).
 * It needs no secrets, no database and no API: the same-origin stub the smoke
 * build is compiled against answers the sign-in guard, and this script records
 * every request it receives.
 *
 * WHY IT EXISTS. The import dialog's Excel path had only ever been held by source
 * guards and by unit tests that never opened a file the way a person does. Driving
 * it found that a workbook with its dates exactly as Excel writes them (built-in
 * short date, d-mmm-yy) was refused row by row, because the dialog turned the
 * sheet into text with the cells' DISPLAY format: `3/15/25`. The unit tests that
 * fixed it (`lib/spreadsheet/xlsxCsv.test.ts`, `importTemplate.test.ts`) build
 * their workbooks in node; this opens the file in the browser the CA uses and
 * checks the screen. Run it after changing `components/CsvImportModal.tsx`,
 * `lib/spreadsheet/*` or the SheetJS version.
 *
 * WHAT IT CHECKS, on Payroll > People > Import (a screen whose import has date
 * columns and needs no client to reach the preview):
 *   1. a workbook whose date cells are Excel's built-in short date and `d-mmm-yy`
 *      previews every date as yyyy-mm-dd, with no two-digit year and no month-first
 *      text in any cell, and every row valid;
 *   2. a date typed as TEXT (dd/mm/yyyy) is left exactly as typed, for the server's
 *      own day-first rule to read;
 *   3. a time-of-day cell and a number are not turned into dates;
 *   4. the Excel template, downloaded and uploaded again untouched, reports "No
 *      data rows found" — not two valid rows;
 *   5. nothing is posted to the API while a file is only being previewed.
 *
 * It exits 1 if any check fails, 2 if it cannot run (no build, no Playwright).
 * The workbook is built here with the SAME SheetJS the page ships, and cells carry
 * Excel's number formats (`m/d/yy` is what format id 14 reads back as).
 */
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : fallback;
};
const SHOTS = argv.includes("--shots");
/** The port `pnpm smoke:build` compiled into the bundle (4319 unless SMOKE_PORT says otherwise). */
const PORT = Number(flag("--port", process.env.SMOKE_PORT || 4319));
const OUT = path.resolve(flag("--out", path.join(__dirname, "..", "out")));
const SHOT_DIR = path.join(__dirname, "..", ".drive");

if (!fs.existsSync(path.join(OUT, "index.html"))) {
  console.error(`No build at ${OUT}. Run  pnpm smoke:build  first (or pass --out <dir>).`);
  process.exit(2);
}

let chromium;
try {
  // PLAYWRIGHT_MODULE points at a Playwright already on the machine (a path to its
  // index.mjs) for a checkout that has not added it.
  const pw = await import(process.env.PLAYWRIGHT_MODULE || "@playwright/test");
  chromium = pw.chromium ?? pw.default?.chromium;
} catch {
  console.error("@playwright/test is not installed. cd apps/web && pnpm add -D @playwright/test  (do not commit it),\n" +
    "or set PLAYWRIGHT_MODULE to the path of a Playwright index.mjs that is already on this machine.");
  process.exit(2);
}
const XLSX = await import("xlsx");
const X = XLSX.default ?? XLSX;

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

// ── the stub the smoke build is compiled against ─────────────────────────────

const USER = { id: "00000000-0000-4000-8000-000000000001", aud: "authenticated", role: "authenticated",
  email: "drive-tool", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" };
const SESSION = { access_token: "drive.token", token_type: "bearer", expires_in: 3600, expires_at: 4102444800,
  refresh_token: "drive.refresh", user: USER };
const USERS_ROW = { id: "00000000-0000-4000-8000-000000000002", auth_user_id: USER.id, role: "Partner",
  firm_id: "00000000-0000-4000-8000-0000000000f1", full_name: "Drive Tool" };
const FIRM_ROW = { id: USERS_ROW.firm_id, name: "Drive & Co., Chartered Accountants" };
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain", ".woff2": "font/woff2" };
const posted = [];

function json(res, body, status = 200) {
  const s = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(s) });
  res.end(s);
}
function built(url) {
  for (const candidate of [url, url.replace(/^\/clients\/[0-9a-f-]{36}\//i, "/clients/_placeholder/")]) {
    let f = path.join(OUT, candidate);
    if (!path.extname(f)) f = path.join(f, "index.html");
    if (fs.existsSync(f) && fs.statSync(f).isFile()) return f;
  }
  return null;
}
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split("?")[0]);
  const wantsObject = String(req.headers.accept || "").includes("vnd.pgrst.object+json");
  if (url.startsWith("/__supabase/auth/v1/")) return json(res, url.endsWith("/user") ? USER : url.endsWith("/logout") ? {} : SESSION);
  if (url.startsWith("/__supabase/rest/v1/users")) return json(res, wantsObject ? USERS_ROW : [USERS_ROW]);
  if (url.startsWith("/__supabase/rest/v1/firms")) return json(res, wantsObject ? FIRM_ROW : [FIRM_ROW]);
  if (url.startsWith("/__supabase/rest/")) return json(res, wantsObject ? null : []);
  if (url.startsWith("/__supabase/storage/")) return json(res, []);
  if (url.startsWith("/__supabase/")) return json(res, {});
  if (url.startsWith("/__api/")) {
    if (req.method !== "GET") posted.push(`${req.method} ${url}`);
    return json(res, { success: true, data: [], error: null });
  }
  const file = built(url);
  if (!file) { res.writeHead(404, { "content-type": "text/plain" }); return res.end("not found"); }
  res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((resolve) => server.listen(PORT, "127.0.0.1", resolve));

// ── the workbook: dates as Excel writes them ─────────────────────────────────

// 15 March 2025 is serial 45731 and 25 March 2025 is 45741 in the 1900 date system.
const workbook = () => {
  // `basic` is the one other required column of this import, so a row is valid when
  // its dates are.
  const head = ["client_name", "employee_code", "name", "date_of_birth", "joining_date", "basic"];
  const rows = [
    ["Acme Traders", "E001", "Asha Rao", { t: "n", v: 45731, z: "m/d/yy" }, { t: "n", v: 45741, z: "d-mmm-yy" }, { t: "n", v: 25000 }],
    ["Acme Traders", "E002", "Bimal Das", { t: "n", v: 45731, z: "dd-mm-yyyy" }, "25/03/2025", { t: "n", v: 30000 }],
    ["Acme Traders", "E003", "Chitra Iyer", { t: "n", v: 0.5, z: "h:mm" }, { t: "n", v: 12345, z: "General" }, { t: "n", v: 27500 }],
  ];
  const ws = {};
  head.forEach((h, c) => { ws[X.utils.encode_cell({ r: 0, c })] = { t: "s", v: h }; });
  rows.forEach((row, r) => row.forEach((cell, c) => {
    ws[X.utils.encode_cell({ r: r + 1, c })] = typeof cell === "string" ? { t: "s", v: cell } : cell;
  }));
  ws["!ref"] = `A1:F${rows.length + 1}`;
  return Buffer.from(X.write({ SheetNames: ["Employees"], Sheets: { Employees: ws } }, { type: "buffer", bookType: "xlsx" }));
};

// ── the drive ────────────────────────────────────────────────────────────────

const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        ${detail}`}`);
};
const browser = await chromium.launch({ executablePath: installedChromium() });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
const refs = ["127", "localhost", "placeholder"];
await context.addInitScript(`(() => { try { for (const ref of ${JSON.stringify(refs)})
  localStorage.setItem("sb-" + ref + "-auth-token", ${JSON.stringify(JSON.stringify(SESSION))}); } catch {} })();`);
const page = await context.newPage();
const problems = [];
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) problems.push(`console.error: ${m.text()}`); });
await page.route("**/*", (route) => {
  const url = route.request().url();
  return url.startsWith(`http://127.0.0.1:${PORT}`) || url.startsWith("data:") || url.startsWith("blob:")
    ? route.continue() : route.abort();
});
const shot = async (name) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};

try {
  await page.goto(`http://127.0.0.1:${PORT}/payroll/people/`, { waitUntil: "networkidle" });
  const open = page.getByRole("button", { name: /Import CSV/i }).first();
  await open.waitFor({ timeout: 20000 });
  await open.click();
  await page.getByText("Import Employees").first().waitFor({ timeout: 10000 });

  // 1-3: a real workbook
  await page.locator('input[type="file"]').setInputFiles({
    name: "employees.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: workbook(),
  });
  await page.getByText(/valid rows/).first().waitFor({ timeout: 15000 });
  await shot("preview");
  const cells = await page.locator("table").last().locator("tbody tr").evaluateAll((trs) =>
    trs.map((tr) => Array.from(tr.querySelectorAll("td")).map((td) => (td.textContent || "").trim())));
  const flat = cells.map((r) => r.join(" | "));
  console.log("preview rows:\n  " + flat.join("\n  "));
  const [r1, r2, r3] = cells;
  check("every date cell Excel holds as a date is previewed as yyyy-mm-dd",
    r1?.includes("2025-03-15") && r1?.includes("2025-03-25") && r2?.includes("2025-03-15"),
    flat.join("\n        "));
  check("no cell shows a two-digit year or Excel's month-first text",
    !flat.some((r) => /\b\d{1,2}\/\d{1,2}\/\d{2}\b|\d{1,2}-[A-Za-z]{3}-\d{2}\b/.test(r)), flat.join("\n        "));
  check("a date typed as text is left exactly as typed", r2?.includes("25/03/2025"), flat.join("\n        "));
  check("a time of day and a plain number are not turned into dates",
    r3?.includes("12:00") && r3?.includes("12345") && !r3.some((c) => /^\d{4}-\d{2}-\d{2}$/.test(c)), flat.join("\n        "));
  check("every row of the file is previewed as valid",
    (await page.getByText(/rows with errors/).count()) === 0, "the preview reports rows with errors");
  check("nothing is posted while a file is only being previewed", posted.length === 0, posted.join(", "));

  // 4: the template, as downloaded, uploaded again
  await page.getByText(/Upload a different file/).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Download Excel/i }).click(),
  ]);
  const saved = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "drive-template-")), "employees-template.xlsx");
  await download.saveAs(saved);
  await page.locator('input[type="file"]').setInputFiles(saved);
  await page.getByText(/No data rows found/).first().waitFor({ timeout: 10000 }).catch(() => {});
  await shot("template-uploaded-untouched");
  check("the Excel template, uploaded untouched, reports no data rows",
    (await page.getByText(/No data rows found/).count()) > 0 && (await page.getByText(/valid rows/).count()) === 0,
    "the template was read as data");
  check("no page error and no console error", problems.length === 0, problems.join("\n        "));
} catch (e) {
  check("the drive ran to the end", false, String(e?.stack || e).slice(0, 600));
  await shot("failure").catch(() => {});
} finally {
  await browser.close();
  server.close();
}

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed} of ${results.length} checks passed.`);
process.exit(failed ? 1 : 0);
