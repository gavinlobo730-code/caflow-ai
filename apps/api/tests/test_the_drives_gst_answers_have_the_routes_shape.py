"""The browser drive answers the GST builds and the filing's status move in the routes' own shape (POST-A-396).

The drive's stub used to answer `POST /api/gst/gstr1/from-books`, `POST /api/gst/gstr3b/from-books` and the filing's
`PATCH .../status` with hand-typed copies that left out what the routes always send (GSTR-1's amendments block, GSTR-3B's
credit ledger and set-off workings, the compliance calendar's answer to a filing), so those screens were driven in a lighter
layout than the one a CA sees. `apps/web/scripts/drive/gst-answers.json` is written by `scripts/write_drive_gst_answers.py`
from the builders themselves; this holds the file to them by SHAPE (every key, at every depth, and the first element of a
list of objects), so a key the builder adds, renames or drops fails here and not in a browser nobody runs. A scenario may
override a figure: the values are not held, only that nothing the route sends is missing and nothing it never sends is there.
"""
from __future__ import annotations

import json
import pathlib
import re

from scripts.write_drive_gst_answers import FIXTURE, real_answers

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _shape(value, path="$"):
    """Every key path in `value`: a dict's keys, recursively, and the first element of a non-empty list of dicts."""
    out = set()
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(f"{path}.{k}")
            out |= _shape(v, f"{path}.{k}")
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        out |= _shape(value[0], f"{path}[]")
    return out


def test_the_drives_answers_have_every_key_the_routes_send_and_none_they_do_not(monkeypatch):
    real = json.loads(json.dumps(real_answers(monkeypatch), default=str))
    served = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert sorted(served) == sorted(real), "the fixture does not hold the four answers"
    for name in real:
        missing = sorted(_shape(real[name]) - _shape(served[name]))
        extra = sorted(_shape(served[name]) - _shape(real[name]))
        assert not missing and not extra, (
            f"{name}: the drive's answer is not the route's shape (rerun `APP_ENV=development python3 "
            f"scripts/write_drive_gst_answers.py` from apps/api). Missing: {missing[:12]}. Never sent: {extra[:12]}.")


def test_the_answers_carry_the_blocks_the_hand_typed_copies_left_out():
    served = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert served["gstr1_from_books"]["amendments"]["included"] is True
    assert "credit_ledger" in served["gstr3b_from_books"] and "itc_utilisation" in served["gstr3b_from_books"]["working"]
    for kind in ("gstr1", "gstr3b"):
        for month, answer in served[f"{kind}_submitted_obligation"].items():
            assert set(answer) == {"state", "closed", "obligation_id", "message"}, f"{kind} {month}"


def test_the_gst_openers_answer_from_the_fixture():
    dates = (WEB / "scripts" / "drive" / "scenarios" / "dates.mjs").read_text(encoding="utf-8")
    assert re.search(r"gst-answers\.json", dates), "dates.mjs does not read the fixture"
    for route, key in ((r"gstr1\\/from-books", "gstr1_from_books"), (r"gstr3b\\/from-books", "gstr3b_from_books")):
        stubs = re.findall(r"re: /api\\/gst\\/" + route + r"\$/, reply: \(_req, raw\) => ok\(\{\s*\.\.\.(\w+)\.(\w+)", dates)
        assert stubs and all(k == key for _, k in stubs), f"a stub of {route} does not answer from GST_ANSWERS.{key}: {stubs}"
    assert "submitted_obligation" in dates, "the filing's status move does not answer with the calendar's answer"
