"""A client's outstanding document requests lower its health score, because the filter is spelled the way the table allows (POST-A-341).

`document_requests.status` is `'pending'` or `'fulfilled'` (migration 024's CHECK). The engine's document-health read and its
stale-request read filtered on `"Pending"`, which no row can hold, so neither deduction has ever fired for any client: a client with five
requests the client never answered scored a full 100 on both. The two reads that EXPLAIN the score further down the same file were
corrected earlier and say so; these two were missed, and nothing drove a request through the score.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import timedelta

import routers.health as health
from core.ist_clock import ist_today
from tests._schema_checked_db import SchemaCheckedDB

FIRM, CLIENT = "firm-1", "client-1"


def _request(status: str, days_old: int, ident: str) -> dict:
    created = (ist_today() - timedelta(days=days_old)).isoformat()
    return {"id": ident, "firm_id": FIRM, "client_id": CLIENT, "title": f"Request {ident}", "status": status, "created_at": created}


def test_each_outstanding_request_costs_fifteen_points_of_document_health():
    db = SchemaCheckedDB({"document_requests": [_request("pending", 1, "a"), _request("pending", 2, "b")]})
    assert health._dim_document_health_db(db, CLIENT, FIRM) == 70


def test_a_fulfilled_request_costs_nothing():
    db = SchemaCheckedDB({"document_requests": [_request("fulfilled", 30, "a"), _request("pending", 1, "b")]})
    assert health._dim_document_health_db(db, CLIENT, FIRM) == 85


def test_a_client_with_no_requests_keeps_full_document_health():
    assert health._dim_document_health_db(SchemaCheckedDB({"document_requests": []}), CLIENT, FIRM) == 100


def test_another_clients_request_is_not_counted():
    other = {**_request("pending", 1, "x"), "client_id": "client-2"}
    assert health._dim_document_health_db(SchemaCheckedDB({"document_requests": [other]}), CLIENT, FIRM) == 100


def test_a_request_older_than_a_week_costs_ten_points_of_responsiveness_and_a_recent_one_costs_none():
    """A portal session in the last fortnight is seeded so the only deduction left is the stale-request one."""
    session = {"id": "s", "firm_id": FIRM, "client_id": CLIENT, "created_at": ist_today().isoformat()}
    db = SchemaCheckedDB({
        "client_portal_sessions": [session],
        "document_requests": [_request("pending", 20, "old"), _request("pending", 9, "older"), _request("pending", 3, "recent"),
                              _request("fulfilled", 40, "done")],
    })
    assert health._dim_client_responsiveness_db(db, CLIENT, FIRM) == 80


def test_no_read_of_the_document_requests_table_filters_on_a_status_the_check_cannot_hold():
    """The rule, not the two sites: every `.eq("status", <literal>)` on a chain that starts at `document_requests`, anywhere in the
    server, uses a spelling the table's CHECK permits."""
    root = pathlib.Path(__file__).resolve().parents[1]
    allowed = {"pending", "fulfilled"}
    seen = 0
    for folder in ("routers", "services", "domain", "jobs", "repositories"):
        for path in (root / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "eq"
                        and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant) and node.args[0].value == "status"):
                    continue
                chain, probe = [], node.func.value
                while isinstance(probe, (ast.Call, ast.Attribute)):
                    if isinstance(probe, ast.Call) and isinstance(probe.func, ast.Attribute) and probe.func.attr == "table" and probe.args:
                        chain.append(getattr(probe.args[0], "value", None))
                    probe = probe.func.value if isinstance(probe, ast.Call) and isinstance(probe.func, ast.Attribute) else getattr(probe, "value", None)
                    if probe is None:
                        break
                if "document_requests" in chain and isinstance(node.args[1], ast.Constant):
                    seen += 1
                    assert node.args[1].value in allowed, f"{path.relative_to(root)}:{node.lineno} filters document_requests.status on {node.args[1].value!r}"
    assert seen >= 4, "the scan found fewer status filters than the four known ones: the rule reads nothing"
