// Which native form controls in a TSX source have no programmatic name (POST-A-127). Found with the TypeScript parser, not a regex.
//
// A CONTROL is a JSX `<input>`, `<select>` or `<textarea>`. It HAS A NAME when any of these holds:
//   * it carries `aria-label` or `aria-labelledby`;
//   * a `<label>` is its ancestor in the JSX tree (an implicit label);
//   * it has an `id` and a `<label>` in the same file has an `htmlFor` with the same expression text (an explicit label), where the text is a
//     string literal's value or the source text of the expression, so `id={id}` pairs with `htmlFor={id}` and `id="x"` with `htmlFor="x"`;
//   * it is the child of a `Field` THAT TIES ITS LABEL TO ITS CHILDREN: the one imported from components/ui/field (which does it itself), or a
//     `Field` declared in the same file whose body puts `{children}` inside a `<label>`. A file's own `Field` that draws a SIBLING label
//     (`<label>{label}</label>{children}`, no `htmlFor`) names nothing, and a name is never taken from a component this file neither
//     imports from ui/field nor declares;
//   * it is a `type="hidden"`, `"submit"`, `"button"`, `"reset"` or `"image"` input, which is named by its value or has none.
//   * it spreads props (`{...props}`), because a wrapper that forwards them is named by whoever calls the wrapper. Counted separately, so
//     a spread is never mistaken for a named control and the number of them can be seen.
// A `placeholder` or a `title` is NOT a name here: a placeholder vanishes as soon as the field has a value, which is the moment a reader
// returns to it.
//
// WHAT IT DOES NOT SEE: a control inside a component that is not a JSX element in this file (a primitive that renders an `<input>` is
// judged in its own file), a label whose `htmlFor` is computed away from the expression it was written as, and a `<label>` in another
// file than the control.
import { createHash } from "node:crypto";
import ts from "typescript";

const CONTROL_TAGS = new Set(["input", "select", "textarea"]);
const UNNAMED_TYPES = new Set(["hidden", "submit", "button", "reset", "image"]);

export interface Control {
  tag: string;
  line: number;
  verdict: "named" | "spread" | "unnamed";
  via?: string;
  /** What the baseline records for an unnamed control: its tag and what it is bound to, so a fix and a new control in one file cannot net out. */
  key: string;
}

type Opening = ts.JsxOpeningElement | ts.JsxSelfClosingElement;

const tagName = (el: Opening) => el.tagName.getText();
const collapse = (t: string) => t.replace(/\s+/g, " ").trim();

function attrs(el: Opening): ts.JsxAttribute[] {
  return el.attributes.properties.filter((p): p is ts.JsxAttribute => ts.isJsxAttribute(p));
}

function attr(el: Opening, name: string): ts.JsxAttribute | undefined {
  return attrs(el).find((a) => a.name.getText() === name);
}

/** The text a value is compared by: a string literal's value, or the expression's source text; null when the attribute has no value. */
function valueText(a: ts.JsxAttribute | undefined): string | null {
  if (!a || !a.initializer) return null;
  const init = a.initializer;
  if (ts.isStringLiteral(init)) return init.text;
  if (ts.isJsxExpression(init) && init.expression) {
    const e = init.expression;
    if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) return e.text;
    return e.getText();
  }
  return null;
}

const FIELD_MODULE = /(^|\/)ui\/field$/;

/** Whether a `Field` in this file can be trusted to name its children: imported from ui/field, or declared here with `{children}` inside a `<label>`. */
function fieldNamesItsChildren(sf: ts.SourceFile): boolean {
  let trusted = false;
  const childrenInsideLabel = (body: ts.Node): boolean => {
    let found = false;
    const walk = (n: ts.Node, inLabel: boolean) => {
      if (ts.isJsxElement(n) && tagName(n.openingElement) === "label") inLabel = true;
      if (inLabel && ts.isJsxExpression(n) && n.expression && n.expression.getText() === "children") found = true;
      ts.forEachChild(n, (c) => walk(c, inLabel));
    };
    walk(body, false);
    return found;
  };
  const visit = (n: ts.Node) => {
    if (ts.isImportDeclaration(n) && ts.isStringLiteral(n.moduleSpecifier) && FIELD_MODULE.test(n.moduleSpecifier.text)) {
      const named = n.importClause?.namedBindings;
      if (named && ts.isNamedImports(named) && named.elements.some((e) => e.name.text === "Field" && (e.propertyName?.text ?? "Field") === "Field")) trusted = true;
    }
    if (ts.isFunctionDeclaration(n) && n.name?.text === "Field" && n.body) { if (childrenInsideLabel(n.body)) trusted = true; }
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === "Field" && n.initializer) {
      if (childrenInsideLabel(n.initializer)) trusted = true;
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return trusted;
}

/**
 * A control's identity for the baseline: its tag and the expression it is bound to (`value`, `checked` or `defaultValue`), which survives a
 * change of class or layout and tells two controls of one file apart; a control bound to nothing falls back to a short hash of its own text.
 */
function keyOf(el: Opening): string {
  const bound = valueText(attr(el, "value")) ?? valueText(attr(el, "checked")) ?? valueText(attr(el, "defaultValue"));
  if (bound !== null) return `${tagName(el)}:${collapse(bound)}`.slice(0, 140);
  return `${tagName(el)}#${createHash("sha1").update(collapse(el.getText())).digest("hex").slice(0, 8)}`;
}

export function findControls(source: string, fileName = "x.tsx"): Control[] {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const fieldNames = fieldNamesItsChildren(sf);
  const labelFor = new Set<string>();
  const openings: Opening[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) {
      openings.push(n);
      if (tagName(n) === "label") {
        const v = valueText(attr(n, "htmlFor"));
        if (v !== null) labelFor.add(v);
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);

  const out: Control[] = [];
  for (const el of openings) {
    const tag = tagName(el);
    if (!CONTROL_TAGS.has(tag)) continue;
    const line = sf.getLineAndCharacterOfPosition(el.getStart()).line + 1;
    const key = keyOf(el);
    const type = valueText(attr(el, "type"));
    if (tag === "input" && type !== null && UNNAMED_TYPES.has(type)) { out.push({ tag, line, key, verdict: "named", via: `type=${type}` }); continue; }
    if (attr(el, "aria-label") || attr(el, "aria-labelledby")) { out.push({ tag, line, key, verdict: "named", via: "aria" }); continue; }
    // The element itself is the opening's parent, or the self-closing node; walk up through its JSX ancestors for a label or a Field.
    const self: ts.Node = ts.isJsxOpeningElement(el) ? el.parent : el;
    let inside: string | null = null;
    for (let p: ts.Node | undefined = self.parent; p; p = p.parent) {
      if (ts.isJsxElement(p)) {
        const t = tagName(p.openingElement);
        if (t === "label") { inside = "label"; break; }
        if (t === "Field" && fieldNames) { inside = "Field"; break; }
      }
    }
    if (inside) { out.push({ tag, line, key, verdict: "named", via: `inside ${inside}` }); continue; }
    const id = valueText(attr(el, "id"));
    if (id !== null && labelFor.has(id)) { out.push({ tag, line, key, verdict: "named", via: "id+htmlFor" }); continue; }
    if (el.attributes.properties.some((p) => ts.isJsxSpreadAttribute(p))) { out.push({ tag, line, key, verdict: "spread" }); continue; }
    out.push({ tag, line, key, verdict: "unnamed" });
  }
  return out;
}
