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

/** What the naming checks need to know about one source file: which labels point at which ids, and whether its `Field` can be trusted. */
interface FileFacts {
  sf: ts.SourceFile;
  fieldNames: boolean;
  labelFor: Set<string>;
  openings: Opening[];
}

function factsOf(source: string, fileName: string): FileFacts {
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
  return { sf, fieldNames, labelFor, openings };
}

/**
 * How an element is named, or null: one of `aria` (any of `ariaProps`), `inside label`, `inside Field`, `id+htmlFor`. The order is the order the
 * rule has always checked in; a spread is the caller's to judge, because what a spread means differs between a native control and a component.
 */
function namedBy(el: Opening, facts: FileFacts, ariaProps: readonly string[]): string | null {
  if (ariaProps.some((a) => attr(el, a))) return "aria";
  // The element itself is the opening's parent, or the self-closing node; walk up through its JSX ancestors for a label or a Field.
  const self: ts.Node = ts.isJsxOpeningElement(el) ? el.parent : el;
  for (let p: ts.Node | undefined = self.parent; p; p = p.parent) {
    if (ts.isJsxElement(p)) {
      const t = tagName(p.openingElement);
      if (t === "label") return "inside label";
      if (t === "Field" && facts.fieldNames) return "inside Field";
    }
  }
  const id = valueText(attr(el, "id"));
  if (id !== null && facts.labelFor.has(id)) return "id+htmlFor";
  return null;
}

const spreads = (el: Opening) => el.attributes.properties.some((p) => ts.isJsxSpreadAttribute(p));

export function findControls(source: string, fileName = "x.tsx"): Control[] {
  const facts = factsOf(source, fileName);
  const out: Control[] = [];
  for (const el of facts.openings) {
    const tag = tagName(el);
    if (!CONTROL_TAGS.has(tag)) continue;
    const line = facts.sf.getLineAndCharacterOfPosition(el.getStart()).line + 1;
    const key = keyOf(el);
    const type = valueText(attr(el, "type"));
    if (tag === "input" && type !== null && UNNAMED_TYPES.has(type)) { out.push({ tag, line, key, verdict: "named", via: `type=${type}` }); continue; }
    const via = namedBy(el, facts, ["aria-label", "aria-labelledby"]);
    if (via) { out.push({ tag, line, key, verdict: "named", via: via === "aria" ? "aria" : via }); continue; }
    if (spreads(el)) { out.push({ tag, line, key, verdict: "spread" }); continue; }
    out.push({ tag, line, key, verdict: "unnamed" });
  }
  return out;
}

// ── The second half of the rule: the shared components that render a control, judged where they are USED ─────────────────────────────────
//
// A native `<input>` is judged where it is written. `Input`, `DateInput`, `Combobox` and the entity lookups render one from inside, so the
// native rule reads their file and passes, and a screen that drops one in with a bare `<label>` beside it (no `htmlFor`, no `id`) got a field
// a screen reader announces as "edit text". The names below are the call sites the rule did not see. A component is the one meant only when
// the file IMPORTS it from the module that defines it (a local `Select` is nobody's), whatever it is called there.
//
// What names one: the prop that component takes for it (`aria-label` / `aria-labelledby` on the three that render a bare control and on
// `DateInput`, whose props are an input's; `ariaLabel` on `Combobox` and the lookups, which do not take the others), a `<label>` that wraps
// it, a `Field` that ties its label to its children, or an `id` a `<label htmlFor>` in the file points at. `YearPicker` and
// `ServiceCataloguePicker` are not here on purpose: each supplies a name of its own when the caller gives none.
//
// WHAT IT DOES NOT SEE: a component imported under a module path other than the one listed, a name passed through a spread (counted apart),
// and whether the name is a good one.
export interface SharedControl { module: RegExp; aria: readonly string[] }

const NATIVE_ARIA = ["aria-label", "aria-labelledby"] as const;
const PROP_ARIA = ["ariaLabel"] as const;
const lookup = (file: string): SharedControl => ({ module: new RegExp(`(^|/)lookups/${file}$`), aria: PROP_ARIA });

export const SHARED_CONTROLS: Readonly<Record<string, SharedControl>> = {
  Input: { module: /(^|\/)ui\/field$/, aria: NATIVE_ARIA },
  Textarea: { module: /(^|\/)ui\/field$/, aria: NATIVE_ARIA },
  Select: { module: /(^|\/)ui\/field$/, aria: NATIVE_ARIA },
  DateInput: { module: /(^|\/)ui\/date-input$/, aria: NATIVE_ARIA },
  Combobox: { module: /(^|\/)ui\/combobox$/, aria: PROP_ARIA },
  ClientLookup: lookup("ClientLookup"),
  CustomerLookup: lookup("CustomerLookup"),
  VendorLookup: lookup("VendorLookup"),
  StateLookup: lookup("StateLookup"),
  AccountLookup: lookup("AccountLookup"),
  HsnLookup: lookup("HsnLookup"),
  EntityLookup: lookup("EntityLookup"),
};

export interface SharedUse {
  /** The component, under its own name (an alias in the file is resolved back to it). */
  component: string;
  line: number;
  verdict: "named" | "spread" | "unnamed";
  via?: string;
}

/** The local names under which a file imports the shared components, mapped back to the component. */
function importedShared(sf: ts.SourceFile): Map<string, string> {
  const local = new Map<string, string>();
  sf.forEachChild((n) => {
    if (!ts.isImportDeclaration(n) || !ts.isStringLiteral(n.moduleSpecifier)) return;
    const named = n.importClause?.namedBindings;
    if (!named || !ts.isNamedImports(named)) return;
    for (const e of named.elements) {
      const original = e.propertyName?.text ?? e.name.text;
      const shared = SHARED_CONTROLS[original];
      if (shared && shared.module.test((n.moduleSpecifier as ts.StringLiteral).text)) local.set(e.name.text, original);
    }
  });
  return local;
}

export function findSharedUses(source: string, fileName = "x.tsx"): SharedUse[] {
  const facts = factsOf(source, fileName);
  const local = importedShared(facts.sf);
  if (local.size === 0) return [];
  const out: SharedUse[] = [];
  for (const el of facts.openings) {
    const component = local.get(tagName(el));
    if (!component) continue;
    const line = facts.sf.getLineAndCharacterOfPosition(el.getStart()).line + 1;
    const via = namedBy(el, facts, SHARED_CONTROLS[component].aria);
    if (via) out.push({ component, line, verdict: "named", via });
    else if (spreads(el)) out.push({ component, line, verdict: "spread" });
    else out.push({ component, line, verdict: "unnamed" });
  }
  return out;
}
