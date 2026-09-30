"""`docker compose up` must work on a clean clone, and it must not bake a secret into an image (engineering-25).

WHAT WAS WRONG
    `docker-compose.yml` built its `web` service from `./apps/web/Dockerfile`, which has never existed, and read
    `./apps/web/.env.local` and `./apps/api/.env`, which are gitignored — so on a fresh checkout the first
    command a new developer ran failed before a single container started:

        env file .../apps/web/.env.local not found

THE RULE, NOT A LIST OF TODAY'S SERVICES
    Every path the compose file names must either EXIST in a clean clone or be marked `required: false`; every
    service's build names a Dockerfile that exists; every `depends_on` names a service that is defined. The
    checks derive the population from the file, so a second service added next year is held to it too.

    PyYAML is not a dependency of this service and the file is ours and small, so `_services` reads the subset
    of YAML it uses (two-space indentation, block lists) rather than importing a parser the required CI job
    would not have. `_problems` is pure over the text and a root directory, which is what lets the ORIGINAL
    broken file be fed back through it below: a guard that has never been shown the defect proves nothing.

THE SECOND HALF IS A SECRET
    The API's Dockerfile says `COPY . .`, so a developer who filled in `apps/api/.env` to run the stack against
    a real Supabase project would bake the service-role key and every AI key into an image layer. Compose
    passes them at run time through `env_file`, which is the only way they should arrive, so a build context
    that copies itself whole must carry a `.dockerignore` that excludes `.env` and `.env.*`.

WHAT CANNOT BE TESTED HERE
    That the image builds and that the container answers. The sandbox this was written in has the Docker client
    and no daemon. What was run instead: `docker compose config` on the file (the last test, where the client is
    present) and the container's own command, gunicorn with the same worker class and no Supabase environment,
    natively.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
COMPOSE = REPO / "docker-compose.yml"
README = REPO / "README.md"

# The file as it was, kept so the rule is shown the defect it was written for on every run.
ORIGINAL_BROKEN = '''\
version: "3.9"

services:
  api:
    build: ./apps/api
    ports:
      - "8000:8000"
    env_file:
      - ./apps/api/.env
    environment:
      - APP_ENV=development

  web:
    build:
      context: ./apps/web
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    env_file:
      - ./apps/web/.env.local
    depends_on:
      - api
'''


# ── reading the subset of YAML the compose file uses ────────────────────────────

def _strip(line: str) -> str:
    """A line without its comment. Full-line only is not enough: `required: false  # why` is ordinary."""
    return re.sub(r"\s+#.*$", "", line.rstrip())


def _unquote(value: str) -> str:
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else value


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _services(text: str) -> dict[str, dict]:
    """{name: {build: (context, dockerfile)|None, env_files: [(path, required)], binds: [src], depends_on: [name]}}"""
    lines = [_strip(l) for l in text.splitlines()]
    lines = [l for l in lines if l.strip() and not l.lstrip().startswith("#")]

    # the `services:` block: everything indented under it until the next top-level key
    start = next((i for i, l in enumerate(lines) if re.fullmatch(r"services:\s*", l)), None)
    assert start is not None, "docker-compose.yml has no `services:` block"
    block: list[str] = []
    for l in lines[start + 1:]:
        if _indent(l) == 0:
            break
        block.append(l)

    # split into one chunk per service (a key at indent 2)
    chunks: dict[str, list[str]] = {}
    current = None
    for l in block:
        m = re.fullmatch(r"  ([A-Za-z0-9_.-]+):\s*", l)
        if m:
            current = m.group(1)
            chunks[current] = []
        elif current is not None:
            chunks[current].append(l)

    out: dict[str, dict] = {}
    for name, body in chunks.items():
        svc = {"build": None, "env_files": [], "binds": [], "depends_on": []}

        def section(key: str) -> list[str]:
            """The lines nested under `    <key>:` (indent 4), or [] — plus the inline value, if any."""
            for i, l in enumerate(body):
                m = re.fullmatch(rf"    {key}:\s*(.*)", l)
                if m:
                    nested = []
                    for n in body[i + 1:]:
                        if _indent(n) <= 4:
                            break
                        nested.append(n)
                    # stripped: a caller asks "does this line start with a dash", and an indent hides it
                    nested = [n.strip() for n in nested]
                    return [m.group(1).strip(), *nested] if m.group(1).strip() else nested
            return []

        b = section("build")
        if b:
            if len(b) == 1 and not b[0].startswith(("context:", "dockerfile:")):
                svc["build"] = (_unquote(b[0]), "Dockerfile")
            else:
                kv = {k: _unquote(v) for k, v in (x.strip().split(":", 1) for x in b if ":" in x)}
                svc["build"] = (kv.get("context", "."), kv.get("dockerfile", "Dockerfile"))

        e = section("env_file")
        if len(e) == 1 and not e[0].startswith("-"):
            svc["env_files"].append((_unquote(e[0]), True))                      # env_file: ./path
        else:
            i = 0
            while i < len(e):
                item = e[i].strip()
                if item.startswith("- path:"):
                    path, required = _unquote(item.split(":", 1)[1]), True
                    j = i + 1
                    while j < len(e) and not e[j].strip().startswith("-"):
                        m = re.fullmatch(r"required:\s*(\w+)", e[j].strip())
                        if m:
                            required = m.group(1).lower() != "false"
                        j += 1
                    svc["env_files"].append((path, required))
                elif item.startswith("- "):
                    svc["env_files"].append((_unquote(item[2:]), True))
                i += 1

        for v in section("volumes"):
            src = _unquote(v.strip()[2:]).split(":", 1)[0] if v.strip().startswith("- ") else ""
            if src.startswith(("./", "../")):
                svc["binds"].append(src)

        for d in section("depends_on"):
            d = d.strip()
            if d.startswith("- "):
                svc["depends_on"].append(_unquote(d[2:]))
            elif re.fullmatch(r"[A-Za-z0-9_.-]+:", d):
                svc["depends_on"].append(d[:-1])
        out[name] = svc
    return out


def _problems(text: str, root: Path, exists=None) -> list[str]:
    """Everything in this compose text that a clean clone at `root` cannot satisfy.

    `exists` answers "is this path in the clone?" and defaults to the filesystem; the clean-clone test passes
    one that treats a gitignored env file as absent, which is what a new developer's checkout holds."""
    exists = exists or (lambda p: p.exists())
    found: list[str] = []
    services = _services(text)
    for name, svc in services.items():
        if svc["build"]:
            context, dockerfile = svc["build"]
            ctx = (root / context).resolve()
            if not ctx.is_dir():
                found.append(f"{name}: build context {context} is not a directory")
            elif not exists(ctx / dockerfile):
                found.append(f"{name}: build names {context}/{dockerfile}, which does not exist")
        for path, required in svc["env_files"]:
            if required and not exists(root / path):
                found.append(f"{name}: env_file {path} does not exist on a clean clone and is not `required: false`")
        for src in svc["binds"]:
            if not exists(root / src):
                found.append(f"{name}: bind mount source {src} does not exist")
        for dep in svc["depends_on"]:
            if dep not in services:
                found.append(f"{name}: depends_on {dep}, which is not a service in this file")
    return found


# ── the rule, on the file ───────────────────────────────────────────────────────

def test_the_compose_file_has_services_and_the_reader_sees_them():
    """Vacuity guard: a reader that finds nothing would let every rule below pass."""
    services = _services(COMPOSE.read_text(encoding="utf-8"))
    assert "api" in services
    assert services["api"]["build"] is not None
    assert services["api"]["env_files"], "the api service names an env file, so the reader must see it"


def _is_gitignored_env(path: Path) -> bool:
    """`.env`, `.env.local` and the like are gitignored (root .gitignore and apps/web/.gitignore); the
    `.example` files beside them are tracked."""
    return path.name.startswith(".env") and not path.name.endswith(".example")


def test_a_clean_clone_satisfies_every_path_the_compose_file_names():
    """Measured with every gitignored env file treated as absent, because a developer's own checkout may well
    hold an `.env` and then everything passes for a reason a new hire does not share."""
    problems = _problems(COMPOSE.read_text(encoding="utf-8"), REPO,
                         exists=lambda p: p.exists() and not _is_gitignored_env(p))
    assert problems == []


def test_every_dockerfile_a_service_builds_from_is_in_the_repository():
    """The original failure, asked of the real tree: the file is checked in, not merely present on one machine."""
    for name, svc in _services(COMPOSE.read_text(encoding="utf-8")).items():
        if svc["build"]:
            context, dockerfile = svc["build"]
            assert (REPO / context / dockerfile).is_file(), f"{name} builds {context}/{dockerfile}, which is missing"


def test_the_rule_catches_the_file_it_was_written_for(tmp_path):
    """The ORIGINAL compose file, through the same function, on a tree shaped like a clean clone: the api
    Dockerfile exists, apps/web has no Dockerfile, and no env file exists anywhere."""
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "Dockerfile").write_text("FROM scratch\n")
    # A single literal on purpose: this builds a SYNTHETIC tree and reads no frontend file, and the
    # browser-contract selector would otherwise take a segment-by-segment path for a read of the app.
    (tmp_path / "apps/web").mkdir(parents=True)
    problems = _problems(ORIGINAL_BROKEN, tmp_path)
    joined = "\n".join(problems)
    assert "web: build names ./apps/web/Dockerfile, which does not exist" in joined
    assert "web: env_file ./apps/web/.env.local does not exist" in joined
    assert "api: env_file ./apps/api/.env does not exist" in joined


def test_an_optional_env_file_is_tolerated_and_a_required_one_is_not(tmp_path):
    """Both directions, so the `required` reading cannot be satisfied by ignoring the flag either way."""
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "Dockerfile").write_text("FROM scratch\n")
    optional = ORIGINAL_BROKEN.split("  web:")[0].replace(
        "      - ./apps/api/.env\n", "      - path: ./apps/api/.env\n        required: false\n")
    assert _problems(optional, tmp_path) == []
    required = optional.replace("required: false", "required: true")
    assert any("api: env_file ./apps/api/.env" in p for p in _problems(required, tmp_path))
    assert any("depends_on" in p for p in _problems(
        optional.replace("    environment:", "    depends_on:\n      - ghost\n    environment:"), tmp_path))


def test_the_committed_file_does_not_use_the_obsolete_version_key():
    """Compose v2 prints a warning for it on every command, which is noise a new developer reads as breakage."""
    assert not re.search(r"^version:", COMPOSE.read_text(encoding="utf-8"), re.M)


# ── the secret ──────────────────────────────────────────────────────────────────

def _copies_itself_whole(dockerfile: Path) -> bool:
    return any(re.match(r"\s*COPY\s+(--\S+\s+)*\.\s+\S+", l, re.I) for l in dockerfile.read_text().splitlines())


def test_a_build_context_that_copies_itself_whole_excludes_the_env_file():
    checked = 0
    for name, svc in _services(COMPOSE.read_text(encoding="utf-8")).items():
        if not svc["build"]:
            continue
        ctx = REPO / svc["build"][0]
        if not _copies_itself_whole(ctx / svc["build"][1]):
            continue
        checked += 1
        ignore = ctx / ".dockerignore"
        assert ignore.is_file(), f"{name}: the Dockerfile says `COPY . .` and there is no .dockerignore"
        entries = {l.strip() for l in ignore.read_text().splitlines() if l.strip() and not l.startswith("#")}
        assert ".env" in entries and ".env.*" in entries, (
            f"{name}: .dockerignore must exclude `.env` and `.env.*` or a filled-in env file is baked into a layer")
    assert checked >= 1, "no service copies its context whole — then this rule has nothing to hold and should be deleted"


def test_the_dockerignore_does_not_hide_anything_the_image_runs_from():
    """An over-eager ignore fails at run time, on Render, where nobody is watching: what the Dockerfile COPYs
    and the CMD imports has to survive it."""
    ignore = {l.strip() for l in (REPO / "apps/api/.dockerignore").read_text().splitlines()
              if l.strip() and not l.startswith("#")}
    for needed in ("main.py", "requirements.txt", "core", "routers", "services", "domain", "migrations"):
        assert needed not in ignore and f"{needed}/" not in ignore, f"{needed} is excluded from the image"


# ── the README says what the file does ─────────────────────────────────────────

def test_the_readme_gives_the_command_and_says_what_it_does_not_give():
    text = README.read_text(encoding="utf-8")
    assert "docker compose up" in text
    services = set(_services(COMPOSE.read_text(encoding="utf-8")))
    assert "web" not in services, "the README says the web app is not in the compose file"
    assert re.search(r"not in the compose file", text)
    assert re.search(r"mock mode", text, re.I)
    assert "supabase start" in text, "the README must say why there is no local Postgres and what would be"


# ── the file, as Compose itself reads it ───────────────────────────────────────

def _compose_version() -> tuple[int, ...] | None:
    docker = shutil.which("docker")
    if not docker:
        return None
    try:
        out = subprocess.run([docker, "compose", "version", "--short"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"v?(\d+)\.(\d+)", out.stdout.strip())
    return (int(m.group(1)), int(m.group(2))) if out.returncode == 0 and m else None


@pytest.mark.skipif(_compose_version() is None or _compose_version() < (2, 24),
                    reason="Docker Compose 2.24+ not on PATH (`required: false` is newer than that)")
def test_docker_compose_itself_accepts_the_file_with_no_warnings(tmp_path):
    """`docker compose config` is client-side and needs no daemon. Run on a copy with no env file in it, so what
    it proves is the clean-clone case and not the developer's own."""
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "Dockerfile").write_text("FROM scratch\n")
    shutil.copy(COMPOSE, tmp_path / "docker-compose.yml")
    out = subprocess.run([shutil.which("docker"), "compose", "config", "--quiet"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "level=warning" not in out.stderr, out.stderr
