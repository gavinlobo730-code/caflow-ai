"""A CA's health override replaces a dimension's score, and until now it did not.

WHAT WAS WRONG (3a-4, 25-09-2026). `POST /api/health/scores/{client_id}/override`
has existed since migration 059 and both health screens call it. Both screens
also LISTED the resulting rows, over PostgREST, under a heading reading "Active
Overrides". And a tree-wide grep for `health_overrides` found the router's CRUD
block, those two browser reads, and nothing else — `_calculate_scores_db` never
touched the table. So the CA corrected a dimension, saw their correction listed
as active, and the number they were correcting did not move.

Three more things came out of the same reading, and each has its own test here:

  · `DELETE /overrides/{id}` was written and guarded and had NO caller, so an
    override recorded without an end date could never be withdrawn.
  · `expires_at` was checked by nothing, so one that lapsed in March was still
    presented as in force in September.
  · The two screens spoke DIFFERENT dimension vocabularies. The client tab's
    picker offered the legacy flat columns (`compliance_score`,
    `relationship_risk_score`, …), which are not the seven dimensions
    `health_overrides.dimension` is matched against — so every override
    recorded there named something the engine has never heard of.

MEASURED FIRST: production holds ZERO `health_overrides` rows, so none of this
was wrong on anybody's screen — it was wrong the first time the control was
used. Latent, and on the demo path.

⚠️ THE ORDER AGAINST THE HARD OVERRIDE IS LOAD-BEARING and has its own test.
`create_override`'s own comment names the risk: "an override can force a
client's grade to anything (including masking a real Critical status)". The
manual override is applied FIRST and the Chapter 16 hard override AFTER, so a
CA can raise a dimension and still cannot hide a missed notice deadline.
"""
from __future__ import annotations

import inspect
import io
import pathlib
from datetime import date

import pytest

import routers.health as hl
from domain.health import overrides as ov
from domain.health import scoring
from domain.health.overrides import apply_overrides

_WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"
_FIRM_SCREEN = _WEB / "app" / "health" / "[client_id]" / "HealthDetailClient.tsx"
_CLIENT_SCREEN = _WEB / "app" / "clients" / "[id]" / "health" / "page.tsx"

FIRM, CLIENT = "firm-ov", "client-ov"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}

COMPUTED = {
    "compliance_health": 88, "accounting_quality": 90, "work_progress": 75,
    "document_health": 85, "ai_risk_signals": 70, "open_notices": 100,
    "client_responsiveness": 48,
}


def _row(**kw) -> dict:
    base = {
        "id": "o1", "client_id": CLIENT, "firm_id": FIRM,
        "dimension": "client_responsiveness", "override_score": 90,
        "reason": "Client was travelling", "expires_at": None,
        "is_active": True, "override_at": "2026-09-01T00:00:00+00:00",
        "created_at": "2026-09-01T00:00:00+00:00",
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    hl._MOCK_SCORES.clear()
    hl._MOCK_OVERRIDES.clear()
    monkeypatch.setattr(hl, "_db", lambda: None)
    monkeypatch.setattr(hl, "assert_client_access", lambda *a, **k: None)
    yield
    hl._MOCK_SCORES.clear()
    hl._MOCK_OVERRIDES.clear()


# ── The rule ─────────────────────────────────────────────────────────────────

def test_an_override_replaces_its_dimension_and_moves_the_composite():
    before = scoring.weighted_score(COMPUTED)
    out = apply_overrides(COMPUTED, [_row()], as_at=date(2026, 9, 25))
    assert out.scores["client_responsiveness"] == 90
    assert out.overall_score > before, (
        "the whole point: the composite moved because the dimension did"
    )
    assert [a.dimension for a in out.applied] == ["client_responsiveness"]
    assert out.applied[0].computed_score == 48
    assert out.ignored == []


def test_the_computed_scores_are_not_mutated():
    """`scores` is a new dict — a caller that still needs the raw computation
    (the history snapshot does) must not find it silently rewritten."""
    snapshot = dict(COMPUTED)
    apply_overrides(COMPUTED, [_row()], as_at=date(2026, 9, 25))
    assert COMPUTED == snapshot


def test_an_override_is_good_ON_its_end_date():
    """A period somebody picked from a date control runs to the end of the day
    they picked — `domain/inventory/batches.py`'s reading of an expiry. The
    other reading withdraws a correction a day early."""
    row = _row(expires_at="2026-09-25")
    assert apply_overrides(COMPUTED, [row], as_at=date(2026, 9, 25)).applied
    lapsed = apply_overrides(COMPUTED, [row], as_at=date(2026, 9, 26))
    assert lapsed.applied == []
    assert [i.why for i in lapsed.ignored] == ["expired"]
    assert lapsed.scores["client_responsiveness"] == 48


def test_the_end_date_is_the_indian_one():
    """19:00 UTC on 25 September is 00:30 IST on the 26th, so an override
    stamped then is good all of the 26th in India. Reading the UTC date would
    withdraw it a day early — the defect this codebase keeps re-finding, from
    `recurring_task_service` to the memory pipeline's month buckets."""
    row = _row(expires_at="2026-09-25T19:00:00+00:00")
    assert apply_overrides(COMPUTED, [row], as_at=date(2026, 9, 26)).applied, (
        "the expiry was read in UTC, not IST"
    )
    assert apply_overrides(COMPUTED, [row], as_at=date(2026, 9, 27)).applied == []


@pytest.mark.parametrize("row,why", [
    (_row(dimension="relationship_risk_score"), "unknown_dimension"),
    (_row(dimension=None), "unknown_dimension"),
    (_row(override_score=None), "no_score"),
    (_row(override_score=101), "out_of_range"),
    (_row(override_score=-1), "out_of_range"),
    (_row(expires_at="not a date"), "unreadable_expiry"),
    (_row(is_active=False), "withdrawn"),
])
def test_every_override_that_does_not_apply_says_why(row, why):
    out = apply_overrides(COMPUTED, [row], as_at=date(2026, 9, 25))
    assert out.applied == []
    assert [i.why for i in out.ignored] == [why]
    assert out.ignored[0].explanation == ov.IGNORED_REASONS[why]
    assert out.scores == COMPUTED


def test_the_reasons_are_all_different():
    """Stated on the ANSWERS rather than on the data, so moving a reason in or
    out cannot make this vacuous."""
    assert len(set(ov.IGNORED_REASONS.values())) == len(ov.IGNORED_REASONS)


def test_the_later_override_wins_and_the_earlier_one_is_named():
    early = _row(id="early", override_score=60, override_at="2026-09-01T00:00:00+00:00")
    late = _row(id="late", override_score=95, override_at="2026-09-20T00:00:00+00:00")
    for pair in ([early, late], [late, early]):
        out = apply_overrides(COMPUTED, pair, as_at=date(2026, 9, 25))
        assert out.scores["client_responsiveness"] == 95
        assert [a.override_id for a in out.applied] == ["late"]
        assert [(i.override_id, i.why) for i in out.ignored] == [("early", "superseded")]


def test_two_overrides_recorded_in_the_same_second_resolve_the_same_way():
    """The recency chain ends on the id, so it is TOTAL — the same property
    `domain/accounting/line_order` needs for a voucher's lines."""
    a = _row(id="aaa", override_score=60)
    b = _row(id="bbb", override_score=95)
    assert (apply_overrides(COMPUTED, [a, b], as_at=date(2026, 9, 25)).scores
            == apply_overrides(COMPUTED, [b, a], as_at=date(2026, 9, 25)).scores)


def test_the_clock_is_an_argument_and_not_read_inside():
    """A pure rule that reads the clock is untestable and lets two callers
    disagree about which day it is."""
    sig = inspect.signature(apply_overrides)
    assert sig.parameters["as_at"].default is inspect.Parameter.empty
    assert sig.parameters["as_at"].kind is inspect.Parameter.KEYWORD_ONLY


# ── The router applies it, and the hard override still wins ──────────────────

def test_the_mock_calculation_honours_an_override():
    hl._MOCK_OVERRIDES.append(_row())
    before = hl._calculate_scores_mock("other-client")["overall_score"]
    after = hl._calculate_scores_mock(CLIENT)
    assert after["client_responsiveness_score"] == 90
    assert after["overall_score"] > before
    assert [o["dimension"] for o in after["overridden_dimensions"]] == ["client_responsiveness"]
    assert after["ignored_overrides"] == []


def test_an_override_cannot_mask_a_hard_override(monkeypatch):
    """`create_override`'s own comment names this as the thing to prevent."""
    monkeypatch.setattr(hl, "_detect_hard_override_mock",
                        lambda cid: "notice_deadline_missed")
    hl._MOCK_OVERRIDES.append(_row(override_score=100))
    out = hl._calculate_scores_mock(CLIENT)
    assert out["grade"] == "Critical"
    assert out["overall_score"] <= 34
    assert out["is_critical"] is True


def test_both_payload_keys_are_always_present():
    """An absent key and an empty list read the same to a screen and are
    different bugs — `domain/accounting/journal_source`'s discipline."""
    out = hl._calculate_scores_mock("nobody")
    assert out["overridden_dimensions"] == []
    assert out["ignored_overrides"] == []


# ── The working must never reach a write ─────────────────────────────────────

def test_the_override_working_is_not_a_column_and_is_stripped():
    """`health_scores` has no `overridden_dimensions` column, and the computed
    dict is spread into an upsert at two call sites — so sending it raises
    PGRST204 against a real database and passes in mock mode, which is exactly
    what migration 291 had to repair on `form_26as_reconciliations`."""
    scores = hl._calculate_scores_mock(CLIENT)
    assert set(hl._NOT_COLUMNS) <= set(scores)
    stripped = hl._columns_only(scores)
    for key in hl._NOT_COLUMNS:
        assert key not in stripped
    assert "dimensions" in stripped, "that one IS a column (jsonb)"
    assert stripped["overall_score"] == scores["overall_score"]


def test_every_health_scores_write_goes_through_the_stripper():
    """Stated on the SOURCE because there are four of them — two upserts and
    two history snapshots — and one left out is invisible until a real
    database refuses it."""
    src = io.open(pathlib.Path(hl.__file__), encoding="utf-8").read()
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "**scores,\n" not in body, (
        "a computed score is spread into a payload without _columns_only"
    )
    assert "**scores,\n" not in body.replace("**_columns_only(scores),", "")
    assert body.count("_columns_only(scores)") >= 4


def test_the_mock_row_has_the_same_shape_as_the_stored_one():
    """A mock row that accepts what production refuses is how a slice comes to
    pass under test and fail against a database."""
    hl._MOCK_OVERRIDES.append(_row())
    hl.calculate_score(CLIENT, current_user=USER)
    stored = hl._MOCK_SCORES[CLIENT]
    for key in hl._NOT_COLUMNS:
        assert key not in stored


# ── The endpoint answers which are in force ──────────────────────────────────

def test_list_overrides_says_what_is_in_force_and_what_is_not():
    hl._MOCK_SCORES[CLIENT] = {f"{k}_score": v for k, v in COMPUTED.items()}
    hl._MOCK_OVERRIDES.extend([
        _row(id="live"),
        _row(id="lapsed", expires_at="2020-01-01"),
        _row(id="unknown", dimension="relationship_risk_score"),
    ])
    rows = hl.list_overrides(client_id=CLIENT, current_user=USER)["data"]
    by_id = {r["id"]: r for r in rows}
    assert by_id["live"]["in_force"] is True
    assert by_id["live"]["not_in_force_because"] is None
    assert by_id["live"]["computed_score"] == 48, "so the screen can show 48 → 90"
    assert by_id["lapsed"]["in_force"] is False
    assert by_id["lapsed"]["not_in_force_because"] == "expired"
    assert by_id["unknown"]["not_in_force_because"] == "unknown_dimension"
    assert by_id["unknown"]["explanation"]


# ── The browser, pinned from the Python side ─────────────────────────────────

def test_both_screens_can_withdraw_an_override():
    for path in (_FIRM_SCREEN, _CLIENT_SCREEN):
        src = io.open(path, encoding="utf-8").read()
        assert "/api/health/overrides/${" in src, f"{path.name} cannot remove one"
        assert 'method: "DELETE"' in src, f"{path.name} has no DELETE"


def test_neither_screen_reads_the_override_table_itself():
    """Whether an override is in force is the rule the CALCULATION applies. A
    screen deriving its own answer would be a second copy of it, which is how
    these two came to disagree about the dimension vocabulary in the first
    place — the Schedule III caption lesson."""
    for path in (_FIRM_SCREEN, _CLIENT_SCREEN):
        src = io.open(path, encoding="utf-8").read()
        assert '.from("health_overrides")' not in src, f"{path.name} still reads the table"
        assert "/api/health/overrides?client_id=" in src, f"{path.name} does not ask"


def test_a_picker_only_offers_dimensions_the_engine_has():
    """A screen must never invite a CA to record something the server will not
    honour — the `attachmentsReadOnly` discipline. The client tab used to offer
    the legacy flat columns, so every override recorded there named a
    dimension the model does not have."""
    src = io.open(_CLIENT_SCREEN, encoding="utf-8").read()
    start = src.index("const OVERRIDE_DIMENSIONS")
    block = src[start:src.index("};", start)]
    for dimension in scoring.DIMENSIONS:
        assert f"{dimension}:" in block, f"the picker is missing {dimension}"
    for legacy in ("relationship_risk_score", "financial_risk_score",
                   "engagement_health_score"):
        assert f"{legacy}:" not in block, f"the picker still offers {legacy}"


def test_the_router_re_exports_the_domain_objects_rather_than_copying_them():
    assert hl.DIMENSION_WEIGHTS_BP is scoring.DIMENSION_WEIGHTS_BP
    assert hl._grade is scoring.grade
    assert hl._weighted_score is scoring.weighted_score
    assert sum(scoring.DIMENSION_WEIGHTS_BP.values()) == 10000
