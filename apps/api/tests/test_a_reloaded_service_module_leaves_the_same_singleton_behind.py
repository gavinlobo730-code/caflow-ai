"""A test module that reloads a service module must not change what the next module's patches reach.

WHAT WAS WRONG
    `test_batch3_1_hardening.py::test_missing_coa_leaves_invoice_retryable_draft` patches
    `journal_for_sales_invoice` on the `phase2_journal_service` singleton it imported at collection and then
    calls `issue_invoice`, which imports the singleton INSIDE its body. Four older modules reload
    `services.phase2_journal_service` (to force non-mock mode, then to put `_USE_MOCK` back), and a reload builds a
    new singleton. Run after any of them in the same process, the patch landed on an object the router no longer
    used and the test saw `success: True`. The alphabetical order every serial run has hid it; it surfaced the day
    the backend job ran in parallel, where which modules share a worker differs from run to run (engineering-21),
    on a tree where nothing had changed. It reproduced on a clean `main`.

THE RULE
    A reload may leave the module's flag restored; it may not leave a different object behind. The autouse fixture in
    `tests/conftest.py` keeps the first singleton of each reloaded module for the whole process.

HOW THIS TESTS IT
    The failure is an ORDER between two modules, so the test runs that order in a fresh interpreter, once per
    polluting module, and asks for a pass. A test that imported both in this process could not tell: this process
    already holds the fixture's protection.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]

POLLUTERS = [
    "tests/test_phase2_journal_key_resolution.py",
    "tests/test_phase2_stabilization.py",
    "tests/test_the_employer_contribution_is_its_own_expense_head.py",
    "tests/test_compensation_cess_reaches_the_document_and_the_ledger.py",
]
VICTIM = "tests/test_batch3_1_hardening.py"


@pytest.mark.parametrize("polluter", POLLUTERS)
def test_a_module_that_runs_after_a_reloading_one_still_sees_its_own_patch(polluter):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", polluter, VICTIM],
        cwd=API, capture_output=True, text=True, timeout=170)
    assert result.returncode == 0, (
        f"{VICTIM} fails when it runs after {polluter}: a reload left a different singleton behind.\n"
        + result.stdout[-1800:])


def test_the_polluters_are_still_the_modules_that_reload_the_journal_service():
    """The list above is the set that reloads it today. A fifth reloader would be unprotected by the case list but
    protected by the fixture; this only keeps the list honest, so the day one is removed or added it is looked at."""
    reloaders = sorted(
        str(p.relative_to(API)).replace("\\", "/")
        for p in (API / "tests").glob("test_*.py")
        if "reload(" in p.read_text(encoding="utf-8")
        and "phase2_journal_service" in p.read_text(encoding="utf-8"))
    assert set(POLLUTERS) <= set(reloaders), (
        "a module in POLLUTERS no longer reloads the journal service: " + str(set(POLLUTERS) - set(reloaders)))
