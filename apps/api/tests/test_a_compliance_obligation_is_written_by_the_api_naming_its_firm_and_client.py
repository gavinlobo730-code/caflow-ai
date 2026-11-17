"""A compliance obligation is written by the API's privileged client, and every write names the firm and the client (POST-A-461).

THE PREMISE
    `compliance_records` took a signed-in write from any member whose role tier the row policy admits (migration 489), and the repository wrote
    through the caller's own client, so an assigned Executive could PATCH `status` over PostgREST to 'Not Required' (no reason, no
    `compliance.approve`, no audit row, and the obligation left every overdue count) or to 'Filed' (no `filings` row, so no period lock). A trigger
    keyed on the caller could not tell that write from the API door's while the door wrote as the caller. So the writers move first (this change),
    and migration 705 takes the signed-in write away after them.

THE RULE
    Every write the repository makes is on the privileged client, which has no row security, so each update and soft delete names `firm_id` AND
    `client_id` in its statement, an insert carries both, and a write against the database without them is refused before it is sent. Every
    runtime caller of a write method names the client. The browser only reads the table.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from repositories import compliance_records_repository as crr

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
WRITE_METHODS = {"update", "update_clearing", "stamp_closing_tds_challans", "soft_delete"}


class _Chain:
    def __init__(self, log):
        self.log = log

    def __getattr__(self, name):
        def call(*a, **k):
            self.log.append((name, a, k))
            return self
        return call

    def execute(self):
        self.log.append(("execute", (), {}))

        class R:
            data = [{"id": "r1"}]
        return R()


@pytest.fixture
def live(monkeypatch):
    log: list = []
    monkeypatch.setattr(crr, "_USE_MOCK", False)
    monkeypatch.setattr(crr, "_writer", lambda: _Chain(log))
    monkeypatch.setattr(crr, "_get_db", lambda: (_ for _ in ()).throw(AssertionError("a write used the caller's own client")))
    return log


def _eqs(log):
    return {(a[0], a[1]) for name, a, _k in log if name == "eq"}


def test_an_update_names_the_firm_and_the_client_on_the_privileged_client(live):
    crr.compliance_records_repo.update("r1", {"status": "Filed"}, firm_id="F1", client_id="C1")
    assert {("id", "r1"), ("firm_id", "F1"), ("client_id", "C1")} <= _eqs(live)


def test_a_clearing_update_a_stamp_and_a_soft_delete_name_both(live):
    crr.compliance_records_repo.update_clearing("r1", "F1", {"status": "Reopened"}, clear=("filed_date",), client_id="C1")
    crr.compliance_records_repo.stamp_closing_tds_challans("r1", "F1", ["c1"], client_id="C1")
    crr.compliance_records_repo.soft_delete("r1", firm_id="F1", client_id="C1")
    updates = [i for i, (name, *_r) in enumerate(live) if name == "update"]
    assert len(updates) == 3
    assert ("firm_id", "F1") in _eqs(live) and ("client_id", "C1") in _eqs(live)


@pytest.mark.parametrize("call", [
    lambda r: r.update("r1", {"status": "Filed"}, firm_id="F1"),
    lambda r: r.update("r1", {"status": "Filed"}, client_id="C1"),
    lambda r: r.update_clearing("r1", "F1", {}, clear=()),
    lambda r: r.stamp_closing_tds_challans("r1", "F1", ["c"]),
    lambda r: r.soft_delete("r1", firm_id="F1"),
    lambda r: r.create({"firm_id": "F1", "status": "Not Started"}),
    lambda r: r.create({"client_id": "C1", "status": "Not Started"}),
])
def test_a_write_without_the_firm_or_the_client_is_refused_before_it_is_sent(live, call):
    with pytest.raises(ValueError):
        call(crr.compliance_records_repo)
    assert live == []


def test_an_insert_goes_on_the_privileged_client(live):
    crr.compliance_records_repo.create({"firm_id": "F1", "client_id": "C1", "status": "Not Started"})
    assert [n for n, *_r in live][:2] == ["table", "insert"]


def test_in_mock_mode_a_named_client_holds_the_write_to_that_clients_row():
    rec = crr.compliance_records_repo.create({"firm_id": "F-461", "client_id": "C-A", "compliance_type": "GST", "status": "Not Started"})
    assert crr.compliance_records_repo.update(rec["id"], {"status": "Filed"}, firm_id="F-461", client_id="C-B") is None
    assert crr.compliance_records_repo.update(rec["id"], {"status": "Filed"}, firm_id="F-OTHER", client_id="C-A") is None
    assert crr.compliance_records_repo.soft_delete(rec["id"], firm_id="F-461", client_id="C-B") is False
    assert crr.compliance_records_repo.find_by_id(rec["id"])["status"] == "Not Started"
    assert crr.compliance_records_repo.update(rec["id"], {"status": "In Progress"}, firm_id="F-461", client_id="C-A")["status"] == "In Progress"


def _runtime_sources():
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "scripts/", ".venv", "venv")) or "/site-packages/" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "compliance_records_repo" in text:
            yield rel, text


def test_every_runtime_caller_of_a_write_names_the_client():
    bad, seen = [], 0
    for rel, text in _runtime_sources():
        for node in ast.walk(ast.parse(text)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_METHODS):
                continue
            recv = ast.unparse(node.func.value)
            if not recv.endswith("compliance_records_repo"):
                continue
            seen += 1
            kws = {k.arg for k in node.keywords}
            if "client_id" not in kws:
                bad.append(f"{rel}:{node.lineno} {node.func.attr} names no client_id")
            if node.func.attr in {"update", "soft_delete"} and "firm_id" not in kws:
                bad.append(f"{rel}:{node.lineno} {node.func.attr} names no firm_id")
    assert seen >= 8, f"only {seen} write calls found; the scan has stopped matching"
    assert not bad, "\n".join(bad)


def _without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def test_the_browser_only_reads_the_obligation_store():
    hits = []
    for folder in ("app", "components", "lib"):
        for path in (WEB / folder).rglob("*.ts*"):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            code = _without_comments(path.read_text(encoding="utf-8", errors="ignore"))
            for m in re.finditer(r"[\"'`]compliance_records[\"'`]", code):
                before, after = code[: m.start()], code[m.end():]
                if re.search(r"\.from\(\s*$", before) and re.match(r"\s*\)\s*\.select\(", after):
                    continue
                hits.append(str(path.relative_to(WEB)))
    assert not hits, f"the browser names compliance_records other than in a read: {hits}"
