"""The coming-soon register (docs/open-items/coming-soon.md) is well formed, and what it says about the code is true.

WHY THIS EXISTS

    The product tells a person in a dozen places that something is planned, coming, not built or not switched
    on, and until the register there was nowhere to see them together: the Scheduled Reports screen promised
    an email nothing sent, the Pay Now button opened a dead page, two walk-throughs described a file that
    already exists as future work, and the pricing page offered a trial nothing implements. Each was found by
    reading one screen. The register is ONE file a person can open: one row per statement, with where it is,
    its exact words, what gates it, who has to act and which open-items ledger line holds the work.

    A register nobody keeps true is worse than none, so this test holds the rows to the code. It reads the
    register to the code ONLY, and that is deliberate:

      * every row is one well-formed line with a unique id, and the file's "Highest id issued" line is not
        below the highest id (a deleted row's number is never handed out again);
      * every ledger id a row cites exists in the six section files, so closing a ledger item forces a look
        at the rows that cite it; a row with NO ledger line is on a frozen list, and the list can only shrink;
      * every path a row names is a file, and the words of a `shown` row are still in one of them, so a
        feature that ships (or a sentence that is reworded) cannot leave a stale row behind;
      * a `switch` row's variable names exist in render.yaml or the API's source, a `walkthrough` row's flow
        is one of services/filing_demo's, and a `marketing` row's claim ids are commitments or unproven claims
        in the marketing claims ledger;
      * a row about FILING (a walk-through, anything gated by a registration, anything in the filing-posture
        or filing-demo files) uses none of `domain.filing_posture.FORBIDDEN_REGISTRATION_CLAIMS`, and says
        "planned" where a registration gates it (decision D17: nothing has been applied for).

WHAT IT DOES NOT DO, AND WHY THAT IS THE NEXT CHANGE AND NOT THIS ONE

    It does not find a promise that has no row. Nothing scans apps/web, apps/marketing or apps/api for new
    "not yet", "planned", "coming soon" or "switched off" wording, so a sentence added without a row passes.
    That scan is a vocabulary (the claims ledger's `_marketing_vocabulary.py` is its precedent: a vocabulary is
    a spelling, and it states its own limits), it fails every branch that adds such wording, and so it is built
    after the register exists and other work has had a chance to add its rows. Until then the register's header
    asks the person who adds wording to add the row in the same commit.

    It does not judge whether a wording is a good one, whether a row is complete, or whether a switch is on in
    production: that is not readable from the repository, and no row says it.

    A "Safe: no" row is a statement that the words, as they are today, overstate or mislead. The test requires
    the reason; it does not require the fix.

WRITE THE RULE, NOT A SPELLING OF IT

    Every check below is a function of (rows, the tree). The verify-clause tests at the bottom run the same
    functions over a synthetic tree and a synthetic register, so each rule is shown to FAIL on the mistake it
    exists for rather than assumed to.
"""
from __future__ import annotations

import ast
import datetime
import functools
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pytest

from domain.filing_posture import FORBIDDEN_REGISTRATION_CLAIMS
from tests import _marketing_claims as marketing_claims

REPO = Path(__file__).resolve().parents[3]
API = REPO / "apps" / "api"
LEDGER_DIR = REPO / "docs" / "open-items"
REGISTER = LEDGER_DIR / "coming-soon.md"

KINDS = ("promise", "switch", "walkthrough", "marketing")
STATUSES = ("shown", "queued")
GATES = (
    "engineering", "owner-decision", "external-registration", "external-account", "counsel", "staffing",
    "statute-reading", "human-act-on-portal", "owner-attestation",
)
FIELD_ORDER = ("Where", "Says", "Safe", "Owner", "Ledger", "Switch", "Flow", "Claims", "Added")
REQUIRED_FIELDS = ("Where", "Says", "Safe", "Owner", "Ledger", "Added")

#: Rows that cite no ledger line because none exists yet. Frozen, and asserted as an EQUALITY in both
#: directions: a row that gains a ledger line must leave this set in the same commit (a `none` row that is
#: not here fails), and an id left here after its row has a ledger line fails too. Empty is the goal.
NO_LEDGER_LINE: set[str] = set()

#: The files whose wording is about filing, a registration or regulatory standing, wherever a row names them.
FILING_FILES = (
    "apps/api/domain/filing_posture.py", "apps/web/lib/filing/posture.ts",
    "apps/web/components/FilingDemoWizard.tsx", "apps/api/services/filing_demo/",
)

ROW_START = "- **COMING-"
HEAD = re.compile(
    r"^- \*\*(?P<id>COMING-\d{3})\*\* · `(?P<kind>[a-z]+)` · `(?P<status>[a-z]+)` · "
    r"gate:(?P<gates>[a-z\-]+(?:,[a-z\-]+)*) — \*\*(?P<title>[^*]+?\.)\*\* (?P<rest>.+)$"
)
FIELD_SPLIT = re.compile(r" — (?=_(?:" + "|".join(FIELD_ORDER) + r"):_ )")
FIELD = re.compile(r"^_(?P<name>[A-Za-z]+):_ (?P<value>.+)$", re.S)
HIGH_WATER = re.compile(r"\*\*Highest id issued: COMING-(\d{3})\*\*")
LEDGER_ID = r"(?:PRE|POST)-[ABC]-\d{3}"
ENV_NAME = r"[A-Z][A-Z0-9_]*"

Problem = tuple[str, str]  # (category, message)


@dataclass
class Row:
    line: int
    id: str
    kind: str
    status: str
    gates: tuple[str, ...]
    title: str
    detail: str
    fields: dict[str, str] = field(default_factory=dict)
    where: tuple[str, ...] = ()
    says: tuple[str, ...] = ()
    ledger: tuple[str, ...] = ()
    switch: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return " ".join([self.title, self.detail, *self.says])

    def is_about_filing(self) -> bool:
        return (
            self.kind == "walkthrough"
            or "external-registration" in self.gates
            or any(w.startswith(FILING_FILES) for w in self.where)
        )


@dataclass
class Tree:
    """Everything a check reads outside the register, so the same checks run over a synthetic tree."""

    root: Path
    ledger_ids: set[str]
    flows: set[str]
    claim_ids: set[str]
    env_known: Callable[[str], bool]
    no_ledger_line: set[str] = field(default_factory=lambda: set(NO_LEDGER_LINE))


# ── parsing ──────────────────────────────────────────────────────────────────

class _Report:
    """Collects the format problems of ONE row, each named with the row's id and line."""

    def __init__(self, sink: list[Problem], rid: str, line: int):
        self.sink, self.rid, self.line = sink, rid, line

    def __call__(self, message: str) -> None:
        self.sink.append(("format", f"{self.rid} (line {self.line}): {message}"))


def _only(tokens_rx: str, value: str, sep: str = ", ") -> Optional[list[str]]:
    """Split `value` on `sep`; every part must match `tokens_rx` exactly, else None."""
    parts = value.split(sep)
    return parts if all(re.fullmatch(tokens_rx, p) for p in parts) else None


def parse(text: str) -> tuple[list[Row], list[Problem], Optional[int]]:
    """(rows, format problems, the "Highest id issued" number or None)."""
    rows: list[Row] = []
    problems: list[Problem] = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("- "):
            continue
        row = _parse_row(n, line, problems)
        if row is not None:
            rows.append(row)
    hw = HIGH_WATER.search(text)
    return rows, problems, int(hw[1]) if hw else None


def _parse_row(n: int, line: str, problems: list[Problem]) -> Optional[Row]:
    if not line.startswith(ROW_START):
        problems.append(("format", f"line {n} is a bullet that is not a row: {line[:70]}"))
        return None
    m = HEAD.match(line)
    if not m:
        problems.append(("format", f"line {n} does not match `- **COMING-NNN** · `kind` · `status` · gate:… — **Title.** …`: {line[:90]}"))
        return None
    bad = _Report(problems, m["id"], n)
    if m["kind"] not in KINDS:
        bad(f"kind `{m['kind']}` is not one of {KINDS}")
    if m["status"] not in STATUSES:
        bad(f"status `{m['status']}` is not one of {STATUSES}")
    gates = tuple(m["gates"].split(","))
    for g in (g for g in gates if g not in GATES):
        bad(f"gate `{g}` is not one of {GATES}")
    parts = FIELD_SPLIT.split(m["rest"])
    row = Row(n, m["id"], m["kind"], m["status"], gates, m["title"], parts[0])
    _split_fields(row, parts[1:], bad)
    _read_values(row, bad)
    _read_kind_rules(row, bad)
    return row


def _split_fields(row: Row, raw_fields: list[str], bad: _Report) -> None:
    order = []
    for raw in raw_fields:
        fm = FIELD.match(raw)
        if not fm:
            bad(f"cannot read the field `{raw[:40]}`")
            continue
        name = fm["name"]
        if name in row.fields:
            bad(f"field {name} appears twice")
        row.fields[name] = fm["value"].strip()
        order.append(name)
    if order != sorted(order, key=FIELD_ORDER.index):
        bad(f"fields are out of order: {order} (the order is {FIELD_ORDER})")
    for name in (n for n in REQUIRED_FIELDS if n not in row.fields):
        bad(f"field _{name}:_ is missing")


def _read_values(row: Row, bad: _Report) -> None:
    """The shape of each field's value (the kind-specific rules are `_read_kind_rules`)."""
    f = row.fields
    if "Where" in f:
        row.where = tuple(re.findall(r"`([^`]+)`", f["Where"]))
        if not row.where or re.sub(r"`[^`]+`|, ", "", f["Where"]):
            bad("_Where:_ must be backtick-quoted paths separated by commas")
    if "Says" in f:
        row.says = tuple(q.strip() for q in re.findall(r"«([^»]+)»", f["Says"]))
        if not row.says or re.sub(r"«[^»]+»|\s", "", f["Says"]):
            bad("_Says:_ must be one or more «exact words»")
    if "Safe" in f and not (f["Safe"] == "yes" or re.fullmatch(r"no \(.+\)", f["Safe"])):
        bad("_Safe:_ is `yes` or `no (the reason)`")
    if "Owner" in f and f["Owner"] not in ("A", "B", "C"):
        bad("_Owner:_ is A, B or C (the open-items buckets)")
    if "Ledger" in f and f["Ledger"] != "none":
        ids = _only(LEDGER_ID, f["Ledger"])
        row.ledger = tuple(ids or ())
        if ids is None:
            bad("_Ledger:_ is `none` or open-items ids separated by commas")
    if "Switch" in f:
        names = _only(ENV_NAME + r"|dashboard:[A-Za-z][A-Za-z0-9 _-]*", f["Switch"])
        row.switch = tuple(names or ())
        if names is None:
            bad("_Switch:_ is environment variable names or `dashboard:Name`")
    if "Flow" in f and not re.fullmatch(r"[a-z0-9_]+", f["Flow"]):
        bad("_Flow:_ is one flow key")
    if "Claims" in f:
        ids = _only(r"[a-z][a-z0-9\-]*", f["Claims"])
        row.claims = tuple(ids or ())
        if ids is None:
            bad("_Claims:_ is marketing claim ids separated by commas")
    if "Added" in f:
        try:
            datetime.date.fromisoformat(f["Added"])
        except ValueError:
            bad("_Added:_ is an ISO date")


def _read_kind_rules(row: Row, bad: _Report) -> None:
    """The fields a kind needs, and the ones only a kind may carry."""
    f = row.fields
    if row.kind == "switch" and "Switch" not in f:
        bad("a `switch` row names its switch (_Switch:_)")
    if row.kind == "walkthrough" and "Flow" not in f:
        bad("a `walkthrough` row names its flow (_Flow:_)")
    if "Flow" in f and row.kind != "walkthrough":
        bad("only a `walkthrough` row carries _Flow:_")
    if "Claims" in f and row.kind != "marketing":
        bad("only a `marketing` row carries _Claims:_")


# ── the checks ───────────────────────────────────────────────────────────────

def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def _text_variants(raw: str) -> tuple[str, str]:
    """A file's text as a person reads it: whitespace squashed, and again with adjacent string literals
    (`"a "` newline `"b"`, or `"a " +` newline `"b"`) joined, because a long sentence is written in pieces."""
    joined = re.sub(r"""(["'`])\s*\+?\s*\n\s*\1""", "", raw)
    return _squash(raw), _squash(joined)


@functools.lru_cache(maxsize=None)
def _file_variants(path: str) -> tuple[str, str]:
    return _text_variants(Path(path).read_text(encoding="utf-8", errors="ignore"))


def check(rows: list[Row], high_water: Optional[int], tree: Tree) -> list[Problem]:
    out = _check_ids(rows, high_water)
    flows_used: dict[str, str] = {}
    for r in rows:
        out += _check_ledger(r, tree)
        out += _check_files(r, tree)
        out += _check_names(r, tree, flows_used)
        out += _check_posture(r)
    # The frozen set may not outlive its rows.
    for gone in sorted(tree.no_ledger_line - {r.id for r in rows}):
        out.append(("ledger-none", f"{gone} is on NO_LEDGER_LINE but has no row: take it off"))
    return out


def _check_ids(rows: list[Row], high_water: Optional[int]) -> list[Problem]:
    out: list[Problem] = []
    seen: dict[str, int] = {}
    for r in rows:
        if r.id in seen:
            out.append(("duplicate", f"{r.id} is on line {seen[r.id]} and line {r.line}"))
        seen[r.id] = r.line
    if high_water is None:
        out.append(("high-water", "the register has no `**Highest id issued: COMING-NNN**` line"))
    elif rows and high_water < max(int(r.id[-3:]) for r in rows):
        out.append(("high-water", f"`Highest id issued` is COMING-{high_water:03d} but a row has a higher id"))
    return out


def _check_ledger(r: Row, tree: Tree) -> list[Problem]:
    out: list[Problem] = []
    for lid in (i for i in r.ledger if i not in tree.ledger_ids):
        out.append(("ledger", f"{r.id} cites {lid}, which is not in any section file (closed? look at this row)"))
    if "Ledger" in r.fields and not r.ledger and r.id not in tree.no_ledger_line:
        out.append(("ledger-none", f"{r.id} has no ledger line and is not on the frozen list: add the ledger line, or say here why not"))
    if r.ledger and r.id in tree.no_ledger_line:
        out.append(("ledger-none", f"{r.id} now cites a ledger line: take it off NO_LEDGER_LINE"))
    return out


def _check_files(r: Row, tree: Tree) -> list[Problem]:
    out: list[Problem] = []
    texts: list[tuple[str, str]] = []
    for w in r.where:
        p = tree.root / w
        if p.is_file():
            texts.append(_file_variants(str(p)))
        else:
            out.append(("where", f"{r.id}: {w} is not a file"))
    if r.status == "shown" and texts:
        for q in r.says:
            if not any(_squash(q) in variant for pair in texts for variant in pair):
                out.append(("stale", f"{r.id}: «{q[:70]}» is no longer in {', '.join(r.where)}: if the feature shipped or the sentence changed, edit or delete the row in the same commit"))
    return out


def _check_names(r: Row, tree: Tree, flows_used: dict[str, str]) -> list[Problem]:
    out: list[Problem] = []
    for name in (n for n in r.switch if not n.startswith("dashboard:") and not tree.env_known(n)):
        out.append(("switch", f"{r.id}: {name} is read by nothing in render.yaml or apps/api"))
    if r.kind == "walkthrough" and "Flow" in r.fields:
        flow = r.fields["Flow"]
        if flow not in tree.flows:
            out.append(("flow", f"{r.id}: {flow} is not a key of services.filing_demo.FLOWS"))
        if flow in flows_used:
            out.append(("flow", f"{r.id} and {flows_used[flow]} are both the {flow} walk-through"))
        flows_used[flow] = r.id
    for cid in (c for c in r.claims if c not in tree.claim_ids):
        out.append(("claims", f"{r.id}: {cid} is not a commitment or unproven claim in tests/_marketing_claims.py"))
    return out


def _check_posture(r: Row) -> list[Problem]:
    """D17: nothing about filing, a registration or regulatory standing is claimed that this product lacks."""
    if not r.is_about_filing():
        return []
    low = r.text.lower()
    out = [("posture", f"{r.id} is about filing and says {p!r}: no registration has been sought (D17), so say what is PLANNED and what gates it")
           for p in FORBIDDEN_REGISTRATION_CLAIMS if p in low]
    if "external-registration" in r.gates and "planned" not in low:
        out.append(("posture", f"{r.id} is gated by a registration and does not say the filing is planned"))
    return out


# ── the real tree ────────────────────────────────────────────────────────────

def _ledger_ids() -> set[str]:
    ids: set[str] = set()
    for p in [*LEDGER_DIR.glob("pre-demo-*.md"), *LEDGER_DIR.glob("post-demo-*.md")]:
        ids.update(re.findall(rf"^- \*\*({LEDGER_ID})\*\*", p.read_text(encoding="utf-8"), re.M))
    return ids


def _flow_keys() -> set[str]:
    """The keys of FLOWS, read from the source (importing it would import every flow module)."""
    src = (API / "services" / "filing_demo" / "__init__.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "FLOWS" for t in targets) and isinstance(node.value, ast.Dict):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError("services/filing_demo/__init__.py no longer assigns FLOWS as a dict literal")


_SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}


@functools.lru_cache(maxsize=None)
def _api_source() -> str:
    """Every non-test Python file under apps/api, as one string (read once, and only if a name is not in render.yaml)."""
    chunks = []
    for dirpath, dirnames, filenames in os.walk(API):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and d != "tests"]
        chunks += [(Path(dirpath) / fn).read_text(encoding="utf-8", errors="ignore") for fn in filenames if fn.endswith(".py")]
    return "\n".join(chunks)


def _env_known(name: str) -> bool:
    return name in (REPO / "render.yaml").read_text(encoding="utf-8") or name in _api_source()


def _real_tree() -> Tree:
    return Tree(
        root=REPO,
        ledger_ids=_ledger_ids(),
        flows=_flow_keys(),
        claim_ids={c.id for c in marketing_claims.CLAIMS if c.status in (marketing_claims.COMMITMENT, marketing_claims.UNPROVEN)},
        env_known=_env_known,
    )


@pytest.fixture(scope="module")
def real():
    rows, fmt, hw = parse(REGISTER.read_text(encoding="utf-8"))
    return rows, fmt, hw, check(rows, hw, _real_tree())


def _of(problems: list[Problem], *cats: str) -> list[str]:
    return [m for c, m in problems if c in cats]


def test_the_register_exists_and_is_read():
    rows, _fmt, hw = parse(REGISTER.read_text(encoding="utf-8"))
    # A floor, so a parser that finds nothing cannot pass every check below.
    assert len(rows) >= 25, f"only {len(rows)} rows parsed from {REGISTER}: the parser or the file is broken"
    assert hw is not None and hw >= len(rows)


def test_every_row_is_one_well_formed_line(real):
    _, fmt, _, _ = real
    assert not fmt, "\n".join(m for _, m in fmt[:20])


def test_ids_are_unique_and_the_high_water_line_is_not_behind(real):
    _, _, _, problems = real
    assert not _of(problems, "duplicate", "high-water"), "\n".join(_of(problems, "duplicate", "high-water"))


def test_every_ledger_id_a_row_cites_exists_and_the_no_ledger_list_is_exact(real):
    _, _, _, problems = real
    assert not _of(problems, "ledger", "ledger-none"), "\n".join(_of(problems, "ledger", "ledger-none"))


def test_every_path_exists_and_a_shown_rows_words_are_still_there(real):
    _, _, _, problems = real
    assert not _of(problems, "where", "stale"), "\n".join(_of(problems, "where", "stale"))


def test_every_switch_flow_and_claim_a_row_names_exists(real):
    _, _, _, problems = real
    assert not _of(problems, "switch", "flow", "claims"), "\n".join(_of(problems, "switch", "flow", "claims"))


def test_a_row_about_filing_claims_no_registration_the_product_lacks(real):
    rows, _, _, problems = real
    assert not _of(problems, "posture"), "\n".join(_of(problems, "posture"))
    # Not vacuous: the register does hold filing rows, and every walk-through names a real flow.
    assert len([r for r in rows if r.is_about_filing()]) >= 9
    assert {r.fields["Flow"] for r in rows if r.kind == "walkthrough"} <= _flow_keys()


def test_the_forbidden_list_is_held_once_and_compares_lowercase():
    assert FORBIDDEN_REGISTRATION_CLAIMS and all(p == p.lower() for p in FORBIDDEN_REGISTRATION_CLAIMS), (
        "the check lowercases the text, so a phrase with a capital letter would never match")
    holders = []
    needles = set(FORBIDDEN_REGISTRATION_CLAIMS)
    for dirpath, dirnames, filenames in os.walk(API):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            path = Path(dirpath) / fn
            if not fn.endswith(".py") or path.relative_to(API).as_posix() == "domain/filing_posture.py":
                continue
            raw = path.read_text(encoding="utf-8", errors="ignore")
            if "applied for" not in raw or "pending approval" not in raw:  # cheap prefilter
                continue
            for node in ast.walk(ast.parse(raw)):
                if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                    strs = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                    if len(strs & needles) >= 3:
                        holders.append(f"{path.relative_to(API).as_posix()}:{node.lineno}")
    assert not holders, (
        "a second copy of the forbidden filing phrases: import domain.filing_posture.FORBIDDEN_REGISTRATION_CLAIMS "
        "instead, or the next phrase added to one list is missing from the other: " + ", ".join(holders))


# ── the verify clause: each rule fails on the mistake it exists for ──────────

PAGE = "src/page.tsx"
BASE_TEXT = (
    "**Highest id issued: COMING-004**\n\n"
    "- **COMING-001** · `promise` · `shown` · gate:engineering — **A thing.** It is not built. "
    "— _Where:_ `src/page.tsx` — _Says:_ «this feature is coming soon» — _Safe:_ yes — _Owner:_ A "
    "— _Ledger:_ PRE-B-001 — _Added:_ 2026-10-09\n"
    "- **COMING-002** · `switch` · `shown` · gate:owner-decision — **A switch.** Off unless set. "
    "— _Where:_ `src/page.tsx` — _Says:_ «this is not switched on» «piece one piece two» — _Safe:_ no (it hides a state) — _Owner:_ C "
    "— _Ledger:_ PRE-B-001, POST-A-002 — _Switch:_ SOME_FLAG, dashboard:Supabase — _Added:_ 2026-10-09\n"
    "- **COMING-003** · `walkthrough` · `shown` · gate:external-registration — **A walk-through.** Filing is planned. "
    "— _Where:_ `src/page.tsx` — _Says:_ «a registration changes this screen» — _Safe:_ yes — _Owner:_ C "
    "— _Ledger:_ PRE-B-001 — _Flow:_ gstr1 — _Added:_ 2026-10-09\n"
    "- **COMING-004** · `marketing` · `queued` · gate:staffing — **A commitment.** Held by the owner. "
    "— _Where:_ `src/page.tsx` — _Says:_ «words not in the tree yet» — _Safe:_ yes — _Owner:_ C "
    "— _Ledger:_ none — _Claims:_ support-service — _Added:_ 2026-10-09\n"
)
PAGE_TEXT = (
    "<p>this feature is coming soon</p>\n<p>this is not switched on</p>\n"
    'const s = "piece one "\n  "piece two";\n<p>a registration changes this screen</p>\n'
)


def _tree(tmp_path: Path, **over) -> Tree:
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / PAGE).write_text(PAGE_TEXT, encoding="utf-8")
    base = dict(
        root=tmp_path, ledger_ids={"PRE-B-001", "POST-A-002"}, flows={"gstr1"}, claim_ids={"support-service"},
        env_known=lambda n: n == "SOME_FLAG", no_ledger_line={"COMING-004"},
    )
    base.update(over)
    return Tree(**base)


def _run(text: str, tree: Tree) -> list[Problem]:
    rows, fmt, hw = parse(text)
    return [*fmt, *check(rows, hw, tree)]


def _cats(problems: list[Problem]) -> set[str]:
    return {c for c, _ in problems}


def test_the_synthetic_register_is_clean(tmp_path):
    assert _run(BASE_TEXT, _tree(tmp_path)) == []


ROW1_TAIL = "«this feature is coming soon» — _Safe:_ yes — _Owner:_ A"


@pytest.mark.parametrize("mutate, category", [
    # a malformed row
    (lambda t: t.replace(" — _Owner:_ A", ""), "format"),
    (lambda t: t.replace("`promise` · `shown`", "`wish` · `shown`", 1), "format"),
    (lambda t: t.replace("gate:engineering", "gate:vibes", 1), "format"),
    (lambda t: t.replace("_Safe:_ yes", "_Safe:_ maybe", 1), "format"),
    (lambda t: t.replace(ROW1_TAIL, ROW1_TAIL.replace("«", "").replace("»", ""), 1), "format"),
    (lambda t: t.replace("_Owner:_ A", "_Owner:_ D", 1), "format"),
    (lambda t: t.replace("_Added:_ 2026-10-09", "_Added:_ 2026-13-45", 1), "format"),
    (lambda t: t.replace(" — _Switch:_ SOME_FLAG, dashboard:Supabase", "", 1), "format"),
    (lambda t: t.replace(" — _Flow:_ gstr1", "", 1), "format"),
    (lambda t: t + "- a stray bullet in the register\n", "format"),
    # a field out of order
    (lambda t: t.replace("— _Where:_ `src/page.tsx` — _Says:_ " + ROW1_TAIL,
                         "— _Says:_ " + ROW1_TAIL.split(" — _Safe")[0] + " — _Where:_ `src/page.tsx` — _Safe:_ yes — _Owner:_ A", 1), "format"),
    # a duplicate id
    (lambda t: t.replace("**COMING-002**", "**COMING-001**", 1), "duplicate"),
    # the high-water line behind a row, and missing
    (lambda t: t.replace("Highest id issued: COMING-004", "Highest id issued: COMING-003"), "high-water"),
    (lambda t: t.replace("**Highest id issued: COMING-004**", ""), "high-water"),
    # a ledger id that does not exist
    (lambda t: t.replace("_Ledger:_ PRE-B-001, POST-A-002", "_Ledger:_ PRE-B-001, POST-A-999"), "ledger"),
    # a row with no ledger line that is not on the frozen list
    (lambda t: t.replace("_Ledger:_ PRE-B-001 — _Added:_ 2026-10-09\n- **COMING-002**", "_Ledger:_ none — _Added:_ 2026-10-09\n- **COMING-002**"), "ledger-none"),
    # a path that is not a file
    (lambda t: t.replace("`src/page.tsx` — _Says:_ " + ROW1_TAIL, "`src/gone.tsx` — _Says:_ " + ROW1_TAIL, 1), "where"),
    # a shown row whose words are gone (the feature shipped, or the sentence was reworded)
    (lambda t: t.replace(ROW1_TAIL, ROW1_TAIL.replace("is coming soon", "is on its way"), 1), "stale"),
    # a switch variable nothing reads
    (lambda t: t.replace("SOME_FLAG", "RENAMED_FLAG"), "switch"),
    # a flow that does not exist
    (lambda t: t.replace("_Flow:_ gstr1", "_Flow:_ gstr99"), "flow"),
    # a marketing claim id that is not a commitment
    (lambda t: t.replace("_Claims:_ support-service", "_Claims:_ nothing-like-it"), "claims"),
    # a filing row that claims a registration is in motion
    (lambda t: t.replace("Filing is planned.", "Filing is planned and the registration is in progress.", 1), "posture"),
    (lambda t: t.replace("Filing is planned.", "Filing is planned; we have applied for it.", 1), "posture"),
    # a registration-gated row that does not say planned
    (lambda t: t.replace("Filing is planned.", "Filing needs a registration.", 1), "posture"),
])
def test_each_rule_fails_on_the_mistake_it_exists_for(tmp_path, mutate, category):
    mutated = mutate(BASE_TEXT)
    assert mutated != BASE_TEXT, "the mutation did nothing: the test is vacuous"
    got = _run(mutated, _tree(tmp_path))
    assert category in _cats(got), f"expected a `{category}` problem, got {got}"


def test_a_filing_row_may_not_say_coming_soon_but_an_ordinary_one_may(tmp_path):
    """The house words: 'coming soon' for a product feature, 'planned' for a filing."""
    filing = BASE_TEXT.replace("Filing is planned.", "Filing is planned and coming soon.", 1)
    assert "posture" in _cats(_run(filing, _tree(tmp_path)))
    # COMING-001 quotes «this feature is coming soon» and is not about filing: no problem.
    assert _run(BASE_TEXT, _tree(tmp_path)) == []


def test_a_row_in_a_filing_file_is_about_filing_whatever_its_kind(tmp_path):
    posture = tmp_path / "apps" / "api" / "domain"
    posture.mkdir(parents=True)
    (posture / "filing_posture.py").write_text("x = 'we will be live shortly'\n")
    text = (
        "**Highest id issued: COMING-001**\n"
        "- **COMING-001** · `promise` · `shown` · gate:owner-decision — **Posture.** The submission is in progress. "
        "— _Where:_ `apps/api/domain/filing_posture.py` — _Says:_ «we will be live shortly» — _Safe:_ yes — _Owner:_ B "
        "— _Ledger:_ PRE-B-001 — _Added:_ 2026-10-09\n"
    )
    assert "posture" in _cats(_run(text, _tree(tmp_path)))


def test_a_queued_rows_words_need_not_be_in_the_tree_yet(tmp_path):
    # COMING-004 is `queued` and quotes words that are in no file.
    assert "stale" not in _cats(_run(BASE_TEXT, _tree(tmp_path)))
    shown = BASE_TEXT.replace("`marketing` · `queued`", "`marketing` · `shown`")
    assert "stale" in _cats(_run(shown, _tree(tmp_path)))


def test_a_sentence_written_in_pieces_is_found():
    one, two = _text_variants('x = "piece one "\n    "piece two"\ny = "a " +\n    "b"\n')
    assert "piece one piece two" in two and "a b" in two and "piece one piece two" not in one


def test_the_no_ledger_list_may_not_outlive_its_row(tmp_path):
    got = _run(BASE_TEXT, _tree(tmp_path, no_ledger_line={"COMING-004", "COMING-777"}))
    assert any("COMING-777" in m for c, m in got if c == "ledger-none")
    got = _run(BASE_TEXT, _tree(tmp_path, no_ledger_line=set()))
    assert any("COMING-004" in m for c, m in got if c == "ledger-none")
