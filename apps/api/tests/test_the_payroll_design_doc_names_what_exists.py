"""The payroll design record points only at files, symbols and screens that exist.

WHY THIS EXISTS

    `docs/architecture/10-payroll.md` was written on 4 September 2026 as a plan and
    its own status box said, three days later, that it was partly superseded. A
    month on it still carried a twelve-row "build to end-December 2026" table in
    which every row had shipped, sized in weeks and days; it named `/payroll/setup`
    as a screen (the owner decided not to build one: `/settings/statutory-values` is
    that screen); and it cited two audit files by a path that was deleted on
    8 October 2026, with nothing saying they were recoverable. A reader could not
    tell what was built from what was planned, and source comments cite this
    document by section name, so it could be neither deleted nor left to rot.

    The rule is derived from the tree, not from the document's present contents:

      * every backticked repository path resolves (and a `path::symbol` names a
        symbol the file contains); a `docs/audits/...` path is the one exception and
        is allowed only where its paragraph also carries the commit that holds the
        deleted file;
      * every payroll screen the document names has a page, or its row says "not
        built";
      * no table keeps the planning header `# | what | size`, which is what a
        schedule looks like once nobody has updated it.

    It cannot say a description is TRUE, only that nothing it points at is missing.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
API = REPO / "apps" / "api"
WEB = REPO / "apps" / "web"
DOC = REPO / "docs" / "architecture" / "10-payroll.md"
DELETED_AUDITS_COMMIT = "315e6a19"

PATH_TOKEN = re.compile(
    r"`((?:apps|docs|domain|routers|services|components|lib|app|migrations|tests|core)/"
    r"[^`\s]*?\.(?:py|tsx?|md|sql))(?:::(\w+))?`")
ROUTE_TOKEN = re.compile(r"`(/(?:payroll|clients/\[id\]/payroll|settings/[\w-]+)[\w/\[\]-]*)`")
PLANNING_HEADER = re.compile(r"^\|\s*#\s*\|\s*what\s*\|\s*size\s*\|", re.IGNORECASE | re.MULTILINE)
FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)


def prose(text: str) -> str:
    return FENCE.sub("", text)


def paragraphs(text: str) -> list[str]:
    return re.split(r"\n\s*\n", prose(text))


def resolve(path: str) -> Path | None:
    for root in (REPO, API, WEB):
        candidate = root / path
        if candidate.is_file():
            return candidate
    return None


def path_problems(text: str) -> list[str]:
    out: list[str] = []
    for para in paragraphs(text):
        annotated = DELETED_AUDITS_COMMIT in para
        for m in PATH_TOKEN.finditer(para):
            path, symbol = m.group(1), m.group(2)
            if path.startswith("docs/audits/"):
                if not annotated:
                    out.append(f"{path} was deleted on 8 October 2026 and its paragraph does not say "
                               f"where to recover it ({DELETED_AUDITS_COMMIT})")
                continue
            found = resolve(path)
            if found is None:
                out.append(f"{path} does not exist")
            elif symbol and path.endswith(".py") and not re.search(
                    rf"\b{re.escape(symbol)}\b", found.read_text(encoding="utf-8")):
                out.append(f"{path} has no {symbol}")
    return out


def screen_problems(text: str) -> list[str]:
    out: list[str] = []
    for line in prose(text).splitlines():
        for m in ROUTE_TOKEN.finditer(line):
            route = m.group(1)
            if (WEB / "app" / route.lstrip("/") / "page.tsx").is_file():
                continue
            if "not built" not in line.lower():
                out.append(f"{route} has no page and its line does not say 'not built': {line.strip()[:120]}")
    return out


def planning_tables(text: str) -> int:
    return len(PLANNING_HEADER.findall(prose(text)))


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


def test_every_path_the_document_names_exists():
    found = path_problems(_read())
    assert not found, "\n".join(found)


def test_every_payroll_screen_the_document_names_has_a_page_or_says_it_is_not_built():
    found = screen_problems(_read())
    assert not found, "\n".join(found)


def test_no_planning_table_survives_once_its_rows_have_shipped():
    assert planning_tables(_read()) == 0, (
        "a '# | what | size' table is a schedule: replace it with what shipped and where it is")


def test_the_collector_is_not_vacuous():
    text = _read()
    # the floor is what the document held before it was rewritten, so it cannot fail for the very
    # defects the tests above name
    assert len(PATH_TOKEN.findall(prose(text))) >= 10, "the document's paths were not found"
    assert len(ROUTE_TOKEN.findall(prose(text))) >= 5, "the document's screens were not found"
    # the headings other files cite by name must still be there
    for heading in ("Deferred with reasons", "The cost brake", "13th top-level workspace",
                    "exception index"):
        assert heading.lower() in text.lower(), f"source comments cite {heading!r}"
    assert (WEB / "app" / "payroll" / "page.tsx").is_file()


def test_the_rules_fire_on_each_way_the_document_can_be_wrong():
    ok_path = "see `apps/api/routers/payroll.py::finalize_run`."
    assert path_problems(ok_path) == []
    # a path that does not exist, a symbol the file lacks
    assert path_problems("see `apps/api/routers/payroll_gone.py`.")
    assert path_problems("see `apps/api/routers/payroll.py::no_such_function_anywhere`.")
    # a deleted audit: fine with its recovery commit in the paragraph, a finding without
    audit = "`docs/audits/2026-09-01-payroll-can-it-run-a-year.md`"
    assert path_problems(audit)
    assert path_problems(f"{audit}, deleted: git show {DELETED_AUDITS_COMMIT}:docs/audits/x.md") == []
    # the recovery commit in ANOTHER paragraph does not rescue this one
    assert path_problems(f"{audit}\n\nunrelated {DELETED_AUDITS_COMMIT}")
    # a screen: exists, missing and unmarked, missing and marked
    assert screen_problems("| **People** (`/payroll/people`) | built |") == []
    assert screen_problems("| **Setup** (`/payroll/setup`) | built |")
    assert screen_problems("| **Setup** (`/payroll/setup`) | **Not built**, by decision |") == []
    assert planning_tables("| # | what | size |\n|---|---|---|\n| 1 | x | weeks |") == 1
    assert planning_tables("| # | what | where it is |\n|---|---|---|\n| 1 | x | y |") == 0
