"""A module first imported while a test had SUPABASE_URL set is back in mock mode for the next test (ledger POST-A-578).

WHAT WAS WRONG
    About ninety modules decide mock mode once, at import (`_USE_MOCK = not os.environ.get("SUPABASE_URL")`). A test that sets the URL
    and happens to be the first in its worker to import one of them left it out of mock mode for the rest of the worker, and whichever
    file came next failed for want of a database. The whole suite passed in its usual order; a run of a subset did not (eight tests in
    two files on 27-11-2026, each passing alone).

WHAT THIS HOLDS
    The two tests below run in this order in one worker (one file, the order they are written in). The first imports a module, written
    for the purpose, while the URL is set, and sees it out of mock mode: the capture is real. The second, which sets nothing, sees it
    back in mock mode, because `tests/conftest.py` puts a newly imported module back to what the session started with before every
    test. With that fixture taken out the second test fails. A third shows a flag a test sets on purpose is left alone while it runs.
"""
from __future__ import annotations

import importlib
import sys
import textwrap

import pytest

from tests import conftest

NAME = "a_module_that_reads_the_database_url_at_import_578"


@pytest.fixture(scope="module")
def where_the_module_lives(tmp_path_factory):
    folder = tmp_path_factory.mktemp("captured_at_import")
    (folder / f"{NAME}.py").write_text(textwrap.dedent('''
        import os
        _USE_MOCK = not os.environ.get("SUPABASE_URL")
    '''), encoding="utf-8")
    sys.path.insert(0, str(folder))
    yield folder
    sys.path.remove(str(folder))
    sys.modules.pop(NAME, None)
    conftest._modules_already_looked_at.discard(NAME)


@pytest.mark.skipif(not conftest._MOCK_MODE_AT_SESSION_START, reason="this session started with a database configured")
def test_first_a_module_imported_while_the_url_is_set_is_out_of_mock_mode(monkeypatch, where_the_module_lives):
    monkeypatch.setenv("SUPABASE_URL", "http://another-tests-own-purpose.invalid")
    module = importlib.import_module(NAME)
    assert module._USE_MOCK is False, "the module did not capture the URL at import: this test no longer reproduces the capture"


@pytest.mark.skipif(not conftest._MOCK_MODE_AT_SESSION_START, reason="this session started with a database configured")
def test_then_the_next_test_finds_it_back_in_mock_mode(where_the_module_lives):
    module = sys.modules.get(NAME)
    assert module is not None, "the first test of this file did not run before this one"
    assert module._USE_MOCK is True, "a module imported under another test's SUPABASE_URL stayed out of mock mode"


@pytest.mark.skipif(not conftest._MOCK_MODE_AT_SESSION_START, reason="this session started with a database configured")
def test_a_flag_a_test_sets_on_purpose_is_left_alone_while_it_runs(monkeypatch, where_the_module_lives):
    module = importlib.import_module(NAME)
    monkeypatch.setattr(module, "_USE_MOCK", False)
    assert conftest._put_newly_imported_modules_back_in_the_sessions_mock_mode() == []
    assert module._USE_MOCK is False
