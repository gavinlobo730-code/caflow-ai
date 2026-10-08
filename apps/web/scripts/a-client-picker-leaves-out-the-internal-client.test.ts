// A list of the firm's clients read straight from the browser leaves out the
// firm's own internal practice client. Run with:
//   node --experimental-strip-types --test scripts/a-client-picker-leaves-out-the-internal-client.test.ts
//
// WHAT WAS WRONG (PRE-A-017)
//     Provisioning the Practice (Revenue Operations) makes the firm a client of
//     itself: a `clients` row with `is_internal = true` (Guardrail G2). The
//     backend leaves it out of every client population by default, and
//     `lib/data/clients.getClients` filters it. But the browser also reads
//     `clients` straight over PostgREST, where only RLS stands in the way, and
//     RLS hides the internal client from non-Partners only. Eleven screens read
//     the list for a dropdown or a name map with no `is_internal = false`, so a
//     Partner who had provisioned Practice saw their own firm offered as a
//     client in payroll, GST, loans, receivables, scheduled reports and the
//     Schedule III picker - and picking it for payroll runs into the server's
//     refusal (assert_not_internal_for_payroll). Not a leak (the Partner may
//     read it); a wrong choice on offer. docs/REVENUE_OPS_BRIDGE.md B2-2 had
//     recorded the debt: "any new direct clients query must remember to exclude
//     is_internal" - a sentence nothing checked, which is how eleven came to be.
//
// THE RULE (not a list of today's files)
//   Every `.from("clients")` read in the product's own source that returns a
//   LIST of clients carries `.eq("is_internal", false)` in the same chain - or
//   the file is in EXCEPTIONS below with its reason and its exact count.
//   What is NOT a list read, and so is not asked:
//     - a write (insert / update / upsert / delete);
//     - a lookup of ONE named client or a known set (`.eq("id", ...)`,
//       `.in("id", ...)`): that is "tell me about the client I am on", not a
//       picker, and the internal client's own screens use it.
//   A count (`head: true`) is a list read and is asked.
//
// WHAT IT CANNOT SEE, AND SAYS SO
//   A `from(tableName)` whose table is a variable; a chain built across several
//   statements is followed only when it is assigned to a variable and the same
//   enclosing block later applies `.eq("is_internal", false)` to that variable;
//   the backend (`client_repo` and `clients_external` are the server's half of
//   G2 and have their own tests). Whether a screen SHOULD show the internal
//   client is decided here as "no, in a picker": the Practice screens read it
//   through `/api/practice`, not through this table.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "out") continue;
      walk(rel, out);
    } else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name)) {
      out.push(rel);
    }
  }
  return out;
}

/** The product's own source (not scripts/, which quote the forms they ban). */
const SOURCES = ["app", "components", "lib"].flatMap((d) => walk(d)).sort();

function parse(src: string, name = "x.tsx"): ts.SourceFile {
  return ts.createSourceFile(name, src, ts.ScriptTarget.ES2022, true,
    name.endsWith(".ts") ? ts.ScriptKind.TS : ts.ScriptKind.TSX);
}

const WRITES = new Set(["insert", "update", "upsert", "delete"]);

type Kind = "write" | "lookup" | "list";
export interface ClientsRead { line: number; kind: Kind; excludesInternal: boolean }

const isStringish = (n: ts.Node | undefined): n is ts.StringLiteral | ts.NoSubstitutionTemplateLiteral =>
  !!n && (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n));

/** `x.eq("is_internal", false)` */
function isInternalFalse(call: ts.CallExpression): boolean {
  const [a, b] = call.arguments;
  return isStringish(a) && a.text === "is_internal" && !!b && b.kind === ts.SyntaxKind.FalseKeyword;
}

/** Every read/write of the `clients` table in a source, classified. */
export function clientsReads(src: string, name = "x.tsx"): ClientsRead[] {
  const sf = parse(src, name);
  const reads: ClientsRead[] = [];

  (function visit(node: ts.Node) {
    // <anything>.from("clients")
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "from" &&
      isStringish(node.arguments[0]) &&
      node.arguments[0].text === "clients"
    ) {
      // Climb the call chain from the table to its last method (select, then each filter).
      const methods: { name: string; call: ts.CallExpression }[] = [];
      let top: ts.Node = node;
      for (;;) {
        const access = top.parent;
        const call = access?.parent;
        if (
          access && call &&
          ts.isPropertyAccessExpression(access) && access.expression === top &&
          ts.isCallExpression(call) && call.expression === access
        ) {
          methods.push({ name: access.name.text, call });
          top = call;
        } else break;
      }

      let kind: Kind = "list";
      if (methods.some((m) => WRITES.has(m.name))) kind = "write";
      else if (methods.some((m) => (m.name === "eq" || m.name === "in")
        && isStringish(m.call.arguments[0]) && m.call.arguments[0].text === "id")) kind = "lookup";

      let excludes = methods.some((m) => m.name === "eq" && isInternalFalse(m.call));

      // `let q = sb.from("clients")...; ... q = q.eq("is_internal", false)`
      if (!excludes && ts.isVariableDeclaration(top.parent) && ts.isIdentifier(top.parent.name)) {
        const v = top.parent.name.text;
        let block: ts.Node = top.parent;
        while (block.parent && !ts.isBlock(block) && !ts.isSourceFile(block)) block = block.parent;
        const text = block.getText(sf);
        excludes = new RegExp(`\\b${v}\\b[^;]*\\.eq\\(\\s*["']is_internal["']\\s*,\\s*false\\s*\\)`).test(text);
      }

      reads.push({
        line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
        kind,
        excludesInternal: excludes,
      });
    }
    ts.forEachChild(node, visit);
  })(sf);

  return reads;
}

/** A list read that does not exclude the internal client. */
export const unfiltered = (reads: ClientsRead[]) =>
  reads.filter((r) => r.kind === "list" && !r.excludesInternal);

/**
 * The legitimate exceptions: files that read a LIST of clients with the internal
 * one still in it, with the exact number of such reads and WHY. Asserted as an
 * equality in both directions, so it can only shrink on its own: a new
 * unfiltered list read fails until somebody writes the reason down here, and a
 * fixed one fails until its entry is deleted.
 *
 * It is empty. A picker that wants the internal client does not read this table
 * (the Practice screens go through /api/practice), so there is no exception to
 * record; the mechanism stays so the next one is a decision made in this file
 * and not in a code review.
 */
const EXCEPTIONS: Record<string, { count: number; reason: string }> = {};

const bySource = new Map(SOURCES.map((f) => [f, clientsReads(fs.readFileSync(path.join(WEB, f), "utf8"), f)]));

/** Ten of the eleven screens PRE-A-017 named (the eleventh is below). Each must still read the table directly, with the filter. */
const NAMED_SCREENS = [
  "app/payroll/attendance/page.tsx",
  "app/payroll/statutory/page.tsx",
  "app/payroll/declarations/page.tsx",
  "app/payroll/reports/page.tsx",
  "app/settings/scheduled-reports/page.tsx",
  "app/gst/gstr1/page.tsx",
  "app/gst/gstr3b/page.tsx",
  "app/accounting/loans/page.tsx",
  "app/accounting/receivables/page.tsx",
  "app/accounting/schedule-iii/page.tsx",
];
// app/notifications/whatsapp/page.tsx is the eleventh: it reads through getClients() now,
// which carries the filter, so it has no direct read to assert here (asserted separately).

test("a list of clients read from the browser leaves out the internal client", async (t) => {
  await t.test("no list read of `clients` lacks .eq(\"is_internal\", false) beyond the named exceptions", () => {
    const found: Record<string, number> = {};
    for (const [file, reads] of bySource) {
      const n = unfiltered(reads).length;
      if (n > 0) found[file] = n;
    }
    const expected = Object.fromEntries(Object.entries(EXCEPTIONS).map(([f, e]) => [f, e.count]));
    assert.deepEqual(found, expected,
      "a list of clients is read without .eq(\"is_internal\", false). Add the filter (or use getClients() from " +
      "lib/data/clients.ts); only if the screen genuinely needs the internal client add it to EXCEPTIONS with the reason. " +
      "If an entry in EXCEPTIONS is now fixed, delete it.");
  });

  await t.test("every exception carries a real reason", () => {
    for (const [file, e] of Object.entries(EXCEPTIONS)) {
      assert.ok(e.reason.trim().length >= 40, `${file}: an exception needs its reason written down`);
      assert.ok(e.count >= 1, `${file}: a count of ${e.count} is not an exception`);
    }
  });

  await t.test("the screens PRE-A-017 named still read the table directly, and with the filter", () => {
    for (const file of NAMED_SCREENS) {
      const lists = (bySource.get(file) ?? []).filter((r) => r.kind === "list");
      assert.ok(lists.length >= 1, `${file}: expected a direct read of clients (the scan has gone blind or the screen moved)`);
      assert.ok(lists.every((r) => r.excludesInternal), `${file}: reads clients without is_internal = false`);
    }
  });

  await t.test("the WhatsApp screen reads its clients through getClients(), which carries the filter", () => {
    const src = fs.readFileSync(path.join(WEB, "app/notifications/whatsapp/page.tsx"), "utf8");
    assert.match(src, /getClients\(\s*"all"\s*\)/);
    assert.deepEqual(bySource.get("app/notifications/whatsapp/page.tsx"), [],
      "the WhatsApp screen has gone back to reading clients directly");
    const helper = fs.readFileSync(path.join(WEB, "lib/data/clients.ts"), "utf8");
    const reads = clientsReads(helper, "lib/data/clients.ts");
    assert.ok(reads.some((r) => r.kind === "list" && r.excludesInternal),
      "getClients() no longer excludes the internal client");
  });

  await t.test("the scan is not vacuous: it sees many reads, of all three kinds", () => {
    const all = [...bySource.values()].flat();
    assert.ok(all.length >= 20, `only ${all.length} reads of clients found; the scan has gone blind`);
    for (const kind of ["list", "lookup", "write"] as const) {
      assert.ok(all.some((r) => r.kind === kind), `no ${kind} read of clients found`);
    }
    assert.ok(all.filter((r) => r.kind === "list" && r.excludesInternal).length >= 12,
      "fewer filtered list reads than the sweep left");
  });

  // ── the classifier itself, on synthetic sources ─────────────────────────────
  await t.test("negative control: an unfiltered picker is caught, in each spelling", () => {
    const bad = [
      `sb.from("clients").select("id, client_name").eq("firm_id", fid).order("id")`,
      `sb.from('clients').select('*').is("deleted_at", null)`,
      `selectAll(() => supabase.from(\`clients\`).select("id").eq("status", "active"))`,
      `sb.from("clients").select("id", { count: "exact", head: true }).eq("firm_id", f)`,
      `sb.from("clients").select("id").eq("is_internal", true)`,
    ];
    for (const src of bad) {
      assert.equal(unfiltered(clientsReads(`async function f(){ await ${src}; }`)).length, 1, src);
    }
  });

  await t.test("negative control: a filtered picker, a lookup and a write are not asked", () => {
    const fine = [
      `sb.from("clients").select("id, client_name").eq("firm_id", fid).eq("is_internal", false).order("id")`,
      `sb.from("clients").select("client_name").eq("id", clientId).maybeSingle()`,
      `sb.from("clients").select("id").in("id", ids)`,
      `sb.from("clients").insert({ firm_id: f, client_name: "x" })`,
      `sb.from("clients").update({ status: "archived" }).eq("id", id)`,
    ];
    for (const src of fine) {
      assert.equal(unfiltered(clientsReads(`async function f(){ await ${src}; }`)).length, 0, src);
    }
    const viaVariable = `async function f(){
      let q = sb.from("clients").select("*").is("deleted_at", null);
      if (x) q = q.neq("status", "archived");
      q = q.eq("is_internal", false);
      return q;
    }`;
    assert.equal(unfiltered(clientsReads(viaVariable)).length, 0);
    const variableNeverFiltered = `async function f(){
      let q = sb.from("clients").select("*").is("deleted_at", null);
      if (x) q = q.neq("status", "archived");
      return q;
    }`;
    assert.equal(unfiltered(clientsReads(variableNeverFiltered)).length, 1);
  });
});
