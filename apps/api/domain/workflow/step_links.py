"""How the steps of a saved workflow are wired to one another.

A workflow runs by following links: the engine starts at the first step that is
not the trigger and goes to `next_step_id` until a step has none, and a branch
goes to `true_branch_step_id` or `false_branch_step_id`. A link names a step by
its id, and a step has no id until it is stored.

THAT IS THE PROBLEM THIS MODULE ENDS. A template saved through the API arrives as
an ordered list of steps, and the caller cannot write a link to a step that does
not exist yet, so every step was stored with `next_step_id = NULL`. The engine
reads a missing link as "the flow ends here", so a template of three steps ran
the first, completed, and reported success. Every multi-step test in the suite
wired its links by hand, which is why nothing noticed.

THE RULE. The server decides the ids, then the links:

  1. Every step gets an id (the one it carries, if a direct caller wrote one,
     else a new one) and its position in the list as `step_order`.
  2. A link that names a step which is not in THIS save is removed. It cannot
     be right: through the API it is an id from before this save (a template
     read back and sent again carries the old steps' ids, and those steps are
     replaced), and a link out of the template would send the run to nothing.
  3. If, after that, no step is wired and no step is a branch or a condition,
     the list is a straight line and each step is linked to the next, in order.
     The last has no link, which is how a flow ends.

A TEMPLATE WITH A BRANCH IS NOT CHAINED. A branch chooses between two steps, and
which two is a decision the list order cannot express: linking "the step after
the branch" would invent a path the author never drew. Such a template is stored
with the links it was given (none, through the API) until the API can name a
step before it exists. That is the next piece of work on this feature, and it is
better to store a branch that ends the flow than one that quietly goes where
nobody said.

Nothing here reads a database; the repository calls `prepare` once per save and
makes ONE insert of what it returns, so a template's steps are stored together
or not at all.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Iterable

#: The three columns that hold a step's successor.
LINK_FIELDS = ("next_step_id", "true_branch_step_id", "false_branch_step_id")

#: Step types that choose between two successors.
BRANCHING_TYPES = frozenset({"branch", "condition"})

#: The columns of `workflow_steps` a saved step carries (migration 157).
COLUMNS = ("step_order", "step_type", "name", "description", "config", *LINK_FIELDS)


def _new_id() -> str:
    return str(uuid.uuid4())


def prepare(steps: Iterable[dict], new_id: Callable[[], str] = _new_id) -> list[dict]:
    """The rows to store for an ordered list of steps: ids, order and links.

    `steps` are dicts as `WorkflowStepIn.model_dump()` makes them. The result has
    one row per step, in the same order, each with `id`, `step_order` (the list
    position, whatever the caller wrote) and the eight columns in COLUMNS.
    """
    rows: list[dict[str, Any]] = []
    for position, step in enumerate(steps):
        row = {column: step.get(column) for column in COLUMNS}
        # `config` is NOT NULL (migration 157); an unset one is an empty object.
        row["config"] = step.get("config") or {}
        row["id"] = step.get("id") or new_id()
        row["step_order"] = position
        rows.append(row)

    saved_ids = {row["id"] for row in rows}
    for row in rows:
        for field in LINK_FIELDS:
            if row[field] not in saved_ids:
                row[field] = None

    wired = any(row[field] for row in rows for field in LINK_FIELDS)
    branching = any(row["step_type"] in BRANCHING_TYPES for row in rows)
    if not wired and not branching:
        for here, after in zip(rows, rows[1:], strict=False):
            here["next_step_id"] = after["id"]
    return rows
