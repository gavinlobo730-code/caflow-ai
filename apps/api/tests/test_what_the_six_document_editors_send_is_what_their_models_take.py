"""A key one of the six document editors sends must be a field of the model that takes it (POST-A-399).

THE DEFECT THIS HOLDS. A pydantic model ignores a key it has no field for. The new purchase debit note and purchase credit note screens sent the note typed in their Notes box and the
copy of the supplier's document the person had attached, and neither create model had a field for them, so both were dropped on the way in, the row came back with NULL, and the screen said
"saved as draft". The sales pair had the same defect for the note. Nothing noticed: the web guard held that the screen SENDS the key, and the API tests held what the routes do with the keys the
models take; no test held that the two agree. An independent read of the first version of this change found the purchase pair, which the change's own tests had passed over.

THE RULE. Read the request the editor makes, from the editor's source, and require every key of its body to be a field of the model that takes it:
  * the create (`apiCall(<create url>, "POST", {...})`): `SalesInvoiceIn`, `PurchaseBillIn`, `CreditNoteIn`, `SalesDebitNoteIn`, `DebitNoteIn`, `PurchaseCreditNoteIn`;
  * the edit (`apiCall(<edit url>, "PATCH", {...})`, or the object(s) a `patchPayload` is built from): the matching `...UpdateIn`.
A spread (`...shippingBillSent`) hides its keys from a reader of the source, so each one is resolved from `_SPREADS`, and a spread that is not there fails the test until somebody says which
keys it carries.

WHAT THIS DOES NOT SEE. A key built some way other than an object literal passed to `apiCall` in these six files; a request another screen makes to the same route; a field the model takes
and the route then ignores (the routes' own tests hold that). The six editors are named: a seventh with the same shape is not found by it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
from models.invoices import PurchaseBillIn, PurchaseBillUpdateIn, SalesInvoiceIn, SalesInvoiceUpdateIn

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

#: (editor, the create's url as it is written, the model that takes it, the edit's url as it is written, the model that takes that)
EDITORS = [
    ("components/invoices/InvoiceEditor.tsx", '"/api/sales-invoices/"', SalesInvoiceIn, "`/api/sales-invoices/${patchId}`", SalesInvoiceUpdateIn),
    ("components/purchases/PurchaseBillEditor.tsx", '"/api/purchase-bills/"', PurchaseBillIn, "`/api/purchase-bills/${existing.id}`", PurchaseBillUpdateIn),
    ("components/sales/SalesCreditNoteEditor.tsx", '"/api/credit-notes/"', cn.CreditNoteIn, "`/api/credit-notes/${existing.id}`", cn.CreditNoteUpdateIn),
    ("components/sales/SalesDebitNoteEditor.tsx", '"/api/sales-debit-notes/"', sdn.SalesDebitNoteIn, "`/api/sales-debit-notes/${existing.id}`", sdn.SalesDebitNoteUpdateIn),
    ("components/purchases/DebitNoteEditor.tsx", '"/api/debit-notes/"', dn.DebitNoteIn, "`/api/debit-notes/${existing.id}`", dn.DebitNoteUpdateIn),
    ("components/purchases/PurchaseCreditNoteEditor.tsx", '"/api/purchase-credit-notes/"', pcn.PurchaseCreditNoteIn, "`/api/purchase-credit-notes/${existing.id}`", pcn.PurchaseCreditNoteUpdateIn),
]

#: What each spread in those requests carries (a reader of the source cannot see inside a function call or a variable). Each name is the first identifier of the spread.
_SPREADS = {
    "shippingBillSent": {"shipping_bill_no", "shipping_bill_date", "port_code"},          # InvoiceEditor: the three keys of the shipping bill block, sent only while it is drawn
    "docDiscountPayload": {"discount_percent_bps", "discount_paise"},                        # InvoiceEditor: one of the two, never both
    "toClassificationPayload": {"supply_type", "invoice_type", "is_reverse_charge"},         # lib/invoices/gst.ts
}


# ── a small reader of the source: enough of TypeScript to find a call's arguments and an object literal's keys ────────────────

def _strip_comments(src: str) -> str:
    out, i, quote = [], 0, None
    while i < len(src):
        c, n = src[i], src[i + 1] if i + 1 < len(src) else ""
        if quote:
            out.append(c)
            if c == "\\":
                out.append(n)
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c == "/" and n == "/":
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if c == "/" and n == "*":
            i += 2
            while i < len(src) and not (src[i] == "*" and src[i + 1:i + 2] == "/"):
                i += 1
            i += 2
            continue
        if c in "\"'`":
            quote = c
        out.append(c)
        i += 1
    return "".join(out)


_PAIRS = {"(": ")", "{": "}", "[": "]"}


def _skip_quoted(src: str, i: int) -> int:
    q = src[i]
    i += 1
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if q == "`" and c == "$" and src[i + 1:i + 2] == "{":
            i = _skip_balanced(src, i + 1) + 1
            continue
        if c == q:
            return i + 1
        i += 1
    raise ValueError("an unterminated string")


def _skip_balanced(src: str, i: int) -> int:
    """src[i] opens a bracket; the index of the one that closes it."""
    stack = [_PAIRS[src[i]]]
    i += 1
    while i < len(src):
        c = src[i]
        if c in "\"'`":
            i = _skip_quoted(src, i)
            continue
        if c in _PAIRS:
            stack.append(_PAIRS[c])
        elif c in ")}]":
            if c != stack.pop():
                raise ValueError("mismatched brackets")
            if not stack:
                return i
        i += 1
    raise ValueError("an unterminated bracket")


def _split_top_level(body: str) -> list[str]:
    """The comma-separated parts of a bracket's inside, ignoring commas in nested brackets and strings."""
    parts, start, i = [], 0, 0
    while i < len(body):
        c = body[i]
        if c in "\"'`":
            i = _skip_quoted(body, i)
            continue
        if c in _PAIRS:
            i = _skip_balanced(body, i) + 1
            continue
        if c == ",":
            parts.append(body[start:i])
            start = i + 1
        i += 1
    parts.append(body[start:])
    return [p.strip() for p in parts if p.strip()]


def _keys_of(literal: str) -> tuple[set[str], list[str]]:
    """(the keys an object literal names, the spreads in it by their first identifier). `literal` is `{ ... }`."""
    keys, spreads = set(), []
    for entry in _split_top_level(literal[1:-1]):
        if entry.startswith("..."):
            m = re.match(r"\.\.\.\s*([A-Za-z_]\w*)", entry)
            spreads.append(m.group(1) if m else entry)
            continue
        m = re.match(r"""(?:"([^"]+)"|'([^']+)'|([A-Za-z_]\w*))\s*(?::|$)""", entry)
        if m:
            keys.add(m.group(1) or m.group(2) or m.group(3))
    return keys, spreads


def _object_literals(expr: str) -> list[str]:
    """The `{...}` literals at the top level of an expression such as `isLocked ? { a } : { b }`."""
    out, i = [], 0
    while i < len(expr):
        c = expr[i]
        if c in "\"'`":
            i = _skip_quoted(expr, i)
            continue
        if c == "{":
            end = _skip_balanced(expr, i)
            out.append(expr[i:end + 1])
            i = end + 1
            continue
        if c in "([":
            i = _skip_balanced(expr, i) + 1
            continue
        i += 1
    return out


def _calls(src: str):
    """Every `apiCall(...)` as (url text, method text, body text or None)."""
    for m in re.finditer(r"\bapiCall\(", src):
        start = m.end() - 1
        end = _skip_balanced(src, start)
        args = _split_top_level(src[start + 1:end])
        if len(args) >= 2:
            yield args[0], args[1].strip("\"'`"), (args[2] if len(args) > 2 else None)


def _bodies(src: str, url: str, method: str) -> list[str]:
    """The object literals the editor sends to `url` with `method`."""
    found = []
    for u, m, body in _calls(src):
        if u != url or m != method or body is None:
            continue
        if body.startswith("{"):
            found.append(body)
        elif re.fullmatch(r"[A-Za-z_]\w*", body):
            init = re.search(rf"\bconst {body}\s*=\s*(.*?);\s*\n", src, re.S)
            assert init, f"the body {body} sent to {url} is not an object literal nor a const this reader can find"
            found.extend(_object_literals(init.group(1)))
        else:
            raise AssertionError(f"the body sent to {url} is neither an object literal nor a name: {body[:60]}")
    return found


def _sent_keys(src: str, url: str, method: str) -> set[str]:
    out: set[str] = set()
    for literal in _bodies(src, url, method):
        keys, spreads = _keys_of(literal)
        out |= keys
        for name in spreads:
            assert name in _SPREADS, f"a spread of `{name}` in the {method} to {url} carries keys this test cannot see: say which in _SPREADS"
            out |= _SPREADS[name]
    return out


# ── the rule ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("editor,create_url,create_model,edit_url,edit_model", EDITORS, ids=[e[0].rsplit("/", 1)[1] for e in EDITORS])
def test_every_key_an_editor_sends_is_a_field_of_the_model_that_takes_it(editor, create_url, create_model, edit_url, edit_model):
    src = _strip_comments((WEB / editor).read_text(encoding="utf-8"))
    for method, url, model in (("POST", create_url, create_model), ("PATCH", edit_url, edit_model)):
        keys = _sent_keys(src, url, method)
        assert keys, f"{editor}: no {method} to {url} was found, so nothing was checked"
        assert "lines" in keys or method == "PATCH", f"{editor}: the create to {url} reads without a lines key, so the reader has not read the request"
        dropped = sorted(keys - set(model.model_fields))
        assert not dropped, (f"{editor} sends {dropped} in its {method} to {url}, and {model.__name__} has no field for them: pydantic ignores a key it has no field for, "
                             "so the value never reaches the row and the screen still says it saved")


def test_the_reader_reads_what_it_is_meant_to():
    """The reader is tried on the shapes it must read, so a rule that read nothing could not pass."""
    src = _strip_comments('''
        const patchPayload = isLocked ? { notes: editedText(notes, existing.notes), document_url: documentUrl || undefined } : { a: 1, "b": 2, ...shippingBillSent, nested: { x: 1, y: [1, 2] }, c };
        const r = await apiCall("/api/x/", "POST", { client_id: clientId, // a comment, with a comma
          lines: [{ q: 1 }], note: `t ${a ? { b: 1 } : 2}`, ...toClassificationPayload({ supplyType }) }, token);
        await apiCall(`/api/x/${id}`, "PATCH", patchPayload, token);
        await apiCall("/api/x/issue", "POST", undefined, token);
    ''')
    assert _sent_keys(src, '"/api/x/"', "POST") == {"client_id", "lines", "note", "supply_type", "invoice_type", "is_reverse_charge"}
    assert _sent_keys(src, "`/api/x/${id}`", "PATCH") == {"notes", "document_url", "a", "b", "nested", "c", "shipping_bill_no", "shipping_bill_date", "port_code"}


def test_a_key_the_model_does_not_take_is_found():
    src = _strip_comments('apiCall("/api/x/", "POST", { client_id: c, notes: n }, token);')
    keys = _sent_keys(src, '"/api/x/"', "POST")
    assert sorted(keys - {"client_id", "lines"}) == ["notes"]


def test_every_spread_in_the_table_is_a_key_some_model_takes():
    fields = set()
    for _, _, create_model, _, edit_model in EDITORS:
        fields |= set(create_model.model_fields) | set(edit_model.model_fields)
    for name, keys in _SPREADS.items():
        assert keys <= fields, f"_SPREADS[{name!r}] names {sorted(keys - fields)}, which no create or update model of the six has"
