/**
 * Finds loading flags that a rejected request can strand.
 *
 * THE BUG
 *     The shape is everywhere in this app:
 *
 *         setLoading(true);
 *         const { data } = await supabase.from("customers").select("*");
 *         setCustomers(data ?? []);
 *         setLoading(false);
 *
 *     If the await rejects — the network drops, Supabase returns a 5xx that
 *     supabase-js throws on, a token refresh fails — control leaves the
 *     function at the await. `setLoading(false)` never runs. The skeleton spins
 *     for as long as the CA is willing to watch it, and the only way out is a
 *     page reload. Nothing is logged and nothing is shown; it just hangs.
 *
 *     The same shape with `setSaving` is worse: the Save button stays disabled,
 *     so a failed submit looks identical to one still in progress, and the CA
 *     cannot retry.
 *
 * THE RULE
 *     A function that raises a flag and awaits must lower that flag in a
 *     `finally`. Not "somewhere on the happy path", and not "after a
 *     try/catch" either — a `catch` that itself throws, or a `return` added
 *     inside the `try` later, both skip a trailing call. `finally` is the only
 *     placement the language guarantees.
 *
 *     Guard clauses that lower the flag early (`if (!clientId) {
 *     setLoading(false); return; }`) are fine and are not what this looks for.
 *     It asks one question: is there a `finally` in this function that lowers
 *     this flag?
 *
 * WHAT IT SKIPS
 *     A function with no `await` of its own cannot be stranded by a rejection
 *     it never waits for, so a synchronous raise/lower pair is not reported.
 */
import ts from "typescript";

/** State flags whose whole purpose is to disable the UI until work finishes. */
const FLAG = /^set([A-Z]\w*)?(Loading|Busy|Saving|Submitting|Sending|Posting|Running|Generating|Uploading|Deleting|Refreshing)$/;

export interface StrandedFlag {
  file: string;
  /** 1-based line of the `setX(true)` that can be left raised. */
  line: number;
  /** The setter, e.g. "setLoading". */
  flag: string;
}

type FnLike = ts.FunctionDeclaration | ts.FunctionExpression | ts.ArrowFunction | ts.MethodDeclaration;

function isFnWithBlock(n: ts.Node): n is FnLike {
  return (ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n) ||
          ts.isArrowFunction(n) || ts.isMethodDeclaration(n)) &&
         n.body !== undefined && ts.isBlock(n.body);
}

/** The innermost function that owns this node. */
function owningFunction(node: ts.Node): FnLike | null {
  let p: ts.Node | undefined = node.parent;
  while (p && !isFnWithBlock(p)) p = p.parent;
  return p ? (p as FnLike) : null;
}

/** Walk a function body without descending into functions nested inside it. */
function walkOwnBody(fn: FnLike, visit: (n: ts.Node) => void): void {
  const walk = (n: ts.Node): void => {
    if (n !== fn && isFnWithBlock(n)) return;
    visit(n);
    ts.forEachChild(n, walk);
  };
  ts.forEachChild(fn.body as ts.Block, walk);
}

/** `setX(true)` / `setX(false)` for a flag-shaped setter. */
function flagCall(n: ts.Node, sf: ts.SourceFile, want: ts.SyntaxKind): string | null {
  if (!ts.isCallExpression(n) || n.arguments.length !== 1) return null;
  if (n.arguments[0].kind !== want) return null;
  const name = n.expression.getText(sf);
  return FLAG.test(name) ? name : null;
}

/** Every flag this file can strand. */
export function findStrandedFlags(fileName: string, source: string): StrandedFlag[] {
  const sf = ts.createSourceFile(
    fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: StrandedFlag[] = [];
  const seen = new Set<string>();

  const inspect = (fn: FnLike): void => {
    const raises = new Map<string, number>();   // flag -> line of the first raise
    let awaits = false;
    walkOwnBody(fn, (n) => {
      if (ts.isAwaitExpression(n)) awaits = true;
      const raised = flagCall(n, sf, ts.SyntaxKind.TrueKeyword);
      if (raised && !raises.has(raised)) {
        raises.set(raised, sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1);
      }
    });
    if (!awaits || raises.size === 0) return;

    // Flags lowered inside a `finally` anywhere in this function.
    const safe = new Set<string>();
    walkOwnBody(fn, (n) => {
      if (!ts.isTryStatement(n) || !n.finallyBlock) return;
      const scan = (m: ts.Node): void => {
        const lowered = flagCall(m, sf, ts.SyntaxKind.FalseKeyword);
        if (lowered) safe.add(lowered);
        ts.forEachChild(m, scan);
      };
      ts.forEachChild(n.finallyBlock, scan);
    });

    // Does the function ever intend to lower it? A flag that is raised and
    // never lowered anywhere is a different bug (a permanent spinner by
    // construction) and not what this rule is about.
    const lowered = new Set<string>();
    walkOwnBody(fn, (n) => {
      const l = flagCall(n, sf, ts.SyntaxKind.FalseKeyword);
      if (l) lowered.add(l);
    });

    raises.forEach((line, flag) => {
      if (safe.has(flag) || !lowered.has(flag)) return;
      const key = `${line}:${flag}`;
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ file: fileName, line, flag });
    });
  };

  const walk = (n: ts.Node): void => {
    if (isFnWithBlock(n)) inspect(n);
    ts.forEachChild(n, walk);
  };
  walk(sf);
  out.sort((a, b) => a.line - b.line);
  return out;
}

export { owningFunction };
