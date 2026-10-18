"""The service catalogue and the HSN library each accept either spelling of goods and services (POST-A-107).

THE DEFECT
    `service_catalogue.kind` is `good` / `service` and `firm_hsn_library.hsn_type` (and `hsn_master.hsn_type`) is `goods` /
    `services`. Each door refused the other's word, and the two list filters silently IGNORED an unknown one (a `type=good` search
    returned goods and services alike). Each screen's dropdown supplies the right word, so it cost an API or importer caller a
    retry, never a wrong number; the retry was a 422 for the write and nothing at all for the filter.

WHAT IS HELD
    * `domain.gst.goods_or_services.kind_word` knows both vocabularies, any case, trimmed, and says None for anything else;
    * the catalogue accepts `goods` and stores `good`, the library accepts `service` and stores `services`: the STORED values
      are each door's own and no row is touched;
    * a word that is neither is still refused, by each door, with its own message;
    * the library list filter and the HSN search filter read either word (the old behaviour of an unrecognised word is to apply no
      filter at all).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from domain.gst.goods_or_services import catalogue_kind, kind_word
from models.firm_hsn_library import FirmHsnLibraryIn
from models.service_catalogue import ServiceCatalogueIn

API = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("word,expected", [
    ("good", "goods"), ("goods", "goods"), ("Goods", "goods"), (" GOOD ", "goods"),
    ("service", "services"), ("services", "services"), ("Services", "services"), ("\tSERVICE\n", "services"),
])
def test_both_vocabularies_are_known_in_any_case(word, expected):
    assert kind_word(word) == expected


@pytest.mark.parametrize("word", [None, "", "  ", "goodies", "service s", "both", 1, ["goods"], b"goods"])
def test_anything_else_is_none(word):
    assert kind_word(word) is None and catalogue_kind(word) is None


def test_the_catalogue_word_is_the_singular():
    assert catalogue_kind("goods") == "good" and catalogue_kind("Services") == "service"
    assert catalogue_kind("good") == "good" and catalogue_kind("service") == "service"


def _catalogue(**over):
    return ServiceCatalogueIn(**{"client_id": "C1", "name": "Widget", "kind": "good", **over})


def _library(**over):
    return FirmHsnLibraryIn(**{"hsn_code": "9983", "description": "Professional services", "hsn_type": "services", **over})


@pytest.mark.parametrize("given,stored", [("good", "good"), ("goods", "good"), ("Goods", "good"),
                                           ("service", "service"), ("services", "service"), (" SERVICES ", "service")])
def test_the_catalogue_accepts_either_word_and_stores_its_own(given, stored):
    assert _catalogue(kind=given).kind == stored


@pytest.mark.parametrize("given,stored", [("goods", "goods"), ("good", "goods"), ("GOODS", "goods"),
                                           ("services", "services"), ("service", "services"), (" Service ", "services")])
def test_the_library_accepts_either_word_and_stores_its_own(given, stored):
    assert _library(hsn_type=given).hsn_type == stored


def test_a_word_that_is_neither_is_refused_by_each_door_with_its_own_message():
    with pytest.raises(ValidationError) as catalogue:
        _catalogue(kind="both")
    assert "kind must be 'good' or 'service'" in str(catalogue.value)
    with pytest.raises(ValidationError) as library:
        _library(hsn_type="both")
    assert "hsn_type must be 'goods' or 'services'" in str(library.value)


def test_the_filters_read_either_word_and_not_a_list_of_two_spellings():
    """Source-level: neither filter tests membership of ("goods", "services") any more, which is what ignored `good`."""
    for rel in ("routers/hsn.py", "routers/firm_hsn_library.py"):
        tree = ast.parse((API / rel).read_text(encoding="utf-8"))
        offending = [n.lineno for n in ast.walk(tree)
                     if isinstance(n, ast.Compare) and any(isinstance(op, ast.In) for op in n.ops)
                     and any(isinstance(c, ast.Tuple) and [e.value for e in c.elts if isinstance(e, ast.Constant)] == ["goods", "services"]
                             for c in n.comparators)]
        assert offending == [], f"{rel}:{offending} compares a type with the literal pair again"
        assert "kind_word(" in (API / rel).read_text(encoding="utf-8")


def test_the_library_filter_applies_a_filter_for_the_singular_word(monkeypatch):
    import routers.firm_hsn_library as mod
    rows = [{"firm_id": "F1", "hsn_code": "1001", "description": "Wheat", "hsn_type": "goods", "is_active": True},
            {"firm_id": "F1", "hsn_code": "9983", "description": "Advice", "hsn_type": "services", "is_active": True}]
    monkeypatch.setattr(mod, "_USE_MOCK", True)
    monkeypatch.setattr(mod, "MOCK_LIBRARY", rows)
    caller = {"firm_id": "F1", "role": "Partner", "id": "u1"}
    for word, expected in (("good", ["1001"]), ("goods", ["1001"]), ("Service", ["9983"]), ("services", ["9983"])):
        out = mod.list_library(q="", hsn_type=word, include_archived=False, limit=50, current_user=caller)
        assert [r["hsn_code"] for r in out["data"]] == expected, word
    unfiltered = mod.list_library(q="", hsn_type=None, include_archived=False, limit=50, current_user=caller)
    assert len(unfiltered["data"]) == 2
