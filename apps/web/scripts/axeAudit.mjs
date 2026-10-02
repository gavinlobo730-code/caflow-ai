/**
 * The accessibility half of the smoke walk (frontend_ux-03): which screens are scanned with axe, what counts
 * as a failure, and the ratchet that keeps the rest from getting worse.
 *
 * WHY IT EXISTS. There was no automated accessibility test of any kind: no axe, no testing library. Contrast,
 * labels and focus were audited by hand once and then guarded as source rules ("every class list that removes
 * the outline draws an indicator"), which prove a property is WRITTEN and not that the page a person gets
 * passes. axe runs in the browser against the rendered page, which is the only place most of its rules can be
 * asked: a control's accessible name, a landmark's role, a colour pair as painted.
 *
 * TWO KINDS OF SCREEN, AND THE DIFFERENCE IS THE POINT.
 *   * THE SIX NAMED SCREENS (`NAMED_SCREENS`) are the ones everybody meets: sign in, sign up, the dashboard,
 *     a client's sales, the journal editor and the firm menu opened. A serious or critical violation on any
 *     of them FAILS the run outright. There is no allowlist for them and `parseBaseline` refuses an entry that
 *     names one, so nobody can quietly make one of these pass by writing it down.
 *   * EVERY OTHER SCREEN is held by a RATCHET (`axe-baseline.json`). It records what is wrong TODAY, as
 *     (route, rule, node count), and it may only shrink: a (route, rule) pair that is not in it fails as new,
 *     a count above its figure fails as grown, and a line whose violation has gone fails as stale — a fix
 *     deletes its own line in the commit that makes it, the way `scripts/ci/ruff_baseline.txt` works. A count
 *     that has FALLEN but not yet been lowered passes and is reported ("can be lowered to N"): the count is a
 *     ceiling, not an equality, because a node count is measured by a browser and a renderer's patch release
 *     must not turn a night red, while the set of pairs is exact. `--axe-shrink` lowers and deletes, and can
 *     never add or raise; `--axe-init` writes the first baseline and refuses when one exists.
 *
 * ONLY SERIOUS AND CRITICAL COUNT. axe grades every violation; moderate and minor are real but numerous, and a
 * ratchet over them would be a list nobody could burn down. The tags are WCAG 2.0 and 2.1 A and AA — the level
 * the product's own contrast audit was done against — and not axe's best-practice set.
 *
 * A WALK THAT AUDITED NOTHING IS NOT CLEAN. Every verdict here is "found nothing wrong", and that is worth
 * exactly as much as the number of pages that were asked. `settleVerdict` fails a run in which axe was
 * requested and no page was audited, a page it could not audit, and a named screen that landed somewhere
 * other than where it was sent (the walk once photographed the onboarding wizard for four days and called
 * it green, which is why every audit here is asked WHERE it ended up first).
 *
 * THE PACKAGE IS NOT A DEPENDENCY OF THE PRODUCT. `@axe-core/playwright` is added in the walk's own CI job at
 * the exact version below, beside `@playwright/test` and for the same reason (`smoke-walk.yml`): `package.json`
 * is untouched, so the job every pull request runs downloads nothing and the production bundle can never
 * include it. It is imported lazily here. Absent on a developer machine the audit is SKIPPED WITH A LOUD LINE,
 * never silently; absent in CI it is a failure (exit 2), because the workflow installs it and a missing one
 * means the workflow is broken, not that the pages are fine.
 *
 * No Playwright, no axe and no filesystem in the pure functions below, so `axe-ratchet.test.ts` can run them
 * under plain node.
 */

/** Exact. Mirrored by `AXE_PLAYWRIGHT_VERSION` in `.github/workflows/smoke-walk.yml`, and a test holds the two
 *  equal. A bump is a deliberate edit of both, followed by one by-hand run of the workflow before the next
 *  night is trusted: a newer axe-core can add a rule and turn an allowlisted page's count up. */
export const AXE_PACKAGE = "@axe-core/playwright";
export const AXE_PACKAGE_VERSION = "4.13.0";

export const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
export const FAILING_IMPACTS = ["serious", "critical"];

/**
 * The six screens a serious or critical violation fails outright.
 *
 * `route` may carry `{client}`, which the walk replaces with its stub client's id so the CLIENT WORKSPACE
 * renders its own chrome (the `--real-client` reason). `signedIn: false` means a fresh browser context with no
 * session, because `/login` and `/signup` bounce a signed-in visitor to `/` and a walk that is signed in can
 * only ever photograph the dashboard instead. `opens` names a step taken before the scan.
 *
 * The journal editor is `entryId = new`, the create-mode sentinel the page itself documents, because a real
 * entry id would resolve to nothing in a stubbed walk and the scan would be of "Journal entry not found".
 */
export const NAMED_SCREENS = [
  { id: "login", label: "Sign in", route: "/login", signedIn: false },
  { id: "signup", label: "Sign up", route: "/signup", signedIn: false },
  { id: "dashboard", label: "Dashboard", route: "/", signedIn: true },
  { id: "client-sales", label: "Client sales", route: "/clients/{client}/sales", signedIn: true },
  { id: "journal-editor", label: "Journal editor", route: "/clients/{client}/accounting/journal/new/edit", signedIn: true },
  { id: "firm-menu", label: "Firm menu, open", route: "/", signedIn: true, opens: "firm-menu" },
];

/** The routes the route-walk must NOT put in the baseline because a named screen already covers them, and so
 *  nothing about them is negotiable. Only the ones with no `{client}` placeholder: `/clients/_placeholder/sales`
 *  is a different page from a real client's sales. */
export const NAMED_ROUTE_PATHS = new Set(
  NAMED_SCREENS.filter((s) => !s.route.includes("{client}")).map((s) => s.route),
);

/** The route a named screen is asked for, with the client placeholder filled in. */
export function resolveNamedRoute(screen, clientId) {
  return screen.route.replace("{client}", clientId);
}

/** For a colour-contrast node, the measured pair, so a person reads "3.5:1, #059669 on #ecfdf5, needs 4.5:1"
 *  instead of a selector and a guess. Empty for every other rule. */
function contrastNote(node) {
  const d = node?.any?.[0]?.data;
  if (!d || typeof d !== "object" || d.contrastRatio === undefined) return "";
  return ` [${d.contrastRatio}:1, ${d.fgColor} on ${d.bgColor}, needs ${d.expectedContrastRatio}]`;
}

/**
 * What one scan found, reduced to what the ratchet judges.
 *
 * `violations` is axe's own result array. Only serious and critical are kept, one row per rule, with how many
 * nodes it hit and up to three selectors, so a failure line names something a person can find.
 */
export function failingFindings(violations) {
  const rows = [];
  for (const v of Array.isArray(violations) ? violations : []) {
    if (!FAILING_IMPACTS.includes(v?.impact)) continue;
    const nodes = Array.isArray(v.nodes) ? v.nodes : [];
    rows.push({
      rule: String(v.id),
      impact: v.impact,
      nodes: nodes.length,
      help: typeof v.help === "string" ? v.help : "",
      targets: nodes.slice(0, 3).map((n) =>
        (Array.isArray(n?.target) ? n.target.join(" ") : String(n?.target ?? "")) + contrastNote(n)),
    });
  }
  return rows.sort((a, b) => (a.rule < b.rule ? -1 : a.rule > b.rule ? 1 : 0));
}

// ── The baseline file ────────────────────────────────────────────────────────

/** Validate the baseline's text and return its entries, or throw saying what is wrong with it. */
export function parseBaseline(text) {
  let doc;
  try { doc = JSON.parse(text); } catch (e) { throw new Error(`axe baseline is not JSON: ${e.message}`); }
  if (!doc || typeof doc !== "object" || !Array.isArray(doc.entries)) {
    throw new Error("axe baseline needs an `entries` array");
  }
  const seen = new Set();
  const entries = [];
  for (const [i, e] of doc.entries.entries()) {
    const where = `axe baseline entry ${i}`;
    if (!e || typeof e.route !== "string" || !e.route.startsWith("/")) throw new Error(`${where}: route must be a path`);
    if (typeof e.rule !== "string" || !e.rule) throw new Error(`${where}: rule must be an axe rule id`);
    if (!Number.isInteger(e.nodes) || e.nodes < 1) throw new Error(`${where}: nodes must be a whole number of at least 1 (delete the line instead of writing 0)`);
    if (NAMED_ROUTE_PATHS.has(e.route)) {
      throw new Error(`${where}: ${e.route} is one of the six named screens, which fail outright and have no allowlist`);
    }
    const key = `${e.route} ${e.rule}`;
    if (seen.has(key)) throw new Error(`${where}: ${key} is listed twice`);
    seen.add(key);
    entries.push({ route: e.route, rule: e.rule, nodes: e.nodes });
  }
  return entries;
}

/** The file's text for these entries: sorted, so a diff shows what changed and nothing else. */
export function serialiseBaseline(entries) {
  const sorted = [...entries].sort((a, b) =>
    a.route < b.route ? -1 : a.route > b.route ? 1 : a.rule < b.rule ? -1 : a.rule > b.rule ? 1 : 0);
  const doc = {
    comment:
      "The accessibility ratchet (frontend_ux-03). Serious and critical axe violations on every screen the walk " +
      "visits EXCEPT the six named ones, which fail outright. It may only shrink: a fix deletes its own line (or " +
      "lowers its count) in the same commit. See scripts/axeAudit.mjs.",
    tags: AXE_TAGS,
    impacts: FAILING_IMPACTS,
    entries: sorted,
  };
  return JSON.stringify(doc, null, 2) + "\n";
}

/**
 * Judge what was found on the audited routes against the baseline.
 *
 * `found` maps a route to its failing findings (`failingFindings`), for the routes that WERE audited. A route
 * that was not audited (a partial run, `--only`) is neither judged nor reported stale — a line whose route was
 * never asked about says nothing.
 */
export function compareToBaseline(found, entries) {
  const allowed = new Map(entries.map((e) => [`${e.route} ${e.rule}`, e]));
  /** @type {{ added: Record<string, any>[], grew: Record<string, any>[], stale: Record<string, any>[], lowerable: Record<string, any>[] }} */
  const out = { added: [], grew: [], stale: [], lowerable: [] };
  const seenKeys = new Set();
  for (const [route, findings] of found) {
    for (const f of findings) {
      const key = `${route} ${f.rule}`;
      seenKeys.add(key);
      const line = allowed.get(key);
      if (!line) out.added.push({ route, rule: f.rule, impact: f.impact, nodes: f.nodes, help: f.help, targets: f.targets });
      else if (f.nodes > line.nodes) out.grew.push({ route, rule: f.rule, impact: f.impact, from: line.nodes, to: f.nodes, help: f.help, targets: f.targets });
      else if (f.nodes < line.nodes) out.lowerable.push({ route, rule: f.rule, from: line.nodes, to: f.nodes });
    }
  }
  for (const e of entries) {
    if (found.has(e.route) && !seenKeys.has(`${e.route} ${e.rule}`)) out.stale.push({ route: e.route, rule: e.rule, nodes: e.nodes });
  }
  return out;
}

/** The baseline after `--axe-shrink`: counts lowered to what was found, fixed lines removed, nothing added,
 *  nothing raised, and every line of a route that was not audited kept exactly as it was. */
export function shrinkBaseline(found, entries) {
  const kept = [];
  for (const e of entries) {
    if (!found.has(e.route)) { kept.push(e); continue; }
    const now = (found.get(e.route) ?? []).find((f) => f.rule === e.rule);
    if (!now) continue;
    kept.push({ ...e, nodes: Math.min(e.nodes, now.nodes) });
  }
  return kept;
}

/** The first baseline, from a full walk: every serious or critical finding on a route that is not a named one. */
export function initialBaseline(found) {
  const entries = [];
  for (const [route, findings] of found) {
    if (NAMED_ROUTE_PATHS.has(route)) continue;
    for (const f of findings) entries.push({ route, rule: f.rule, nodes: f.nodes });
  }
  return entries;
}

// ── Deciding whether to run, and the verdict ─────────────────────────────────

/**
 * Whether the audit runs, and the line that says so.
 *
 * `loaded` is whether `@axe-core/playwright` could be imported. The one rule worth stating twice: the audit is
 * never skipped WITHOUT SAYING SO, and in CI a missing package is fatal.
 */
export function axeMode({ disabled, loaded, ci }) {
  if (disabled) return { run: false, fatal: false, line: "axe: NOT RUN (--no-axe was passed)." };
  if (!loaded) {
    const why = `${AXE_PACKAGE} is not installed`;
    if (ci) {
      return {
        run: false, fatal: true,
        line: `axe: FAILED — ${why}, and this is CI: the workflow installs ${AXE_PACKAGE}@${AXE_PACKAGE_VERSION} for this job, ` +
          "so its absence means the workflow is broken. Refusing to report a walk that checked no accessibility.",
      };
    }
    return {
      run: false, fatal: false,
      line: `axe: NOT RUN — ${why} here. The nightly runs it. To run it locally, in apps/web: ` +
        `pnpm add -D ${AXE_PACKAGE}@${AXE_PACKAGE_VERSION}, and take it out again before committing.`,
    };
  }
  return { run: true, fatal: false, line: `axe: running ${AXE_PACKAGE}@${AXE_PACKAGE_VERSION}, tags ${AXE_TAGS.join(", ")}, impacts ${FAILING_IMPACTS.join(" and ")}.` };
}

/**
 * Fold the run into one verdict.
 *
 * `named` is one row per named screen: `{ id, label, route, landed?, error?, findings }`. `comparison` is
 * `compareToBaseline`'s answer, or null when nothing was compared. `auditedRoutes` counts pages scanned in the
 * route walk, `unaudited` lists pages axe could not scan. A failing name appears once, with its reason.
 */
export function settleVerdict({ named, comparison, auditedRoutes, unaudited, partial }) {
  const failures = [];
  for (const n of named) {
    if (n.error) failures.push({ kind: "named_unaudited", screen: n.label, route: n.route, detail: n.error });
    for (const f of n.findings ?? []) {
      failures.push({ kind: "named", screen: n.label, route: n.route, rule: f.rule, impact: f.impact, nodes: f.nodes, help: f.help, targets: f.targets });
    }
  }
  for (const u of unaudited) failures.push({ kind: "unaudited", route: u.route, detail: u.error });
  if (comparison) {
    for (const a of comparison.added) failures.push({ kind: "new", ...a });
    for (const g of comparison.grew) failures.push({ kind: "grew", ...g });
    // `compareToBaseline` only calls a line stale when its route WAS audited, so this is as true of a partial
    // walk as of a full one: a route nobody asked about is not judged either way.
    for (const s of comparison.stale) failures.push({ kind: "stale", ...s });
  }
  const audited = named.filter((n) => !n.error).length + auditedRoutes;
  const nothingAudited = audited === 0;
  return {
    ok: failures.length === 0 && !nothingAudited,
    nothingAudited,
    audited,
    failures,
    partial: Boolean(partial),
    lowerable: comparison?.lowerable ?? [],
  };
}

/** One failure, as the sentence a person reads in the log and on the summary page. */
export function describeFailure(f) {
  const where = f.screen ? `${f.screen} (${f.route})` : f.route;
  const nodes = (n) => `${n} element${n === 1 ? "" : "s"}`;
  const eg = f.targets?.length ? ` e.g. ${f.targets.join("; ")}` : "";
  switch (f.kind) {
    case "named": return `${where}: ${f.impact} ${f.rule} on ${nodes(f.nodes)} — ${f.help}.${eg} A named screen has no allowlist.`;
    case "named_unaudited": return `${where}: could not be audited — ${f.detail}`;
    case "unaudited": return `${where}: axe could not scan this page — ${f.detail}`;
    case "new": return `${where}: NEW ${f.impact} ${f.rule} on ${nodes(f.nodes)} — ${f.help}.${eg} Fix it; the baseline only shrinks.`;
    case "grew": return `${where}: ${f.rule} grew from ${nodes(f.from)} to ${nodes(f.to)} — ${f.help}.${eg}`;
    case "stale": return `${where}: ${f.rule} is in scripts/axe-baseline.json (${nodes(f.nodes)}) and no longer fires — delete that line (or run --axe-shrink).`;
    default: return `${where}: ${f.kind}`;
  }
}

/** The report block and the summary-page section. */
export function summaryMarkdown(verdict, mode) {
  const lines = [`### Accessibility (axe): ${verdict.ok ? "clean" : "FAILED"}`, ""];
  if (verdict.nothingAudited) lines.push("**No page was audited**, so this run says nothing about accessibility.", "");
  lines.push(`${verdict.audited} page(s) scanned for ${FAILING_IMPACTS.join(" and ")} WCAG A/AA violations (${mode}).`, "");
  if (verdict.partial) lines.push("This was a partial walk: baseline lines for routes it did not visit were not judged.", "");
  if (verdict.failures.length) {
    lines.push("| page | problem |", "|---|---|");
    for (const f of verdict.failures) lines.push(`| \`${f.screen ?? f.route}\` | ${describeFailure(f).replace(/\|/g, "\\|").replace(/\s+/g, " ")} |`);
    lines.push("");
  }
  if (verdict.lowerable.length) {
    lines.push(`${verdict.lowerable.length} baseline count(s) can be lowered (\`--axe-shrink\`): ` +
      verdict.lowerable.slice(0, 8).map((l) => `${l.route} ${l.rule} ${l.from} → ${l.to}`).join(", ") +
      (verdict.lowerable.length > 8 ? ", …" : "") + ".", "");
  }
  return lines.join("\n");
}

// ── The two things that touch the outside world ──────────────────────────────

/** Import the package without naming it as a literal import, so a machine that lacks it can still load the walk.
 *  Resolves to `{ AxeBuilder }` or `{ error }`. */
export async function loadAxeBuilder(importer = (name) => import(name)) {
  try {
    const mod = await importer(AXE_PACKAGE);
    const AxeBuilder = mod?.default ?? mod?.AxeBuilder ?? null;
    if (typeof AxeBuilder !== "function") return { error: `${AXE_PACKAGE} loaded but exports no AxeBuilder` };
    return { AxeBuilder };
  } catch (e) {
    return { error: String(e?.message ?? e).split("\n")[0] };
  }
}

/**
 * Scan one open page. Never throws: a page axe could not scan comes back as `{ error }`, because a walk that
 * died on its sixtieth screen would report nothing about the other hundred.
 */
export async function auditPage(AxeBuilder, page) {
  try {
    const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
    return { findings: failingFindings(result.violations) };
  } catch (e) {
    return { findings: [], error: String(e?.message ?? e).split("\n")[0].slice(0, 200) };
  }
}
