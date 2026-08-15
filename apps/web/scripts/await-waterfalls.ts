/**
 * Finds request waterfalls: two network calls awaited one after the other when
 * nothing about the second depends on the first.
 *
 * WHY THIS EXISTS
 *     Every avoidable `await` in a page's loader costs a full round trip to
 *     Supabase or the API before the screen can paint. Three in a row is three
 *     times the latency for exactly the same data. That is the difference a CA
 *     feels between "instant" and "a bit slower than QuickBooks", and it is
 *     invisible in review because each individual line looks fine.
 *
 * WHY IT PARSES INSTEAD OF GREPPING
 *     The first version counted `await` lines by brace depth and reported 207
 *     hits, nearly all wrong: awaits in two different functions that happened
 *     to share an indentation level, the two halves of an if/else, and — most
 *     often — a token read on one line and used three lines later inside a
 *     template literal, which a line-at-a-time scan cannot see is a real
 *     dependency. TypeScript's own parser answers all three exactly.
 *
 * WHY IT MATCHES ON THE ROOT OF THE CALL CHAIN, NOT ON TEXT
 *     The second version regexed the awaited expression for /supabase\./ and
 *     found nothing in the file it was written for, because the code reads
 *
 *         await supabase
 *           .from("bank_transactions")
 *
 *     and the dot is on the next line. Every multi-line Supabase chain in the
 *     app — which is most of them — was silently invisible. Walking down to the
 *     leftmost identifier has no such blind spot.
 *
 * THE RULE
 *     Two awaited network calls, A then B, in the SAME statement list, are an
 *     avoidable waterfall when no statement from A+1 through B mentions any
 *     name that A bound. Anything referencing A's result — including a guard
 *     like `if (!res.success) return;` — makes B genuinely dependent, because
 *     hoisting B above that guard would fire a request the code chose not to.
 *
 *     "Same statement list" is what separates the branches of an if/else and
 *     the body of a loop: those are different blocks, examined on their own,
 *     so a conditional call is never paired with the one after it.
 *
 * WHAT COUNTS AS ONE STEP
 *     `await Promise.all([...])` is a single step however many requests are
 *     inside it — that is the shape this file exists to encourage.
 */
import ts from "typescript";

/**
 * The leftmost identifier of a call chain, when it names something that goes
 * over the wire. `supabase`/`sb` cover every PostgREST chain, `api` the typed
 * client, and the rest are the hand-rolled fetch helpers each workspace page
 * declares at the top of its own file.
 */
const NETWORK_ROOTS = new Set([
  "supabase", "sb", "api",
  "selectAll", "apiFetch", "apiCall", "apiGet", "apiPost", "fetch",
  "getSupabaseClient",
]);

export interface Waterfall {
  file: string;
  /** 1-based line of the earlier call. */
  line: number;
  /** 1-based line of the call that could have run alongside it. */
  nextLine: number;
  first: string;
  second: string;
}

/** Peel a call/property/assertion chain down to its leftmost identifier. */
function rootIdentifier(node: ts.Node): string | null {
  let n: ts.Node = node;
  for (;;) {
    if (ts.isCallExpression(n) || ts.isPropertyAccessExpression(n) ||
        ts.isElementAccessExpression(n)) {
      n = n.expression;
    } else if (ts.isTaggedTemplateExpression(n)) {
      n = n.tag;
    } else if (ts.isNonNullExpression(n) || ts.isParenthesizedExpression(n) ||
               ts.isAsExpression(n) || ts.isAwaitExpression(n) ||
               ts.isTypeAssertionExpression(n)) {
      n = n.expression;
    } else {
      break;
    }
  }
  return ts.isIdentifier(n) ? n.text : null;
}

/** Does this expression reach the network — directly, or through the array
 *  handed to `Promise.all`? */
function isNetworkCall(expr: ts.Node): boolean {
  const root = rootIdentifier(expr);
  if (root && NETWORK_ROOTS.has(root)) return true;
  let found = false;
  const scan = (n: ts.Node): void => {
    if (found) return;
    if (ts.isCallExpression(n)) {
      const r = rootIdentifier(n);
      if (r && NETWORK_ROOTS.has(r)) { found = true; return; }
    }
    ts.forEachChild(n, scan);
  };
  ts.forEachChild(expr, scan);
  return found;
}

/** Names a statement introduces or overwrites — `const x =`, `let [a, b] =`,
 *  and plain `x = ...` reassignment of a variable declared further up. */
function boundNames(stmt: ts.Statement): Set<string> {
  const names = new Set<string>();
  const collectBinding = (name: ts.BindingName): void => {
    if (ts.isIdentifier(name)) {
      names.add(name.text);
    } else {
      for (const el of name.elements) {
        if (ts.isBindingElement(el)) collectBinding(el.name);
      }
    }
  };
  if (ts.isVariableStatement(stmt)) {
    for (const decl of stmt.declarationList.declarations) collectBinding(decl.name);
  }
  const collectAssignments = (n: ts.Node): void => {
    if (ts.isBinaryExpression(n) &&
        n.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      const t = n.left;
      if (ts.isIdentifier(t)) names.add(t.text);
      else if (ts.isPropertyAccessExpression(t)) {
        const r = rootIdentifier(t);
        if (r) names.add(r);
      } else {
        // Destructured reassignment: ({ a } = x) / ([a] = x)
        const inner = (m: ts.Node): void => {
          if (ts.isIdentifier(m)) names.add(m.text);
          ts.forEachChild(m, inner);
        };
        inner(t);
      }
    }
    ts.forEachChild(n, collectAssignments);
  };
  collectAssignments(stmt);
  return names;
}

/** Every identifier a statement mentions, nested callbacks included — a name
 *  used inside a `.then()` is still a use. */
function referencedNames(node: ts.Node): Set<string> {
  const names = new Set<string>();
  const walk = (n: ts.Node): void => {
    if (ts.isIdentifier(n)) names.add(n.text);
    ts.forEachChild(n, walk);
  };
  ts.forEachChild(node, walk);
  return names;
}

/**
 * The awaited network call this statement makes in its own straight line, if
 * any.
 *
 * Does not descend into nested functions (the awaits inside
 * `Promise.all(rows.map(async …))` belong to those callbacks and already run
 * together), nor into if/loop/try/switch bodies — those are separate statement
 * lists with their own examination, and a call that only happens under a
 * condition must never be paired with the one after it.
 */
function ownNetworkAwait(stmt: ts.Statement): ts.AwaitExpression | null {
  let found: ts.AwaitExpression | null = null;
  const walk = (n: ts.Node): void => {
    if (found) return;
    if (ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n) ||
        ts.isArrowFunction(n) || ts.isMethodDeclaration(n) ||
        ts.isClassDeclaration(n) || ts.isBlock(n) ||
        ts.isIfStatement(n) || ts.isTryStatement(n) ||
        ts.isSwitchStatement(n) || ts.isIterationStatement(n, false) ||
        ts.isConditionalExpression(n) || ts.isLabeledStatement(n)) return;
    if (ts.isAwaitExpression(n) && isNetworkCall(n.expression)) {
      found = n;
      return;
    }
    ts.forEachChild(n, walk);
  };
  walk(stmt);
  return found;
}

function firstLine(text: string): string {
  return text.split("\n")[0].trim().slice(0, 110);
}

/** Every avoidable waterfall in one source file. */
export function findWaterfalls(fileName: string, source: string): Waterfall[] {
  const sf = ts.createSourceFile(
    fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: Waterfall[] = [];

  const examine = (statements: readonly ts.Statement[]): void => {
    const steps: number[] = [];
    statements.forEach((stmt, i) => {
      if (ownNetworkAwait(stmt)) steps.push(i);
    });

    for (let s = 0; s + 1 < steps.length; s++) {
      const a = steps[s];
      const b = steps[s + 1];
      const bound = boundNames(statements[a]);
      let dependent = false;
      for (let k = a + 1; k <= b && !dependent; k++) {
        referencedNames(statements[k]).forEach((name) => {
          if (bound.has(name)) dependent = true;
        });
      }
      if (dependent) continue;
      out.push({
        file: fileName,
        line: sf.getLineAndCharacterOfPosition(statements[a].getStart(sf)).line + 1,
        nextLine: sf.getLineAndCharacterOfPosition(statements[b].getStart(sf)).line + 1,
        first: firstLine(statements[a].getText(sf)),
        second: firstLine(statements[b].getText(sf)),
      });
    }
  };

  const walk = (node: ts.Node): void => {
    if (ts.isBlock(node) || ts.isSourceFile(node) ||
        ts.isCaseClause(node) || ts.isDefaultClause(node)) {
      examine(node.statements);
    }
    ts.forEachChild(node, walk);
  };
  walk(sf);
  return out;
}

/** Source files under a directory, excluding tests and build output. */
export function sourceFilesUnder(
  dir: string,
  fs: typeof import("node:fs"),
  path: typeof import("node:path"),
): string[] {
  const out: string[] = [];
  const walk = (d: string): void => {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || entry.name === ".next") continue;
        walk(p);
      } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
        out.push(p);
      }
    }
  };
  walk(dir);
  return out.sort();
}
