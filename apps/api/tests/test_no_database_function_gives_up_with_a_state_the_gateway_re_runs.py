"""No database function gives up with a state the gateway re-runs by itself (ledger POST-A-577; migration 783).

WHAT WAS WRONG
    The API reaches the database through PostgREST. The review of migration 781 (28-11-2026) read in PostgREST's source that every request
    runs inside a transaction its database library re-runs by itself when the server answers serialization_failure (40001) or
    deadlock_detected (40P01). A function that RAISES one of those on purpose, to tell the API "I gave up, nothing was written", is
    therefore never heard: the gateway runs it again. Migration 548's `file_it_declaration` raised 40001 when it could not take the
    declaration's row in three tries, and the first draft of migration 781 raised it when an invoice had moved under a receipt, which is
    permanent for that payload and could only loop. That reading of the gateway was not tried against the live one.

THE RULE (mock mode, read from the migrations)
    For every function the migrations define, its LAST definition (found by number, rollback files left out) raises neither state, by
    code or by name. A function that needs to say "busy" or "prepare this again" raises a state of its own, which the gateway hands on
    with the code. (That the declaration service hears both the function's own state and the older one is held beside its other
    refusals, in test_the_declaration_filing_service_speaks_the_function_it_calls.py.)
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
RE_RUN_BY_THE_GATEWAY = {"40001": "serialization_failure", "40P01": "deadlock_detected"}

_HEADER = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?\"?([a-z_][a-z0-9_]*)\"?\s*\(", re.I)
_DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)?\$")


def _without_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def last_definitions(files: dict[str, str]) -> dict[str, tuple[str, str]]:
    """function name -> (the migration that last defines it, its body with comments taken out)."""
    out: dict[str, tuple[str, str]] = {}
    for name in sorted(files):
        text = _without_comments(files[name])
        for header in _HEADER.finditer(text):
            opening = _DOLLAR.search(text, header.end())
            if not opening:
                continue
            close = text.find(opening.group(0), opening.end())
            if close < 0:
                continue
            out[header.group(1).lower()] = (name, text[opening.end():close])
    return out


def states_raised(body: str) -> set[str]:
    """The re-run states a body raises on purpose: `ERRCODE = '40001'`, `ERRCODE = 'serialization_failure'`, `RAISE serialization_failure`."""
    found = set()
    for code, word in RE_RUN_BY_THE_GATEWAY.items():
        if re.search(rf"ERRCODE\s*=\s*'(?:{code}|{word})'", body, re.I) or re.search(rf"\bRAISE\s+(?:EXCEPTION\s+)?{word}\b", body, re.I) \
                or re.search(rf"\bRAISE\s+SQLSTATE\s+'{code}'", body, re.I):
            found.add(code)
    return found


def _migrations() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")) if not p.name.endswith("_rollback.sql")}


def test_no_functions_last_definition_raises_a_state_the_gateway_re_runs():
    definitions = last_definitions(_migrations())
    assert len(definitions) > 150, f"only {len(definitions)} functions were found: the reader has stopped seeing them"
    offenders = sorted(f"{fn} (last defined in {name}) raises {sorted(states_raised(body))}"
                       for fn, (name, body) in definitions.items() if states_raised(body))
    assert not offenders, (
        "these functions give up with a state PostgREST re-runs by itself, so the API never sees the refusal. Raise a state of the "
        "function's own (as migrations 781 and 783 do) and match it in the service: " + "; ".join(offenders))


def test_the_reader_sees_the_two_functions_as_they_were_and_every_spelling():
    files = _migrations()
    m548 = next(n for n in files if n.startswith("548_"))
    assert states_raised(last_definitions({m548: files[m548]})["file_it_declaration"][1]) == {"40001"}, "the control no longer shows the defect"
    assert last_definitions(files)["file_it_declaration"][0].startswith("783_")
    for spelling in ("RAISE EXCEPTION 'x' USING ERRCODE = '40001';", "RAISE EXCEPTION 'x' USING ERRCODE='serialization_failure';",
                     "RAISE serialization_failure;", "RAISE SQLSTATE '40001';"):
        assert states_raised(spelling) == {"40001"}, spelling
    assert states_raised("RAISE EXCEPTION 'x' USING ERRCODE = 'deadlock_detected';") == {"40P01"}
    assert states_raised("RAISE EXCEPTION 'x' USING ERRCODE = 'RC001'; -- not 40001") == set()
    commented = "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $$ BEGIN\n -- USING ERRCODE = '40001'\n RAISE EXCEPTION 'x' USING ERRCODE = 'DC001'; END $$;"
    assert states_raised(last_definitions({"900_x.sql": commented})["f"][1]) == set()
