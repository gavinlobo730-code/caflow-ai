"""The demo's unregistered reverse-charge supplier is recorded as unregistered, and its self-invoice is issued (PRE-A-004).

What was wrong: the seeder sent every party without a GSTIN with its registration unrecorded, which `domain/gst/rcm_documents`
reads as a NAMED GAP and not as unregistered (rightly: an absent GSTIN is only something nobody recorded). So the reverse-charge
client's bill from its unregistered supplier never had a section 31(3)(f) self-invoice due, and the seeded firm showed none.

What the fixture and seeder do now: the vendor a posted reverse-charge bill comes from, and that has no GSTIN, is recorded as
unregistered; every other unregistered party stays unrecorded, so the gap is still on the screen. The seeder issues the
self-invoice for each such received bill through the screen's own door, before any of the client's GST returns is filed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from domain.demo import fixture
from domain.gst import rcm_documents as rd

FY = "2025-26"
FIRM = fixture.build(FY)
DRAFT = fixture.draft_month(FY)


def _owed(c):
    """(position, bill, vendor) of every posted reverse-charge bill whose vendor is recorded unregistered."""
    out = []
    for n, d in enumerate(c.purchases, start=1):
        v = c.vendors[d.party % len(c.vendors)]
        if d.is_reverse_charge and d.doc_date[:7] != DRAFT and v.registration_recorded == "unregistered":
            out.append((n, d, v))
    return out


def test_only_an_unregistered_supplier_of_a_posted_reverse_charge_bill_is_recorded_and_the_gap_is_still_shown():
    recorded, unrecorded = [], []
    for c in FIRM.clients:
        rcm_parties = {d.party % len(c.vendors) for d in c.purchases if d.is_reverse_charge and d.doc_date[:7] != DRAFT}
        for i, v in enumerate(c.vendors):
            if v.gstin is not None:
                assert v.registration_recorded is None, (c.name, v.name)
            elif i in rcm_parties:
                assert v.registration_recorded == "unregistered", (c.name, v.name)
                recorded.append(v)
            else:
                assert v.registration_recorded is None, (c.name, v.name)
                unrecorded.append(v)
    assert recorded, "no unregistered supplier of a reverse-charge bill: no self-invoice is ever due"
    assert unrecorded, "every unregistered party is recorded: the named gap is never shown"


def test_the_self_invoice_is_due_on_each_such_bill_and_undecided_for_an_unrecorded_supplier():
    owed = [x for c in FIRM.clients for x in _owed(c)]
    assert owed
    for _, _d, v in owed:
        vendor = {"name": v.name, "gstin": v.gstin, "gst_registration_status": v.registration_recorded}
        assert rd.self_invoice_due({"is_reverse_charge": True}, vendor).due
    unrecorded = {"name": "x", "gstin": None, "gst_registration_status": None}
    assert rd.self_invoice_due({"is_reverse_charge": True}, unrecorded).undecided


def test_recording_a_status_draws_nothing_from_the_random_stream():
    """The status is set after every draw, so the documents, parties and dates are those of a fixture that records none."""
    import dataclasses
    for c in FIRM.clients:
        stripped = tuple(dataclasses.replace(v, registration_recorded=None) for v in c.vendors)
        again = fixture._recorded_where_reverse_charge_needs_it(dataclasses.replace(c, vendors=stripped), FY)
        assert again == c


# ── The seeder's bodies ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def run():
    spec = importlib.util.spec_from_file_location(
        "body_test", Path(__file__).resolve().parent / "test_every_body_the_seeder_sends_is_one_its_door_accepts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from main import app
    seeder = mod._seeder()
    rec = mod._Recorder(mod._doors(app))
    seeder.seed(rec, fixture.build(), add_to_existing=False)
    assert not rec.invalid, rec.invalid
    assert not rec.unmatched, rec.unmatched
    return rec


def test_every_vendor_body_carries_the_status_the_fixture_records(run):
    bodies = [b for m, p, b in run.requests if (m, p) == ("POST", "/api/vendors/")]
    vendors = [v for c in FIRM.clients for v in c.vendors]
    assert len(bodies) == len(vendors)
    for b, v in zip(bodies, vendors, strict=True):
        assert b["gst_registration_status"] == ("registered" if v.gstin else v.registration_recorded)


def test_a_self_invoice_is_issued_for_each_bill_after_it_is_received_and_before_the_clients_returns(run):
    reqs = run.requests
    issued = [(i, b) for i, (m, p, b) in enumerate(reqs) if (m, p) == ("POST", "/api/rcm-documents")]
    assert len(issued) == sum(len(_owed(c)) for c in FIRM.clients) > 0
    clients = [i for i, (m, p, _) in enumerate(reqs) if (m, p) == ("POST", "/api/clients")] + [len(reqs)]
    for i, b in issued:
        assert b["kind"] == "self_invoice" and b["purchase_bill_id"]
        assert set(b) == {"client_id", "kind", "purchase_bill_id"}, "the door decides the number and the date"
        start = max(c for c in clients if c < i)
        end = min(c for c in clients if c > i)
        received = [j for j, (m, p, _) in enumerate(reqs)
                    if start < j < i and m == "POST" and p == f"/api/purchase-bills/{b['purchase_bill_id']}/receive"]
        assert received, "the self-invoice was issued for a bill that was not received first"
        later_returns = [j for j, (m, p, _) in enumerate(reqs)
                         if start < j < end and p in ("/api/gst/gstr1/from-books", "/api/gst/gstr3b/from-books")]
        assert later_returns and all(j > i for j in later_returns)
