"""What is right for one worker is held to one worker (POST-A-092, the last limit of its stock side).

THE PREMISE. Several pieces of this API keep their state in the memory of the process that serves the request: the claim that stops two clicks
both completing one document's stock, the windows of every rate limiter, the count of guesses at the year-lock PIN. Each says so where it is
written, in the same words: right for the one worker the API runs as, wrong for several. With two workers the second click lands on the other
worker, whose memory holds no claim, and both write the missing stock line; a limit of N a minute becomes N a minute per worker.

That was a sentence in four docstrings and a line on the ledger ("the in-process lock is right for one worker and not for several"). A sentence is
not held: the day somebody raises `--workers` to make the server faster, nothing fails, and the first sign is a document with its stock recorded
twice. This file is the hold. It reads the command the image starts the API with and fails if it asks for more than one worker, and it reads each
named piece of state so that a state which has gone (moved to the database, which is the way out) leaves this list in the same change.

WHAT TO DO WHEN THIS FAILS. Either keep one worker, or move every state named here somewhere all workers share (a row claimed in the database,
the way a payroll run is claimed; a counter in the database), delete its line, and only then raise the number. A worker count read from the
environment is refused too: the premise must be readable from the repository.

WHAT IT DOES NOT SEE: state kept in memory that nobody listed here, and a second INSTANCE of the service (Render's instance count is a dashboard
setting; `render.yaml` names none, which means one, and that is asserted below as far as the file can say it).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]

#: {(file, module-level name): what goes wrong with a second worker}
ONE_WORKER_STATE: dict[tuple[str, str], str] = {
    ("services/stock_effect_retry_service.py", "_in_flight"):
        "the claim on a document whose stock is being completed: a second worker holds no claim, so two clicks could both write the missing line.",
    ("middleware/rate_limit.py", "_windows"):
        "the windows of every rate limit on a route that reaches a model or a public door: each worker would count its own, so N a minute becomes N per worker.",
    ("services/year_lock_service.py", "_actor_attempts"):
        "the count of one person's guesses at the year-lock PIN: each worker would allow the full number.",
    ("services/year_lock_service.py", "_firm_attempts"):
        "the count of a firm's guesses at the year-lock PIN: each worker would allow the full number.",
}


def _start_command(dockerfile: str) -> list[str]:
    """The JSON form of the last CMD of a Dockerfile, which is the command the container runs."""
    commands = re.findall(r"^CMD\s+(\[.*\])\s*$", dockerfile, flags=re.M)
    assert commands, "the Dockerfile has no CMD in the JSON form this test reads"
    return json.loads(commands[-1])


def workers_asked_for(command: list[str]) -> str | None:
    """What the command asks for after `--workers` (or `-w`, or `--workers=N`), as written; None when it does not say."""
    for i, part in enumerate(command):
        if part in ("--workers", "-w") and i + 1 < len(command):
            return command[i + 1]
        if part.startswith("--workers="):
            return part.split("=", 1)[1]
    return None


def test_the_api_is_started_with_exactly_one_worker_and_says_so_in_the_repository():
    command = _start_command((API / "Dockerfile").read_text(encoding="utf-8"))
    assert command[0] == "gunicorn", command
    asked = workers_asked_for(command)
    assert asked == "1", (
        f"the API is started with --workers {asked!r}. The state in ONE_WORKER_STATE lives in one process's memory and is wrong for several: "
        "move each to the database and take it off the list before raising the number (and a number read from the environment cannot be held here).")


def test_the_deployment_file_names_no_second_instance_and_no_other_start_command():
    manifest = (REPO / "render.yaml").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(startCommand|dockerCommand)\s*:", manifest, flags=re.M), "render.yaml overrides the image's start command, which this test reads"
    counts = re.findall(r"^\s*numInstances\s*:\s*(\d+)", manifest, flags=re.M)
    assert all(n == "1" for n in counts), f"render.yaml asks for {counts} instances; two instances are two processes, the same as two workers"
    assert not re.search(r"^\s*-?\s*key\s*:\s*WEB_CONCURRENCY\b", manifest, flags=re.M), "WEB_CONCURRENCY would set a worker count outside the command this test reads"


@pytest.mark.parametrize("where", sorted(ONE_WORKER_STATE), ids=lambda w: f"{w[0]}::{w[1]}")
def test_each_named_state_is_still_kept_in_the_process(where):
    """A state that has moved to the database must leave the list, or the list keeps demanding one worker for a reason that has gone."""
    file, name = where
    tree = ast.parse((API / file).read_text(encoding="utf-8"))
    kept = {t.id for st in tree.body if isinstance(st, (ast.Assign, ast.AnnAssign))
            for t in (st.targets if isinstance(st, ast.Assign) else [st.target]) if isinstance(t, ast.Name)}
    assert name in kept, f"{file} no longer keeps `{name}` at module level: take the line off ONE_WORKER_STATE (and say where the state lives now)"
    assert len(ONE_WORKER_STATE[where].split()) >= 8, "say in words what goes wrong with a second worker"


# ── the reader can fail ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_reader_sees_a_second_worker_however_it_is_written():
    assert workers_asked_for(["gunicorn", "main:app", "--workers", "1"]) == "1"
    assert workers_asked_for(["gunicorn", "main:app", "--workers", "2"]) == "2"
    assert workers_asked_for(["gunicorn", "main:app", "-w", "4"]) == "4"
    assert workers_asked_for(["gunicorn", "main:app", "--workers=3"]) == "3"
    assert workers_asked_for(["gunicorn", "main:app", "--workers", "${WEB_CONCURRENCY}"]) == "${WEB_CONCURRENCY}"
    assert workers_asked_for(["gunicorn", "main:app"]) is None      # gunicorn's default is 1, but a default nobody wrote is not a statement


def test_the_reader_takes_the_last_command_of_the_image():
    text = 'CMD ["gunicorn", "main:app", "--workers", "3"]\nRUN true\nCMD ["gunicorn", "main:app", "--workers", "1"]\n'
    assert workers_asked_for(_start_command(text)) == "1"
