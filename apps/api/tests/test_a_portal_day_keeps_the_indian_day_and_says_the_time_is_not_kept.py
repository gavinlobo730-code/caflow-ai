"""A day a portal printed is kept as the Indian day, and the request's own schema says a time of day is not kept (POST-A-392, item 4).

The e-invoice acknowledgement date and the e-way bill's two dates are DAYS (POST-A-251): `core.ist_clock.portal_day` reads a longer
value for the Indian day it falls on and the column keeps that day, so no reader has to guess what a stored time meant. The time of
day is dropped, deliberately, and that was said nowhere a caller could read it. It is said now in the request models' field
descriptions, which is the schema a caller that is not the screen reads (the screens send a bare day).
"""
from __future__ import annotations

from datetime import date

import pytest

from core.ist_clock import portal_day
from routers.einvoice import RecordIRNRequest
from routers.eway_bill import RecordEWBGeneratedRequest


@pytest.mark.parametrize("value, day", [
    ("2026-11-15", date(2026, 11, 15)),
    ("2026-11-15 14:32:00", date(2026, 11, 15)),          # no offset: the portal's own wall-clock, its date part is the day
    ("2026-11-15T20:00:00Z", date(2026, 11, 16)),         # an instant: 20:00 UTC is 01:30 on the 16th in India
    ("2026-11-15T20:00:00+05:30", date(2026, 11, 15)),
])
def test_a_longer_value_is_kept_as_the_indian_day_it_names(value, day):
    assert portal_day(value) == day


@pytest.mark.parametrize("model, fields", [(RecordIRNRequest, ["ack_date"]), (RecordEWBGeneratedRequest, ["ewb_date", "ewb_valid_upto"])])
def test_the_schema_says_the_time_of_day_is_not_kept(model, fields):
    props = model.model_json_schema()["properties"]
    for field in fields:
        assert "the time is not kept" in props[field].get("description", ""), field
