/**
 * Which overlays draw a request in flight and still let the person dismiss them (POST-A-395). Not a `.test.ts` file: the test beside it
 * (a-dialog-that-holds-close-is-freed-by-a-bounded-request.test.ts) imports it, and a self-test proves it on small sources.
 *
 * AN OVERLAY is a `<Modal>` or `<Drawer>` element or an element whose literal className holds `fixed inset-0` (a hand-built one), taken whole.
 * IT HAS A REQUEST IN FLIGHT when a control inside it is `disabled={...}` by a BUSY flag: an identifier named for waiting
 * a WRITE (busy, saving, submitting, sending, deleting, working, inFlight, posting, issuing, recording, creating, uploading, actionLoading,
 * actionBusy, or ending in one of them). A `loading` flag is a READ and is left out on purpose: a dialog must not trap the person while it reads.
 * ITS DISMISSERS are a button whose visible text is Cancel or Close, one whose aria-label or title says Close, one whose only content is the
 * `<X>` icon or a × (as text, `&times;` or a span holding it), and one whose click is the overlay's `onClose` whatever it says; for a `<Modal>` or `<Drawer>`, also its `onClose` (Escape, a click on the backdrop and the header's X all reach it), and for a hand-built
 * overlay, an `onClick` on the overlay element itself (its backdrop).
 * A DISMISSER IS HELD when its `disabled` (for a Modal's onClose and a backdrop: the handler itself) names a busy flag, and a hand-built
 * backdrop also STOPS its click always (the overlay may be drawn inside another one's click-to-close backdrop, a dialog over a ledger, and a
 * click left to bubble closes that one and unmounts this over its write). A write flag set before an await (or a state flag a derived one is
 * made of) is put back in a `finally`, or a throw leaves every way out held. What it cannot see:
 * an Escape handler a hand-built overlay installs in an effect elsewhere in the file, a busy flag under another name, and a dismisser drawn
 * by a component of another file.
 */
import ts from "typescript";

const WRITE_WORDS = "busy|saving|submitting|sending|deleting|working|posting|issuing|recording|creating|uploading|importing|deactivating|reactivating|archiving|restoring|approving|cancelling|applying|emailing|reversing|revoking|inviting|retracting|purging";
/** A write flag: one of the words, alone, as the start of a name (`savingOverride`, `busyId`) or as its end (`fdSaving`, `rowBusy`), and the
 *  page-wide names `inFlight`, `actionLoading`, `actionBusy` and `actionInFlight`. */
const BUSY = new RegExp(`^(${WRITE_WORDS})([A-Z]\\w*)?$|^(inFlight|actionLoading|actionBusy|actionInFlight)$|(Busy|Saving|Submitting|Sending|Deleting|Working|InFlight|Posting|Issuing|Recording|Creating|Importing)$`);

/** The shared overlays (components/ui/modal.tsx, components/ui/drawer.tsx): Escape, the backdrop and the header's X all call their `onClose`. */
const SHARED = /^(Modal|Drawer)$/;

export interface Loose { file: string; line: number; overlay: string; what: string; flag: string | null; edit: { start: number; end: number; text: string } | null }

function namesBusy(node: ts.Node | undefined): boolean {
  if (!node) return false;
  let hit = false;
  const visit = (n: ts.Node) => {
    if (hit) return;
    if (ts.isIdentifier(n) && BUSY.test(n.text)) hit = true;
    else if (ts.isPropertyAccessExpression(n) && BUSY.test(n.name.text)) hit = true;
    else ts.forEachChild(n, visit);
  };
  visit(node);
  return hit;
}

const attrsOf = (el: ts.JsxElement | ts.JsxSelfClosingElement) => (ts.isJsxElement(el) ? el.openingElement : el).attributes.properties;
const tagOf = (el: ts.JsxElement | ts.JsxSelfClosingElement) => (ts.isJsxElement(el) ? el.openingElement : el).tagName.getText();
function attr(el: ts.JsxElement | ts.JsxSelfClosingElement, name: string): ts.JsxAttribute | undefined {
  return attrsOf(el).find((a): a is ts.JsxAttribute => ts.isJsxAttribute(a) && a.name.getText() === name);
}
function attrExpr(a: ts.JsxAttribute | undefined): ts.Node | undefined {
  if (!a || !a.initializer) return undefined;
  return ts.isJsxExpression(a.initializer) ? a.initializer.expression : a.initializer;
}
function literal(a: ts.JsxAttribute | undefined): string {
  const e = attrExpr(a);
  if (!e) return "";
  if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) return e.text;
  if (ts.isTemplateExpression(e)) return e.getText();
  return "";
}
function textOf(el: ts.JsxElement): string {
  return el.children.map((c) => (ts.isJsxText(c) ? c.text : "")).join("").replace(/\s+/g, " ").trim();
}

function elementsIn(root: ts.Node): (ts.JsxElement | ts.JsxSelfClosingElement)[] {
  const out: (ts.JsxElement | ts.JsxSelfClosingElement)[] = [];
  const visit = (n: ts.Node) => { if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) out.push(n); ts.forEachChild(n, visit); };
  ts.forEachChild(root, visit);
  return out;
}

function dismisserLabel(el: ts.JsxElement | ts.JsxSelfClosingElement): string | null {
  if (!/^(button|Button)$/.test(tagOf(el))) return null;
  const label = `${literal(attr(el, "aria-label"))} ${literal(attr(el, "title"))}`;
  if (/\bClose\b/.test(label)) return "Close (named)";
  // A button whose click is the overlay's own close handler is a way out whatever it says.
  const closes = attrExpr(attr(el, "onClick"))?.getText() === "onClose" ? "onClose button" : null;
  if (!ts.isJsxElement(el)) return closes;
  const text = textOf(el);
  if (/^(Cancel|Close)$/.test(text)) return text;
  if (/^(×|&times;)$/.test(text)) return "×";
  const kids = el.children.filter((c) => !(ts.isJsxText(c) && !c.text.trim()));
  if (kids.length === 1 && (ts.isJsxSelfClosingElement(kids[0]) || ts.isJsxElement(kids[0])) && /^X$/.test(tagOf(kids[0] as ts.JsxSelfClosingElement))) return "X";
  if (kids.length === 1 && ts.isJsxElement(kids[0]) && /^(×|&times;)$/.test(textOf(kids[0]))) return "×";
  return closes;
}

/** How many overlays in one file draw a request in flight (the vacuity floor of the guard: a scan that found none would pass everything). */
export function overlaysInFlight(file: string, source: string): number {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let n = 0;
  const visit = (node: ts.Node) => {
    if ((ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) && (SHARED.test(tagOf(node)) || /\bfixed inset-0\b/.test(literal(attr(node, "className"))))) {
      if (elementsIn(node).some((el) => /^(button|Button)$/.test(tagOf(el)) && !dismisserLabel(el) && namesBusy(attrExpr(attr(el, "disabled"))))) n += 1;
      if (!SHARED.test(tagOf(node))) return;
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return n;
}

/** Every dismisser left live over a request in flight, in one file. */
export function looseDismissers(file: string, source: string): Loose[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: Loose[] = [];
  const overlays: (ts.JsxElement | ts.JsxSelfClosingElement)[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) {
      if (SHARED.test(tagOf(n)) || /\bfixed inset-0\b/.test(literal(attr(n, "className")))) {
        overlays.push(n);
        if (!SHARED.test(tagOf(n))) return; // a hand-built overlay is taken whole (its backdrop child is part of it)
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  const lineOf = (n: ts.Node) => sf.getLineAndCharacterOfPosition(n.getStart()).line + 1;
  for (const ov of overlays) {
    const inside = elementsIn(ov);
    const writers = inside.filter((el) => /^(button|Button)$/.test(tagOf(el)) && !dismisserLabel(el) && namesBusy(attrExpr(attr(el, "disabled"))));
    if (!writers.length) continue;
    const flag = busyIdentifier(attrExpr(attr(writers[0], "disabled")));
    const shared = SHARED.test(tagOf(ov));
    const name = shared ? tagOf(ov) : "overlay";
    const wrapHandler = (a: ts.JsxAttribute, how: "call" | "drop") => {
      const e = attrExpr(a)!;
      const text = how === "call" ? `() => { if (!${flag}) (${e.getText()})(); }` : `${flag} ? undefined : (${e.getText()})`;
      return flag ? { start: e.getStart(), end: e.getEnd(), text } : null;
    };
    const holdButton = (el: ts.JsxElement | ts.JsxSelfClosingElement) => {
      if (!flag) return null;
      const d = attr(el, "disabled");
      if (!d) { const tag = (ts.isJsxElement(el) ? el.openingElement : el).tagName; return { start: tag.getEnd(), end: tag.getEnd(), text: ` disabled={${flag}}` }; }
      const e = attrExpr(d);
      return e ? { start: e.getStart(), end: e.getEnd(), text: `(${e.getText()}) || ${flag}` } : null;
    };
    if (shared && !namesBusy(attrExpr(attr(ov, "onClose"))) && !attr(ov, "busy")) {
      const a = attr(ov, "onClose");
      out.push({ file, line: lineOf(ov), overlay: name, what: "onClose (Escape, backdrop, X)", flag, edit: a ? wrapHandler(a, "call") : null });
    }
    const backdrops = shared ? [] : [ov, ...inside].filter((el) => attr(el, "onClick") && (el === ov || /\babsolute inset-0\b/.test(literal(attr(el, "className")))));
    for (const el of backdrops) {
      const handler = attrExpr(attr(el, "onClick"));
      if (!namesBusy(handler)) out.push({ file, line: lineOf(el), overlay: name, what: "backdrop click", flag, edit: wrapHandler(attr(el, "onClick")!, "drop") });
      // An overlay may be drawn inside another one's click-to-close backdrop (a dialog over a ledger), so a click its backdrop does not act on
      // must still stop there: left to bubble, it closes the overlay behind and unmounts this one over its write.
      else if (!/\bstopPropagation\(\)/.test(handler?.getText() ?? "")) out.push({ file, line: lineOf(el), overlay: name, what: "backdrop click reaches the overlay behind", flag, edit: null });
    }
    // A write flag set before an await is put back in a finally: an answer that throws (the 45-second bound, a dropped connection) would
    // otherwise leave every way out held until the page is reloaded.
    for (const state of flag ? stateFlagsOf(sf, flag) : []) {
      const setter = `set${state[0].toUpperCase()}${state.slice(1)}`;
      for (const fn of functionsSetting(sf, setter)) {
        if (!fn.getText().includes("await ")) continue;
        const resets = finallyBlocks(fn).some((b) => new RegExp(`\\b${setter}\\((false|null)\\)`).test(b.getText()));
        if (!resets) out.push({ file, line: lineOf(fn), overlay: name, what: `${setter}(true) before an await with no ${setter}(false) in a finally`, flag, edit: null });
      }
    }
    for (const el of inside) {
      const label = dismisserLabel(el);
      if (label && !namesBusy(attrExpr(attr(el, "disabled")))) out.push({ file, line: lineOf(el), overlay: name, what: label, flag, edit: holdButton(el) });
    }
  }
  return out;
}

/** The state flags a flag stands for: itself, and where it is a derived `const flag = a || b || ...`, each write flag it is made of (once). */
function stateFlagsOf(sf: ts.SourceFile, flag: string): string[] {
  const out = new Set<string>([flag]);
  const visit = (n: ts.Node) => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === flag && n.initializer && !ts.isCallExpression(n.initializer)) {
      const walk = (m: ts.Node) => { if (ts.isIdentifier(m) && BUSY.test(m.text)) out.add(m.text); ts.forEachChild(m, walk); };
      walk(n.initializer);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return [...out];
}

/** Every function in the file that sets `setter(true)`. */
function functionsSetting(sf: ts.SourceFile, setter: string): ts.FunctionLikeDeclaration[] {
  const out: ts.FunctionLikeDeclaration[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isCallExpression(n) && n.expression.getText() === setter && n.arguments[0]?.kind === ts.SyntaxKind.TrueKeyword) {
      let f: ts.Node | undefined = n.parent;
      while (f && !ts.isFunctionLike(f)) f = f.parent;
      if (f && !out.includes(f as ts.FunctionLikeDeclaration)) out.push(f as ts.FunctionLikeDeclaration);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

function finallyBlocks(fn: ts.Node): ts.Block[] {
  const out: ts.Block[] = [];
  const visit = (n: ts.Node) => { if (ts.isTryStatement(n) && n.finallyBlock) out.push(n.finallyBlock); ts.forEachChild(n, visit); };
  visit(fn);
  return out;
}

/** The busy flag a write button is held by, when it is a plain name in scope (a property of a map's row is not: it is reported, not used). */
function busyIdentifier(node: ts.Node | undefined): string | null {
  let found: string | null = null;
  const visit = (n: ts.Node) => {
    if (found) return;
    if (ts.isPropertyAccessExpression(n)) { if (BUSY.test(n.name.text)) found = "\u0000"; return; }
    if (ts.isIdentifier(n) && BUSY.test(n.text)) { found = n.text; return; }
    ts.forEachChild(n, visit);
  };
  if (node) visit(node);
  return found === "\u0000" ? null : found;
}
