"""A document number is one past the HIGHEST in its series, not one past the count.

SALES-04. Five routers and two services each carried their own copy of

    resp = db.table(T).select("id", count="exact")...execute()
    return (resp.count or 0) + 1

which is deterministic. Delete a draft from the middle of a series and it
returns a number that is already taken — on every attempt, for the rest of the
financial year, because services/numbering.py's retry recomputes the SAME
value six times and the UNIQUE constraint rejects it every time. The client
can never create another document of that kind.

Two rules are pinned here, because two things were wrong:

  1. the number comes from the MAXIMUM, which also makes the retry converge
     (a re-read after a concurrent insert returns a number that has moved);
  2. the sequence is computed over exactly the scope the UNIQUE constraint
     covers, which sales_debit_notes and purchase_credit_notes did not do —
     migration 210 created them per-firm while their routers number per
     client, so the firm's SECOND client could never raise either document.
"""
import ast
import pathlib

import pytest

from services.numbering import (
    NUMBER_SERIES,
    insert_with_number,
    next_sequence,
    sequence_after,
)

API_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ─────────────────────────── the rule itself ───────────────────────────

def test_an_empty_series_starts_at_one():
    assert sequence_after([], "CN-2627-") == 1


def test_a_full_series_continues_from_the_highest():
    assert sequence_after(["CN-2627-0001", "CN-2627-0002", "CN-2627-0003"], "CN-2627-") == 4


def test_deleting_the_middle_of_a_series_does_not_reissue_a_live_number():
    """The wedge. COUNT+1 of {0001, 0003} is 3 — already taken, forever."""
    remaining = ["CN-2627-0001", "CN-2627-0003"]
    assert len(remaining) + 1 == 3                      # what the old code returned
    assert sequence_after(remaining, "CN-2627-") == 4   # what it must return


def test_a_gap_left_by_a_deletion_stays_a_gap():
    series = ["CN-2627-0001", "CN-2627-0003", "CN-2627-0004"]
    assert sequence_after(series, "CN-2627-") == 5
    # 0002 is never handed out again — the audit_log holds its create and delete.


def test_another_clients_series_and_another_year_are_not_this_series():
    assert sequence_after(
        ["CN-2526-0009", "DN-2627-0007", "CN-2627-0002"], "CN-2627-") == 3


def test_a_number_that_is_not_a_number_is_skipped_not_guessed():
    assert sequence_after(["CN-2627-0002", "CN-2627-DRAFT", None, ""], "CN-2627-") == 3


def test_an_unpadded_number_does_not_beat_a_padded_one():
    """Lexicographic order puts "…-9" above "…-0042"; numeric order does not.
    Reading a window and taking the numeric maximum is what makes this safe."""
    assert sequence_after(["CN-2627-9", "CN-2627-0042"], "CN-2627-") == 43


# ─────────────────── scope must match the constraint ───────────────────

class _Recorder:
    """Enough of the PostgREST builder to record what a read asked for."""

    def __init__(self, rows):
        self.rows = rows
        self.eq_columns = {}
        self.like = None
        self.ordered = None
        self.limited = None

    def table(self, name):
        self.table_name = name
        return self

    def select(self, field):
        self.selected = field
        return self

    def eq(self, column, value):
        self.eq_columns[column] = value
        return self

    def like(self, field, pattern):   # noqa: F811 - shadowed attribute is fine
        self.like = (field, pattern)
        return self

    def order(self, field, desc=False):
        self.ordered = (field, desc)
        return self

    def limit(self, n):
        self.limited = n
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


def _recorder(rows):
    rec = _Recorder(rows)
    rec.like = lambda field, pattern: (setattr(rec, "like_args", (field, pattern)), rec)[1]
    return rec


def test_a_scope_narrower_than_the_unique_constraint_is_refused():
    """purchase_payments is UNIQUE (firm_id, payment_no) — per FIRM. Numbering
    it per client is what made the second client's first document impossible."""
    with pytest.raises(ValueError) as exc:
        next_sequence(_recorder([]), "purchase_payments", "VPMT-2627-",
                      firm_id="f1", client_id="c1")
    assert "purchase_payments" in str(exc.value)


def test_a_scope_wider_than_the_unique_constraint_is_refused():
    with pytest.raises(ValueError):
        next_sequence(_recorder([]), "credit_notes", "CN-2627-", firm_id="f1")


def test_the_read_asks_for_the_columns_the_constraint_covers():
    rec = _recorder([{"credit_note_no": "CN-2627-0007"}])
    assert next_sequence(rec, "credit_notes", "CN-2627-",
                         firm_id="f1", client_id="c1") == 8
    assert rec.eq_columns == {"firm_id": "f1", "client_id": "c1"}
    assert rec.like_args == ("credit_note_no", "CN-2627-%")
    assert rec.ordered == ("credit_note_no", True)
    assert rec.limited and rec.limited > 1


def test_a_failed_read_raises_rather_than_returning_one():
    """`except Exception: return 1` turned a transient PostgREST failure into
    the number 1 — a collision with the live first document, or on a table
    without the constraint a second document carrying a number in the books."""
    class Broken(_Recorder):
        def execute(self):
            raise RuntimeError("PostgREST unavailable")

    broken = Broken([])
    broken.like = lambda f, p: broken
    with pytest.raises(RuntimeError):
        next_sequence(broken, "credit_notes", "CN-2627-", firm_id="f1", client_id="c1")


# ────────────────────── the retry loop converges ───────────────────────

def test_the_retry_converges_when_a_concurrent_insert_takes_the_number():
    """Max+1 is not only the fix — it is what makes the six-attempt retry in
    insert_with_number able to succeed. Count+1 returns the same number on
    every attempt, so a collision is fatal however many times it is retried."""
    taken = ["CN-2627-0001"]

    class DB:
        def table(self, _):
            return self

        def insert(self, payload):
            self.payload = payload
            return self

        def execute(self):
            no = self.payload["credit_note_no"]
            if no in taken:
                raise RuntimeError('duplicate key value violates unique constraint (23505)')
            taken.append(no)
            return type("R", (), {"data": [self.payload]})()

    row = insert_with_number(
        DB(), "credit_notes", {"client_id": "c1"}, "credit_note_no",
        lambda s: f"CN-2627-{s:04d}",
        lambda: sequence_after(taken, "CN-2627-"),
    )
    assert row["credit_note_no"] == "CN-2627-0002"


def test_count_plus_one_could_never_converge():
    """The negative control for the test above, stated as behaviour: with the
    old sequence the same retry exhausts, because the value never moves."""
    taken = ["CN-2627-0001"]

    class DB:
        def table(self, _):
            return self

        def insert(self, payload):
            self.payload = payload
            return self

        def execute(self):
            raise RuntimeError('duplicate key value violates unique constraint (23505)')

    with pytest.raises(RuntimeError):
        insert_with_number(
            DB(), "credit_notes", {}, "credit_note_no",
            lambda s: f"CN-2627-{s:04d}",
            lambda: len(taken) + 1,     # the old shape
        )


# ─────────── no copy of the old shape survives anywhere ────────────

def _numbering_functions():
    """Every module-level function whose name says it produces a sequence."""
    for path in sorted(API_ROOT.glob("routers/*.py")) + sorted(API_ROOT.glob("services/*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.endswith("_seq"):
                yield path.relative_to(API_ROOT), node


def test_no_sequence_is_computed_from_a_count():
    """The RULE, not a spelling of it: a function that produces a document
    sequence may not reach a count. Seven copies of `count="exact"` + 1 lived
    in seven files, and prose saying 'use the helper' is what let them."""
    offenders = []
    for rel, node in _numbering_functions():
        body = ast.unparse(node)
        if "count=" in body or "len(" in body:
            offenders.append(str(rel) + "::" + node.name)
    assert not offenders, (
        "these compute a document number from a tally rather than the highest "
        f"number in the series: {offenders}")


def test_every_sequence_delegates_to_the_one_helper():
    named = []
    for rel, node in _numbering_functions():
        if "next_sequence" not in ast.unparse(node):
            named.append(str(rel) + "::" + node.name)
    assert not named, (
        "these do their own numbering instead of services.numbering."
        f"next_sequence, so the scope check cannot reach them: {named}")


def test_every_series_the_helper_knows_is_actually_used():
    """A table in NUMBER_SERIES that nothing numbers is a stale entry; a table
    numbered outside it cannot be scope-checked at all."""
    sources = "\n".join(
        p.read_text() for p in
        sorted(API_ROOT.glob("routers/*.py")) + sorted(API_ROOT.glob("services/*.py")))
    unused = [t for t in NUMBER_SERIES if f'"{t}"' not in sources]
    assert not unused, f"NUMBER_SERIES names tables nothing numbers: {unused}"
