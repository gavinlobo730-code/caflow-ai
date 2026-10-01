"""The schema of every route this app mounts is not served to a stranger.

SECURITY-PRIVACY-26

WHAT WAS WRONG
    `FastAPI(title=..., version=..., lifespan=...)` with no `docs_url`,
    `redoc_url` or `openapi_url`, so /docs, /redoc and /openapi.json listed all
    ~1,100 routes — every path, parameter and body model — to anyone, on the
    production host, without a login.

WHAT THESE PIN
    * the three arguments come from ONE function and move together (an
      `openapi_url=None` alone leaves /docs mounted over a schema that 404s;
      `docs_url=None` alone leaves the schema public);
    * an UNSET APP_ENV keeps them off — core/auth.py reads it as production, and
      a page that is wrongly off costs a developer one variable while one that is
      wrongly on costs the whole route map;
    * the REAL app, imported in a fresh interpreter under each environment, 404s
      all three in production and serves all three in development. The app object
      is built at import, so this cannot be checked against the one the test
      process already holds; `import main` is ~6 s, so the three environments run
      concurrently.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import core.security_config as sc

API_ROOT = Path(__file__).resolve().parents[1]
PAGES = ("/docs", "/redoc", "/openapi.json")

_PROBE = """
import json, os
from fastapi.testclient import TestClient
import main
c = TestClient(main.app, raise_server_exceptions=False)
out = {p: c.get(p).status_code for p in %r}
out["/health"] = c.get("/health").status_code
out["root"] = c.get("/").json()["data"]
out["routes"] = len(main.app.routes)
out["schema_in_process"] = len(main.app.openapi().get("paths", {}))
print("PROBE" + json.dumps(out))
""" % (list(PAGES),)


def _probe(app_env: str | None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("APP_ENV", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SENTRY_DSN")}
    if app_env is not None:
        env["APP_ENV"] = app_env
    done = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=API_ROOT, env=env,
        capture_output=True, text=True, timeout=240)
    lines = [l for l in done.stdout.splitlines() if l.startswith("PROBE")]
    assert lines, f"probe printed nothing (rc={done.returncode}):\n{done.stderr[-1500:]}"
    return json.loads(lines[-1][len("PROBE"):])


@pytest.fixture(scope="module")
def apps() -> dict[str, dict]:
    envs = {"production": "production", "unset": None, "development": "development"}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(_probe, value) for name, value in envs.items()}
        return {name: f.result() for name, f in futures.items()}


# ── the decision ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env,expected", [
    (None, False), ("", False), ("production", False), ("Production", False),
    ("staging", False), ("prod", False),
    ("development", True), ("Development", True), ("dev", True),
    ("local", True), ("test", True),
])
def test_only_a_development_like_environment_serves_the_schema(monkeypatch, env, expected):
    monkeypatch.delenv("APP_ENV", raising=False)
    if env is not None:
        monkeypatch.setenv("APP_ENV", env)
    assert sc.api_docs_enabled() is expected
    kwargs = sc.docs_kwargs()
    assert set(kwargs) == {"docs_url", "redoc_url", "openapi_url"}
    # All three move together.
    assert all(v is not None for v in kwargs.values()) is expected
    assert all(v is None for v in kwargs.values()) is (not expected)


def test_main_builds_the_app_from_that_one_function():
    src = (API_ROOT / "main.py").read_text(encoding="utf-8")
    assert "docs_kwargs()" in src and "FastAPI(" in src
    for literal in ("docs_url=", "redoc_url=", "openapi_url="):
        assert literal not in src, (
            f"{literal!r} is spelled out in main.py — the three arguments must "
            "come from core.security_config.docs_kwargs, or one can drift")


# ── the real app ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env", ["production", "unset"])
def test_production_serves_none_of_the_three(apps, env):
    result = apps[env]
    for page in PAGES:
        assert result[page] == 404, (env, page, result[page])
    # It is the pages that went, not the app.
    assert result["/health"] == 200
    assert result["routes"] > 500


def test_production_root_does_not_point_at_a_page_that_404s(apps):
    assert "docs" not in apps["production"]["root"]


def test_development_still_serves_all_three(apps):
    result = apps["development"]
    for page in PAGES:
        assert result[page] == 200, (page, result[page])
    assert result["root"].get("docs") == "/docs"


def test_the_schema_is_still_buildable_in_process_in_production(apps):
    """Anything that generates a client from the code calls `app.openapi()`;
    switching the URL off must not have broken that."""
    assert apps["production"]["schema_in_process"] > 500
