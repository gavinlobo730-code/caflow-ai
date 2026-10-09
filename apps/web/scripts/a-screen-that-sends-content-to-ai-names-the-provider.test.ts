// A screen that sends typed or uploaded content to an AI provider says which provider,
// before the button is pressed (PRE-A-006).
//
// Run with: node --experimental-strip-types --test scripts/a-screen-that-sends-content-to-ai-names-the-provider.test.ts
//
// THE DEFECT. The invoice Extract box, the statement scan opt-in and the AI Assistant
// said "AI" and nothing more: not who receives the file, not that it leaves India. The
// providers were named only on the Partner-only AI status screen, which the CA who
// uploads a client's bill never opens.
//
// THE RULE, not the three screens it was found on: any file under app/ or components/
// that makes a call which sends content a person typed or uploaded to a model must
// render <AiDisclosure> for THAT call's surface, with a surface that
// lib/ai/disclosure.ts holds. The calls are named below by the identifier a screen
// writes (a URL or an API-client method), each mapped to the one surface it needs, so
// rendering the assistant's sentence on the invoice screen does not satisfy it.
//
// WHAT THIS CANNOT SEE, said so it is not mistaken for coverage: a screen that reaches
// one of these routes by a spelling not listed (a destructured client, a URL built from
// parts) is invisible here. The other half of the chain is on the Python side:
// apps/api/tests/test_the_ai_disclosure_names_the_providers_the_code_calls.py fails when
// a backend module starts calling a provider without being classified as a surface or
// named as one that sends no typed or uploaded content, so a NEW kind of AI screen is
// forced through a person who adds its trigger here. That test also holds the provider
// list of each surface to what the backend really calls.
//
// WHAT IS DELIBERATELY NOT HERE: the three screens that show a model's sentence beside
// figures the product itself computed (statement analysis, the executive view, the
// morning digest). The CA types and uploads nothing on them, so there is no content to
// disclose; each is listed below with its reason and checked for being still true.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";
import { AI_DISCLOSURES, type AiDisclosureSurface } from "../lib/ai/disclosure.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

/** What a screen writes when it sends typed or uploaded content to a model → the
 *  surface whose sentence it has to show. */
const TRIGGERS: Record<string, AiDisclosureSurface> = {
  "/api/document-intelligence-v1/extract-invoice": "invoice_extraction",
  "/api/document-intelligence-v2/notices/extract": "notice_extraction",
  "api.assistant.ask": "assistant",
  "allow_vision": "statement_scan",
  "copilotV2.sendMessage": "copilot",
};

/** Screens that call a model route and send it no content a person typed or
 *  uploaded. Frozen: an entry leaves when the screen stops calling the route. */
const FIGURES_ONLY: Record<string, { calls: string; reason: string }> = {
  "components/accounting/StatementAnalysisPanel.tsx": {
    calls: "statementAnalysis",
    reason: "narrates the revenue, expenses and profit in rupees for two years and the ratios the ledger computes, with no client name; the CA presses a button and types nothing",
  },
  "app/executive-dashboard/page.tsx": {
    calls: "executiveDashboard",
    reason: "a sentence beside counts and labels the product computed; nothing is typed or uploaded",
  },
  "components/insights/DigestPanel.tsx": {
    calls: "api.intelligence.digest",
    reason: "the morning digest narrates computed counts; the server decides whether a model is asked at all",
  },
};

function sourceFiles(): { rel: string; code: string }[] {
  const out: { rel: string; code: string }[] = [];
  for (const top of ["app", "components"]) {
    const walk = (dir: string) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name);
        if (e.isDirectory()) {
          if (e.name === "node_modules" || e.name === ".next") continue;
          walk(full);
        } else if (/\.tsx?$/.test(e.name) && !/\.(test|spec)\.tsx?$/.test(e.name)) {
          // Only app/ and components/ are walked: lib/api DEFINES these calls and is not a caller.
          const rel = path.relative(WEB, full).split(path.sep).join("/");
          out.push({ rel, code: stripComments(fs.readFileSync(full, "utf8")) });
        }
      }
    };
    walk(path.join(WEB, top));
  }
  return out;
}

const FILES = sourceFiles();

/** The surfaces a file's code calls for. */
function surfacesCalledFor(code: string): AiDisclosureSurface[] {
  const found = new Set<AiDisclosureSurface>();
  for (const [needle, surface] of Object.entries(TRIGGERS)) if (code.includes(needle)) found.add(surface);
  return [...found];
}

/** The surfaces a file renders: `<AiDisclosure surface="x"`, and the component
 *  imported from the one place it lives. */
function surfacesRendered(code: string): { surfaces: string[]; importsIt: boolean } {
  const surfaces = [...code.matchAll(/<AiDisclosure\b[^>]*?\bsurface=(?:"([a-z_]+)"|\{"([a-z_]+)"\})/g)].map((m) => m[1] ?? m[2]);
  const importsIt = /import\s*\{[^}]*\bAiDisclosure\b[^}]*\}\s*from\s*"@\/components\/ai\/AiDisclosure"/.test(code);
  return { surfaces, importsIt };
}

const CALLERS = FILES.map((f) => ({ ...f, needs: surfacesCalledFor(f.code) })).filter((f) => f.needs.length > 0);

test("the scan finds the screens it is about (so it cannot pass by finding none)", () => {
  assert.ok(CALLERS.length >= 5, `found ${CALLERS.length} screens that send content to a model: ${CALLERS.map((c) => c.rel).join(", ")}`);
  const surfaces = new Set(CALLERS.flatMap((c) => c.needs));
  for (const s of Object.keys(AI_DISCLOSURES)) assert.ok(surfaces.has(s as AiDisclosureSurface), `no screen was found for the ${s} surface`);
  const names = CALLERS.map((c) => c.rel);
  for (const must of [
    "components/purchases/PurchaseBillEditor.tsx",
    "components/banking/AccountsPanel.tsx",
    "app/ai-assistant/page.tsx",
  ]) assert.ok(names.includes(must), `${must} is not recognised as a screen that sends content to a model`);
});

test("every trigger names a surface lib/ai/disclosure.ts holds", () => {
  for (const [needle, surface] of Object.entries(TRIGGERS)) {
    assert.ok(surface in AI_DISCLOSURES, `${needle} → ${surface}, which has no sentence`);
  }
});

test("a screen that sends content to a model renders the disclosure for each surface it sends to", () => {
  const failures: string[] = [];
  for (const c of CALLERS) {
    const { surfaces, importsIt } = surfacesRendered(c.code);
    if (!importsIt) failures.push(`${c.rel}: does not import AiDisclosure from "@/components/ai/AiDisclosure"`);
    for (const need of c.needs) {
      if (!surfaces.includes(need)) failures.push(`${c.rel}: sends content to a model (${need}) and does not render <AiDisclosure surface="${need}" />`);
    }
    for (const s of surfaces) {
      if (!(s in AI_DISCLOSURES)) failures.push(`${c.rel}: renders surface "${s}", which lib/ai/disclosure.ts does not hold`);
    }
  }
  assert.deepEqual(failures, [], "name the provider before the CA presses the button — see lib/ai/disclosure.ts");
});

test("a disclosure is rendered only where something is sent (no orphan notices)", () => {
  // A notice on a screen that sends nothing is a claim about a call that is not
  // there, and it would outlive the call it described.
  const orphans: string[] = [];
  for (const f of FILES) {
    if (f.rel === "components/ai/AiDisclosure.tsx") continue;
    const { surfaces } = surfacesRendered(f.code);
    const needs = new Set(surfacesCalledFor(f.code));
    for (const s of surfaces) if (!needs.has(s as AiDisclosureSurface)) orphans.push(`${f.rel}: renders "${s}" and makes no call that sends to it`);
  }
  assert.deepEqual(orphans, []);
});

test("the screens left out for sending only computed figures still do, and still call their route", () => {
  for (const [rel, { calls, reason }] of Object.entries(FIGURES_ONLY)) {
    const f = FILES.find((x) => x.rel === rel);
    assert.ok(f, `${rel} is listed (${reason}) and no longer exists — delete its entry`);
    assert.ok(f.code.includes(calls), `${rel} no longer calls ${calls} — delete its entry`);
    assert.deepEqual(surfacesCalledFor(f.code), [], `${rel} now sends content a person typed or uploaded: give it a surface instead of listing it here`);
  }
});

// ── the detectors read what they claim ──────────────────────────────────────────
test("the detectors: a call is found, a comment is not, the wrong surface does not satisfy it", () => {
  const caller = stripComments('const r = await fetch(`${API}/api/document-intelligence-v1/extract-invoice`, {});');
  assert.deepEqual(surfacesCalledFor(caller), ["invoice_extraction"]);
  const quoted = stripComments('// calls /api/document-intelligence-v1/extract-invoice\nconst x = 1;');
  assert.deepEqual(surfacesCalledFor(quoted), []);

  const wrong = stripComments(
    'import { AiDisclosure } from "@/components/ai/AiDisclosure";\n<AiDisclosure surface="assistant" />');
  const r = surfacesRendered(wrong);
  assert.ok(r.importsIt);
  assert.deepEqual(r.surfaces, ["assistant"]);
  assert.ok(!r.surfaces.includes("invoice_extraction"));

  const noImport = surfacesRendered('<AiDisclosure surface="copilot" className="x" />');
  assert.equal(noImport.importsIt, false);
  assert.deepEqual(noImport.surfaces, ["copilot"]);
  assert.deepEqual(surfacesRendered("<div>nothing</div>").surfaces, []);
});
