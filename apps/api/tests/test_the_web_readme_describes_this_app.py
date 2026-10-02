"""apps/web/README.md describes this app, and the paths it names exist (engineering-24).

WHAT WAS WRONG
    The file was the stock create-next-app text: "This is a Next.js project bootstrapped with create-next-app",
    `npm run dev`, a link to the Vercel deployment guide. It said nothing true of this application and a good deal
    that was false (this is a static export on Cloudflare Pages, and Vercel is not involved), and it is the first
    file a person opening `apps/web` reads.

WHAT THIS HOLDS
    * It is not the boilerplate again (a regenerated app, a careless merge or a template copy would bring it back).
    * It says the thing that decides what can be done in this app: it is a STATIC EXPORT with no server and no
      runtime environment, so the only values it can read are `NEXT_PUBLIC_*`.
    * Every file or folder it names in backticks exists. A README that points at `lib/money/rupeeInput.ts` after the
      file moved is the same defect as the boilerplate, only slower: it tells a person where to look and is wrong.
      The check is a RULE over whatever the README names, not a list of today's paths.

WHAT IT DOES NOT HOLD
    That the prose is right, or complete. A path that exists says the sentence points somewhere real, not that what
    is there is what the sentence claims.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
WEB = REPO / "apps" / "web"
README = WEB / "README.md"

pytestmark = pytest.mark.skipif(not README.is_file(), reason="apps/web is not in this checkout")

#: Words that only the create-next-app template (or a deployment guide for a platform this app is not on) uses.
BOILERPLATE = ("bootstrapped with", "create-next-app", "Learn Next.js", "vercel.com/new", "Geist", "next/font")


def _text() -> str:
    return README.read_text(encoding="utf-8")


def test_the_readme_is_not_the_create_next_app_boilerplate():
    found = [phrase for phrase in BOILERPLATE if phrase in _text()]
    assert not found, f"apps/web/README.md carries the stock Next.js text again ({found}); describe this app instead"


def test_the_readme_says_this_is_a_static_export_with_no_server_and_names_the_only_values_it_can_read():
    text = _text()
    assert 'output: "export"' in text, "the README must say the app is a static export, which decides everything else"
    assert "NEXT_PUBLIC_" in text, "the README must say the only values the app can read are NEXT_PUBLIC_*"
    assert "no server" in text.lower()
    # And that is still true of the app it describes.
    config = (WEB / "next.config.mjs").read_text(encoding="utf-8")
    assert re.search(r'output:\s*"export"', config), "the README says static export and next.config.mjs says otherwise"


def _named_paths(text: str) -> list[str]:
    """Every backticked token that is meant as a file or folder: it has a slash inside it, or is one of the few bare
    file names the README names. URLs and routes (a leading slash), globs, and anything with a space are not paths."""
    out = []
    for token in re.findall(r"`([^`\n]+)`", text):
        if token.startswith("/") or any(c in token for c in " *{}<>=:()|$") or token.endswith("(s)"):
            continue
        bare = token in {"wrangler.toml", "next.config.mjs", ".env.local.example", "tsconfig.test.json"}
        if "/" in token.strip("/") or bare:
            out.append(token)
    return out


#: Paths the README names that are NOT in a checkout, each for a stated reason. Held to the ignore file, so an entry
#: cannot stay once the file is tracked, and a tracked file cannot hide here.
IGNORED_ON_PURPOSE = {
    "apps/api/.env": "holds every secret the backend reads and is gitignored; the README says that is where they belong",
}


def _exists(token: str) -> bool:
    relative = token.rstrip("/")
    return any((base / relative).exists() for base in (WEB, REPO))


def test_the_scan_finds_the_paths_the_readme_names_so_the_check_is_not_vacuous():
    assert len(_named_paths(_text())) >= 15, "the README names almost no paths; the existence check would pass over nothing"


def test_a_path_exempted_from_the_check_is_ignored_by_git_and_still_named():
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore, "the .gitignore no longer ignores .env, so apps/api/.env is no longer 'ignored on purpose'"
    for path, why in IGNORED_ON_PURPOSE.items():
        assert path in _named_paths(_text()), f"the README no longer names {path} ({why}); drop the exemption"


def test_every_file_or_folder_the_readme_names_exists():
    missing = sorted({t for t in _named_paths(_text()) if not _exists(t) and t not in IGNORED_ON_PURPOSE})
    assert not missing, (f"apps/web/README.md names paths that do not exist: {missing}. A file moved or was deleted; "
                         "fix the README so it points somewhere real.")
