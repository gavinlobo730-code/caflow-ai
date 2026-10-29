"""Every screen that issues or receives a document the server moves stock for reads the answer the server gives (POST-A-092).

The four routes (`/api/sales-invoices/{id}/issue`, `/api/purchase-bills/{id}/receive`, `/api/credit-notes/{id}/issue`,
`/api/debit-notes/{id}/issue`) put `stock_effect` on the response when a document's stock effect was not all recorded
(`domain/inventory/stock_effect`). A response field nobody reads is the failure this item exists to end, so this finds the
routes from the routers themselves (the function that calls `stock_effects.attach`, its decorator and its router prefix) and
every place under `apps/web/app`, `apps/web/components` and `apps/web/lib` that posts to one, and requires the call to be
followed by a read of the response through `lib/documents/stockEffect`. A fifth route that learns to attach the answer is in
the rule from the day it does, and a screen that issues one without reading it is a red test and not a silent screen.

It reads `apps/web/app/`, `apps/web/components/` and `apps/web/lib/`, so the `browser contract` CI job selects it for a pull
request that touches only the web app.
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
ROUTERS = REPO / "apps" / "api" / "routers"

#: The reads of the response that count. Each takes the response's `data`.
READERS = ("stockEffectProblem(", "issuedMessage(", "stockEffectSummary(")
#: How far after the call the read may be. A bulk handler maps the call and reads the results a screenful later.
REACH = 3500


def _routes_that_attach_the_answer() -> list[tuple[str, str]]:
    """(router file, URL regex) for every route whose function calls `stock_effects.attach`."""
    found: list[tuple[str, str]] = []
    for path in sorted(ROUTERS.glob("*.py")):
        text = path.read_text()
        if "stock_effects.attach(" not in text:
            continue
        tree = ast.parse(text)
        prefix = ""
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "APIRouter":
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or "stock_effects.attach(" not in ast.get_source_segment(text, node):
                continue
            for deco in node.decorator_list:
                if (isinstance(deco, ast.Call) and getattr(deco.func, "attr", "") == "post" and deco.args
                        and isinstance(deco.args[0], ast.Constant)):
                    url = prefix + deco.args[0].value
                    found.append((path.name, re.escape(url).replace(r"\{", "{").replace(r"\}", "}")))
    return found


def _url_regex(escaped: str) -> re.Pattern:
    # `/api/credit-notes/{cn_id}/issue` -> the browser spells the id as `${expr}`
    # The trailing boundary keeps `/issue` from matching the front of `/issue-preflight`, which reads and writes nothing.
    return re.compile(re.sub(r"\{[a-z_]+\}", r"\\$\\{[^}]+\\}", escaped) + r"(?![\w-])")


def _web_sources() -> list[pathlib.Path]:
    out = []
    for root in ("app", "components", "lib"):
        for path in (WEB / root).rglob("*"):
            if path.suffix in (".ts", ".tsx") and "node_modules" not in path.parts and not path.name.endswith((".test.ts", ".test.tsx")):
                out.append(path)
    return sorted(out)


def test_the_rule_finds_the_four_routes_and_not_nothing():
    """A rule that finds no route passes for the wrong reason."""
    routes = _routes_that_attach_the_answer()
    assert sorted(f for f, _ in routes) == ["credit_notes.py", "debit_notes.py", "purchase_bills.py", "sales_invoices.py"], routes


def test_every_place_that_posts_to_one_of_them_reads_the_answer():
    patterns = [_url_regex(escaped) for _file, escaped in _routes_that_attach_the_answer()]
    sites = 0
    unread = []
    for path in _web_sources():
        text = path.read_text()
        starts = sorted(m.start() for pattern in patterns for m in pattern.finditer(text))
        for n, start in enumerate(starts):
            sites += 1
            # The read has to come before the NEXT call site: a single issue handler sitting above a bulk one must not be
            # excused by the bulk handler's read.
            end = min(start + REACH, starts[n + 1] if n + 1 < len(starts) else len(text))
            if not any(reader in text[start:end] for reader in READERS):
                unread.append(f"{path.relative_to(REPO)}:{text.count(chr(10), 0, start) + 1}")
    assert sites >= 9, f"found only {sites} call sites: the rule has stopped seeing the screens"
    assert not unread, ("these call a route that reports whether stock was recorded and never read what it said: "
                        + ", ".join(unread))


def test_the_typed_client_defines_no_member_that_posts_to_them():
    """`api.salesInvoices.issue` was a typed spelling of the first route with no caller. A member that posts to one of these
    routes would be a second way in that the call-site rule above cannot follow to its callers, so the client defines none and
    every screen goes through a call the rule can see."""
    text = (WEB / "lib" / "api" / "index.ts").read_text()
    for _file, escaped in _routes_that_attach_the_answer():
        assert not _url_regex(escaped).search(text), f"lib/api/index.ts defines a member that posts to {escaped}"


def test_the_browser_decides_nothing_about_stock_beyond_the_servers_sentence():
    """The reader words the one case the server cannot speak for (a field it cannot read) and nothing else: no journal, no cost
    account, no Inventory in a sentence of its own."""
    text = re.sub(r"/\*.*?\*/", "", (WEB / "lib" / "documents" / "stockEffect.ts").read_text(), flags=re.S)
    text = re.sub(r"(?m)^\s*//[^\n]*$", "", text)
    assert text.count("could not be confirmed") == 1
    for word in ("journal", "Cost of Goods", "Inventory", "general ledger", "goods line"):
        assert word not in text, f"lib/documents/stockEffect words the failure itself ({word}): the sentence is the server's"
