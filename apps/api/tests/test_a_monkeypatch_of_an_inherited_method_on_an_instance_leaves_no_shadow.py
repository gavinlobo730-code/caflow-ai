"""A monkeypatch of a method an instance only inherits is undone by deleting it, so a later patch of the CLASS still reaches the instance (POST-A-034).

THE COUPLING THIS CLOSES
    pytest records the old value of `monkeypatch.setattr(instance, "method", stub)` with `getattr` (a BOUND method, for a method the
    instance inherits) and puts it back with `setattr`, so the instance ends the test holding an attribute of its own that shadows the
    class's, for the rest of the process. A later test that patches the same method on the class is then ignored by that instance.
    A run that spread the tests one by one over four workers (`--dist load`) found two such tests failing with "DID NOT RAISE"; the
    suite's own distribution (`--dist loadfile`) had hidden it by keeping the files that conflict apart.

WHAT IS HELD
    * after the undo the instance has no attribute of its own for a method it inherits, and a patch of the class reaches it;
    * an attribute the instance DID have of its own is put back to its own value, not deleted;
    * a module attribute and a class attribute are undone as before.
"""
from __future__ import annotations

import types

import pytest


class _Service:
    def method(self):
        return "real"


def test_an_instance_patch_of_an_inherited_method_leaves_no_shadow_and_the_class_patch_then_reaches_it():
    instance = _Service()
    first = pytest.MonkeyPatch()
    first.setattr(instance, "method", lambda: "stub")
    assert instance.method() == "stub"
    first.undo()
    assert "method" not in vars(instance), "the instance kept an attribute of its own: a later patch of the class would be ignored"
    second = pytest.MonkeyPatch()
    second.setattr(_Service, "method", lambda self: "class stub")
    try:
        assert instance.method() == "class stub"
    finally:
        second.undo()
    assert instance.method() == "real"


def test_an_attribute_the_instance_had_of_its_own_is_put_back_not_deleted():
    instance = _Service()
    instance.method = lambda: "its own"
    mp = pytest.MonkeyPatch()
    mp.setattr(instance, "method", lambda: "stub")
    mp.undo()
    assert vars(instance)["method"]() == "its own"


def test_a_module_attribute_and_a_class_attribute_are_undone_as_before():
    module = types.ModuleType("m")
    module.value = 1
    mp = pytest.MonkeyPatch()
    mp.setattr(module, "value", 2)
    mp.setattr(_Service, "method", lambda self: "x")
    mp.undo()
    assert module.value == 1 and _Service().method() == "real"
