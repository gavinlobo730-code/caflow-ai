"""The in-memory double of the three challan functions and the functions of migration 585 leave the same thing behind (ledger POST-A-419).

WHY THIS EXISTS
    The mock suite has no database, so every test of `create_challan`, `itc_04_service.record_return` and `update_challan` runs against `tests/challan_functions_double.py`, which mirrors the
    three database functions in Python. A double that answers a question its own way is a double that eventually disagrees with the thing it stands for, and every mock-mode test written
    against it would then pass for the wrong reason. This runs the same scenarios through the real functions on Postgres and through the double and compares what each answers (success or the
    refusal's own words) and what each leaves behind (the challan's status and day, its lines, its lots), which is the pin `docs/design-record` calls a parity test and the rest of the suite
    uses for the one other place a rule exists twice (`test_cash_flow_sql_parity_pg.py`). The functions' own rules are held by `test_585_..._pg.py`; this holds the double to them.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_585_a_delivery_challan_is_written_in_one_transaction_and_says_when_it_was_issued_pg as real
from tests import challan_functions_double as double

db = real.db      # the throwaway database, with the firm and the two clients seeded
pytestmark = pytest.mark.skipif(not real._ADMIN or not shutil.which("psql"), reason="needs HARNESS_PG and psql on PATH")

FIRM, CLIENT, OTHER_CLIENT = real.FIRM, real.CLIENT, real.OTHER_CLIENT


class RealDatabase:
    """The functions on Postgres, called as the API's privileged client calls them."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def _ids(self, no: str) -> tuple[str, list[str]]:
        cid = real._rows(self.dsn, f"SELECT id FROM delivery_challans WHERE document_no = '{no}' AND firm_id = '{FIRM}' ORDER BY created_at LIMIT 1;")[0]
        lines = real._rows(self.dsn, f"SELECT id FROM delivery_challan_lines WHERE challan_id = '{cid}' ORDER BY line_order, created_at;")
        return cid, lines

    @staticmethod
    def _outcome(done) -> tuple:
        if done.returncode == 0:
            return ("ok",)
        found = re.search(r"ERROR:\s+(.*)", done.stderr)
        return ("refused", found.group(1).strip() if found else done.stderr)

    def create(self, header: dict, lines: list) -> tuple:
        return self._outcome(real._create_call(self.dsn, header, lines))

    def issue(self, no: str) -> None:
        cid, _ = self._ids(no)
        assert real._psql(self.dsn, f"UPDATE delivery_challans SET status = 'issued', issued_at = now() WHERE id = '{cid}';").returncode == 0

    def lot(self, no: str, line: int, lot: dict) -> tuple:
        cid, lines = self._ids(no)
        done = real._lot_call(self.dsn, cid, {**lot, "challan_line_id": lines[line]})
        out = self._outcome(done)
        if out == ("ok",):
            answer = real._answer(done)
            return ("ok", bool(answer["challan_marked_received_back"]), answer["received_back_on"])
        return out

    def correct(self, no: str, header: dict, fixes: list) -> tuple:
        cid, lines = self._ids(no)
        wired = [{**fix, "id": lines[fix["line"]]} if "line" in fix else fix for fix in fixes]
        for fix in wired:
            fix.pop("line", None)
        done = real._call(self.dsn, f"SELECT public.correct_draft_challan_lines_atomic('{FIRM}', '{CLIENT}', '{cid}', {real._json(header)}, {real._json(wired)});")
        out = self._outcome(done)
        return ("ok", int(real._answer(done))) if out == ("ok",) else out

    def snapshot(self) -> dict:
        got = real._rows(self.dsn, """SELECT json_build_object(
            'challans', (SELECT coalesce(json_agg(json_build_object('no', document_no, 'status', status, 'back_on', received_back_on, 'notes', notes) ORDER BY document_no), '[]'::json) FROM delivery_challans),
            'lines', (SELECT coalesce(json_agg(json_build_object('c', c.document_no, 'n', l.line_order, 'description', l.description, 'hsn', l.hsn_sac, 'quantity', l.quantity) ORDER BY c.document_no, l.line_order), '[]'::json)
                        FROM delivery_challan_lines l JOIN delivery_challans c ON c.id = l.challan_id),
            'lots', (SELECT coalesce(json_agg(json_build_object('c', c.document_no, 'on', r.returned_on, 'back', r.quantity_returned, 'lost', r.quantity_lost_or_wasted) ORDER BY c.document_no, r.returned_on, r.created_at), '[]'::json)
                        FROM delivery_challan_returns r JOIN delivery_challans c ON c.id = r.challan_id))::text;""")
        return _normal(json.loads(got[0]))


class InMemoryDatabase:
    """The same three calls on the double."""

    def __init__(self):
        self.tables: dict = {}

    @staticmethod
    def _new_id(_table: str) -> str:
        return str(uuid.uuid4())

    def _ids(self, no: str) -> tuple[str, list[str]]:
        challan = next(c for c in self.tables["delivery_challans"] if c["document_no"] == no)
        lines = [ln["id"] for ln in self.tables.get("delivery_challan_lines", []) if ln["challan_id"] == challan["id"]]
        return challan["id"], lines

    @staticmethod
    def _outcome(error: BaseException) -> tuple:
        found = re.search(r"'message': '((?:[^'\\]|\\.)*)'", str(error))
        return ("refused", found.group(1).replace("\\'", "'") if found else str(error))

    def create(self, header: dict, lines: list) -> tuple:
        try:
            double.create(self.tables, self._new_id, header, lines)
        except double.Refusal as e:
            return self._outcome(e)
        return ("ok",)

    def issue(self, no: str) -> None:
        next(c for c in self.tables["delivery_challans"] if c["document_no"] == no)["status"] = "issued"

    def lot(self, no: str, line: int, lot: dict) -> tuple:
        cid, lines = self._ids(no)
        try:
            got = double.record_lot(self.tables, self._new_id, FIRM, CLIENT, cid, {**lot, "challan_line_id": lines[line]})
        except double.Refusal as e:
            return self._outcome(e)
        return ("ok", got["challan_marked_received_back"], got["received_back_on"])

    def correct(self, no: str, header: dict, fixes: list) -> tuple:
        cid, lines = self._ids(no)
        wired = [{**fix, "id": lines[fix["line"]]} if "line" in fix else fix for fix in fixes]
        for fix in wired:
            fix.pop("line", None)
        try:
            return ("ok", double.correct_draft(self.tables, FIRM, CLIENT, cid, header, wired))
        except double.Refusal as e:
            return self._outcome(e)

    def snapshot(self) -> dict:
        by_id = {c["id"]: c["document_no"] for c in self.tables.get("delivery_challans", [])}
        challans = sorted(({"no": c["document_no"], "status": c["status"], "back_on": c.get("received_back_on"), "notes": c.get("notes")}
                           for c in self.tables.get("delivery_challans", [])), key=lambda c: c["no"])
        lines = sorted(({"c": by_id[ln["challan_id"]], "n": ln.get("line_order", 0), "description": ln.get("description"), "hsn": ln.get("hsn_sac"), "quantity": ln.get("quantity")}
                        for ln in self.tables.get("delivery_challan_lines", [])), key=lambda ln: (ln["c"], ln["n"]))
        lots = sorted(({"c": by_id[r["challan_id"]], "on": r.get("returned_on"), "back": r.get("quantity_returned"), "lost": r.get("quantity_lost_or_wasted")}
                       for r in self.tables.get("delivery_challan_returns", [])), key=lambda r: (r["c"], str(r["on"])))
        return _normal({"challans": challans, "lines": lines, "lots": lots})


def _normal(snapshot: dict) -> dict:
    """Quantities compare as numbers (Postgres hands back 10.000, the double what it was given) and days as text."""
    for ln in snapshot["lines"]:
        ln["quantity"] = str(Decimal(str(ln["quantity"])).quantize(Decimal("0.001")))
    for lot in snapshot["lots"]:
        lot["back"] = str(Decimal(str(lot["back"] or 0)).quantize(Decimal("0.001")))
        lot["lost"] = str(Decimal(str(lot["lost"] or 0)).quantize(Decimal("0.001")))
        lot["on"] = str(lot["on"])[:10]
    for challan in snapshot["challans"]:
        challan["back_on"] = None if challan["back_on"] is None else str(challan["back_on"])[:10]
    return snapshot


def _header(no="DC/1", **more) -> dict:
    return real._header(document_no=no, **more)


def _line(description="Steel bar", **more) -> dict:
    return real._line(description, **more)


def _lot(**more) -> dict:
    return {"returned_on": "2026-08-20", "quantity_returned": "4", "quantity_lost_or_wasted": "0", "job_worker_challan_no": "JW/22", **more}


#: name -> the steps. A step is (verb, arguments...) and the verbs are the driver's methods; "snapshot" is taken at the end of every scenario.
SCENARIOS = {
    "a challan is made as a draft with its lines": [
        ("create", _header(), [_line("Bar A", line_order=0), _line("Bar B", line_order=1, hsn_sac="7215")]),
    ],
    "a challan with no lines is made and a header may not name a status other than draft": [
        ("create", _header("DC/2"), []),
        ("create", _header("DC/3", status="issued"), [_line()]),
    ],
    "a header may not choose its id, its moment of issue or its day back": [
        ("create", _header("DC/4", id=str(uuid.uuid4())), [_line()]),
        ("create", _header("DC/5", received_back_on="2026-08-01"), [_line()]),
    ],
    "a lot on a draft is refused and on an issued challan is recorded": [
        ("create", _header(), [_line(line_order=0)]),
        ("lot", "DC/1", 0, _lot()),
        ("issue", "DC/1"),
        ("lot", "DC/1", 0, _lot()),
    ],
    "a lot more than the line has left is refused and nothing is recorded": [
        ("create", _header(), [_line(line_order=0)]),
        ("issue", "DC/1"),
        ("lot", "DC/1", 0, _lot(quantity_returned="6")),
        ("lot", "DC/1", 0, _lot(quantity_returned="6", returned_on="2026-08-21")),
        ("lot", "DC/1", 0, _lot(quantity_returned="4", returned_on="2026-08-22")),
    ],
    "goods lost or wasted take room and are not goods that came back": [
        ("create", _header(), [_line(line_order=0)]),
        ("issue", "DC/1"),
        ("lot", "DC/1", 0, _lot(quantity_returned="3", quantity_lost_or_wasted="3")),
        ("lot", "DC/1", 0, _lot(quantity_returned="4", returned_on="2026-08-21")),
        ("lot", "DC/1", 0, _lot(quantity_returned="3", returned_on="2026-08-22")),
        ("lot", "DC/1", 0, _lot(quantity_returned="1", returned_on="2026-08-23")),
    ],
    "the lot that brings the last line to nil stamps the challan on its latest day": [
        ("create", _header(), [_line(line_order=0, quantity=10), _line("Bar B", line_order=1, quantity=5)]),
        ("issue", "DC/1"),
        ("lot", "DC/1", 0, _lot(quantity_returned="10", returned_on="2026-08-25")),
        ("lot", "DC/1", 1, _lot(quantity_returned="5", returned_on="2026-08-20")),
        ("lot", "DC/1", 1, _lot(quantity_returned="1", returned_on="2026-08-26")),
    ],
    "quantities are judged as the column stores them": [
        ("create", _header(), [_line(line_order=0, quantity="2.001")]),
        ("issue", "DC/1"),
        ("lot", "DC/1", 0, _lot(quantity_returned="1.0005")),
        ("lot", "DC/1", 0, _lot(quantity_returned="1.0005", returned_on="2026-08-21")),
    ],
    "a challan for another reason takes no lot": [
        ("create", _header(reason="sale_on_approval", goods_kind=None), [_line(line_order=0)]),
        ("issue", "DC/1"),
        ("lot", "DC/1", 0, _lot()),
    ],
    "a draft's header and lines are corrected together": [
        ("create", _header(), [_line("Bar A", line_order=0), _line("Bar B", line_order=1)]),
        ("correct", "DC/1", {"notes": "booked"}, [{"line": 0, "description": "Bar A, cut"}, {"line": 1, "hsn_sac": "9988"}]),
    ],
    "a present key writes, null included, and an absent one leaves the column": [
        ("create", _header(notes="first"), [_line("Bar A", line_order=0, hsn_sac="7214")]),
        ("correct", "DC/1", {}, [{"line": 0, "hsn_sac": None}]),
        ("correct", "DC/1", {"notes": None}, [{"line": 0, "description": "Bar A, cut"}]),
    ],
    "a correction naming a line the challan does not hold undoes the header's change too": [
        ("create", _header(), [_line(line_order=0)]),
        ("correct", "DC/1", {"notes": "booked"}, [{"line": 0, "description": "Cut"}, {"id": str(uuid.uuid4()), "description": "Nobody's"}]),
    ],
    "a correction names a line by id and gives its description and its HSN code and nothing else": [
        ("create", _header(), [_line(line_order=0)]),
        ("correct", "DC/1", {}, [{"line": 0, "quantity": 99}]),
        ("correct", "DC/1", {"status": "issued"}, [{"line": 0, "description": "x"}]),
    ],
    "a line is corrected once in a request": [
        ("create", _header(), [_line(line_order=0)]),
        ("correct", "DC/1", {}, [{"line": 0, "description": "x"}, {"line": 0, "hsn_sac": "1"}]),
    ],
    "a lot of nothing is refused by the table and a fourth decimal below half rounds down and fits the room exactly": [
        ("create", _header(), [_line(line_order=0, quantity=2)]),
        ("issue", "DC/1"),
        ("lot", "DC/1", 0, _lot(quantity_returned="0", quantity_lost_or_wasted="0")),
        ("lot", "DC/1", 0, _lot(quantity_returned="1")),
        ("lot", "DC/1", 0, _lot(quantity_returned="1.0004", returned_on="2026-08-21")),
    ],
    "a created line's quantity is stored to three decimals": [
        ("create", _header(), [_line(line_order=0, quantity="1.0005")]),
    ],
    "a header may not name its moment of issue on a create or on a correction": [
        ("create", _header("DC/6", issued_at="2026-08-01T10:00:00+05:30"), [_line()]),
        ("create", _header(), [_line(line_order=0)]),
        ("correct", "DC/1", {"issued_at": "2026-08-01T10:00:00+05:30"}, [{"line": 0, "description": "x"}]),
    ],
    "a status that is the empty text is not a draft": [
        ("create", _header("DC/7", status=""), [_line()]),
    ],
    "a description given as null is refused by the table and undoes the header's change": [
        ("create", _header(), [_line(line_order=0)]),
        ("correct", "DC/1", {"notes": "booked"}, [{"line": 0, "description": None}]),
        ("create", _header("DC/8"), [_line(description=None)]),
    ],
    "an issued challan is not corrected": [
        ("create", _header(), [_line(line_order=0)]),
        ("issue", "DC/1"),
        ("correct", "DC/1", {"notes": "late"}, [{"line": 0, "description": "late"}]),
    ],
}


def _run(driver, steps: list) -> tuple[list, dict]:
    outcomes = []
    for step in steps:
        verb, *args = step
        outcomes.append((verb, getattr(driver, verb)(*args)))
    return outcomes, driver.snapshot()


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_double_answers_and_leaves_what_the_function_does(db, name):
    steps = [(verb, *(copy for copy in args)) for verb, *args in SCENARIOS[name]]
    on_postgres = _run(RealDatabase(db), json.loads(json.dumps(steps)))
    in_memory = _run(InMemoryDatabase(), json.loads(json.dumps(steps)))
    assert in_memory == on_postgres, f"the double and the database disagree on: {name}"


def test_the_set_of_scenarios_cannot_go_vacuous():
    """Every verb the driver has is asked, and the set asks the three functions' refusals and what they leave."""
    asked = {verb for steps in SCENARIOS.values() for verb, *_ in steps}
    assert asked == {"create", "issue", "lot", "correct"}
    assert len(SCENARIOS) >= 20
