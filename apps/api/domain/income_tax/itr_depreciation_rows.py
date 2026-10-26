"""The rows of the return's depreciation schedules, READ FROM THE DEPARTMENT'S OWN SCHEMA (POST-A-070).

WHY THIS MODULE EXISTS

    Section 32 depreciation is charged on a BLOCK, and the return does not ask for a block: Schedule DPM and Schedule DOA are a
    fixed set of ROWS, each one a nature of asset at a rate ("Plant and machinery, 15 per cent", "Building, 10 per cent",
    "Furniture and fittings"). The block register (`income_tax_asset_blocks`, migration 357) names a block and its rate and says
    nothing about its nature, because §2(11) makes the nature half of a block's identity and a CA decides it. So a block cannot be
    placed on the return without one more fact, and that fact is which ROW it is. `income_tax_asset_blocks.itr_schedule_row`
    holds it (migration 552), and this module is the vocabulary it is checked against.

WHY THE VOCABULARY IS READ AND NOT TYPED

    Appendix I to the Income-tax Rules is a statutory table this repository does not write from memory (CLAUDE.md, "The other
    statutory data a human has to supply"), and a list of the return's rows typed here would be that table by another name. The
    rows are the Department's, committed under `schemas/`: a node of Schedule DPM or DOA that carries a `DepreciationDetail` is a
    row, its name carries the rate the Department printed on it (`Rate15`), and Land has no rate because the form allows none.
    Nothing below holds a rate that the schema does not.

    A row key is the path between the schedule and `DepreciationDetail`, e.g. `PlantMachinery.Rate15`. It is what the register
    stores, so a year whose form drops or adds a row is a change to a committed file and to nothing in this module.

WHAT IT DOES NOT DECIDE

    Which row a block belongs to. The register stores the CA's answer; this module says what answers exist and what rate each one
    implies, so that a block recorded at 15 per cent cannot be placed on a 10 per cent row. It does not read the rate off the key to
    DEPRECIATE anything: the block's own rate does that, and a row whose rate disagrees with the block is refused, not reconciled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from domain.income_tax import itr_schema

#: The two schedules a block's depreciation is declared in. DPM is plant and machinery; DOA is everything else. Schedule DEP
#: summarises them and is built from the rows, not read from the schema as a row set.
SCHEDULES: tuple[str, ...] = ("ScheduleDPM", "ScheduleDOA")

#: The forms whose Part A schedules this assembles. The three that carry a balance sheet and a profit and loss account.
FORMS: tuple[str, ...] = ("ITR-3", "ITR-5", "ITR-6")

#: The Department's own spelling of a rate on a row: `Rate15` is fifteen per cent.
_RATE = re.compile(r"^Rate(\d+)$")

#: A caption for each nature key the schema uses, in the words a CA reads the form in. The KEYS are the Department's; the words
#: are ours, and a key the schema adds that is not here is shown as its own name (a test names it, so it is noticed rather than
#: shown raw for ever).
NATURE_CAPTIONS: dict[str, str] = {
    "PlantMachinery": "Plant and machinery",
    "Land": "Land",
    "Building": "Building",
    "FurnitureFittings": "Furniture and fittings",
    "IntangibleAssets": "Intangible assets",
    "Ships": "Ships",
}


@dataclass(frozen=True)
class Row:
    """One row of Schedule DPM or DOA."""
    key: str                     # e.g. "PlantMachinery.Rate15"; what the register stores
    schedule: str                # "ScheduleDPM" | "ScheduleDOA"
    nature: str                  # the Department's nature key, e.g. "PlantMachinery"
    caption: str                 # "Plant and machinery, 15 per cent"
    rate_percent: Optional[int]  # None for Land, which the form gives no rate
    detail_path: str             # form-root-relative path of the row's DepreciationDetail object
    boxes: frozenset[str]        # the DepreciationDetail boxes this form has on this row

    def path(self, box: str) -> str:
        return f"{self.detail_path}.{box}"


def _node(defs: dict, value: dict) -> dict:
    ref = value.get("$ref")
    return defs.get(ref.split("/")[-1]) if ref else value


def form_root(form: str) -> str:
    """The schema's own root segment for a form: `ITR-3` is `ITR3`."""
    return form.replace("-", "")


def _form_node(form: str) -> tuple[dict, dict]:
    schema = itr_schema.load_schema(form)
    defs = itr_schema._definitions(schema)
    top = _node(defs, schema["properties"]["ITR"])
    return defs, _node(defs, top["properties"][form_root(form)])


@lru_cache(maxsize=None)
def rows_for(form: str) -> tuple[Row, ...]:
    """Every row of Schedule DPM and DOA that this form's schema has, in the schema's own order."""
    if form not in FORMS:
        raise ValueError(f"{form} carries no depreciation schedules this module assembles ({', '.join(FORMS)}).")
    defs, root = _form_node(form)
    out: list[Row] = []

    def detail_boxes(detail: dict) -> frozenset:
        return frozenset((_node(defs, detail).get("properties") or {}).keys())

    def walk(schedule: str, node: dict, trail: list[str]) -> None:
        for name, value in (node.get("properties") or {}).items():
            child = _node(defs, value)
            detail = (child.get("properties") or {}).get("DepreciationDetail")
            if detail is not None:
                parts = trail + [name]
                nature = parts[0]
                rate = None
                if len(parts) > 1:
                    m = _RATE.match(parts[1])
                    rate = int(m.group(1)) if m else None
                caption = NATURE_CAPTIONS.get(nature, nature)
                if rate is not None:
                    caption = f"{caption}, {rate} per cent"
                out.append(Row(
                    key=".".join(parts), schedule=schedule, nature=nature, caption=caption, rate_percent=rate,
                    detail_path=".".join([schedule] + parts + ["DepreciationDetail"]), boxes=detail_boxes(detail)))
            elif child.get("type") == "object":
                walk(schedule, child, trail + [name])

    for schedule in SCHEDULES:
        raw = root["properties"].get(schedule)
        if raw is None:
            continue
        block = _node(defs, raw)
        # A row hangs off a nature key (`PlantMachinery`), or is the nature itself (`Land`). Walk from the schedule's own children
        # so the first path segment is always the nature.
        for nature, value in (block.get("properties") or {}).items():
            child = _node(defs, value)
            detail = (child.get("properties") or {}).get("DepreciationDetail")
            if detail is not None:
                out.append(Row(
                    key=nature, schedule=schedule, nature=nature, caption=NATURE_CAPTIONS.get(nature, nature), rate_percent=None,
                    detail_path=f"{schedule}.{nature}.DepreciationDetail", boxes=detail_boxes(detail)))
            elif child.get("type") == "object":
                walk(schedule, child, [nature])
    return tuple(out)


def row_by_key(form: str, key: Optional[str]) -> Optional[Row]:
    for r in rows_for(form):
        if r.key == key:
            return r
    return None


def keys_for(form: str) -> tuple[str, ...]:
    return tuple(r.key for r in rows_for(form))


def vocabulary(form: str = "ITR-3") -> list[dict]:
    """The rows as a screen offers them: the key it stores, the words, and the rate the row implies (None for Land)."""
    return [{"key": r.key, "schedule": r.schedule, "caption": r.caption, "rate_percent": r.rate_percent}
            for r in rows_for(form)]


def disagreement(row: Row, block_rate_percent: int) -> Optional[str]:
    """A sentence if this row cannot hold a block of that rate, else None.

    A block IS a rate under §2(11), so a block recorded at 15 per cent placed on the 10 per cent row would be depreciated at 15 on
    a return that prints 10 beside it. Land carries no rate and takes no depreciation, so only a block recorded at nil can sit on it.
    """
    if row.rate_percent is None:
        if int(block_rate_percent) == 0:
            return None
        return (f"{row.caption} is not depreciated on the return, and this block is recorded at {block_rate_percent} per cent. "
                f"Choose the row of the block's nature at {block_rate_percent} per cent.")
    if row.rate_percent != int(block_rate_percent):
        return (f"{row.caption} is a {row.rate_percent} per cent row and this block is recorded at {block_rate_percent} per cent. "
                f"A block is a nature at one rate, so the row and the block's rate must agree.")
    return None
