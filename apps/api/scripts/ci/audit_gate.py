"""Turn a dependency audit into a pass or a fail that means something (engineering-05).

WHY A GATE AND NOT `pip-audit && pnpm audit --audit-level high`
    Measured on 30-09-2026, the day this was written: the backend's requirements
    resolve to 87 packages, 5 of which carry 30 distinct advisories
    (python-multipart, pyjwt, starlette, gunicorn, python-dotenv); apps/web has
    70 production advisories, 2 of them critical and 35 high; apps/marketing 28.
    A step that fails on any of those is red on its first run and stays red until
    the upgrades land, and "a check that is always red is a check nobody reads"
    (scripts/smoke_api.py, on the same mistake made with a latency budget).

    So the gate is a RATCHET. It fails on an advisory that is NOT in a reviewed
    baseline, names what is, and says which baseline lines have gone stale so
    they can be deleted. The baseline may only shrink: a line is an exposure the
    product carries today, written down, never a judgement that it is safe. A
    newly published advisory, or a newly pinned vulnerable version, is the thing
    it exists to catch.

TWO KINDS OF REPORT, AND ONLY ONE HAS A SEVERITY
    `pnpm audit --json` carries a severity per advisory, so the JS gate fails only
    at or above `--min-severity` (default high). `pip-audit --format json` does
    NOT: its records are id, aliases, fix_versions and description. So for Python
    the gate is any advisory not in the baseline, which is stricter than "high"
    and is stated here rather than implied. Lowering the pip side to a severity
    would mean inventing one.

WHAT COUNTS AS THE SAME ADVISORY
    One advisory has several names (PYSEC-…, CVE-…, GHSA-…) and the two tools use
    different ones, so a finding matches the baseline if ANY of its ids or aliases
    appears there. A baseline line carries one of them, upper-cased.

A TOOL THAT DID NOT RUN IS NOT A CLEAN RESULT
    Exit 0 means "audited, nothing new". Exit 1 means "audited, something new".
    Exit 2 means the report is missing, unreadable or empty — a failed network
    call, a wrong directory, a resolver error — and is NEVER reported as clean.
    A run that audited zero packages passes every check in the world, so zero
    packages is refused.

Usage:
    audit_gate.py --kind pip  --report pip-audit.json --baseline .github/audit-baseline/pip-api.txt
    audit_gate.py --kind pnpm --report pnpm.json      --baseline .github/audit-baseline/pnpm-web.txt \\
                  [--min-severity high] [--label apps/web]
    audit_gate.py ... --print-baseline        # the lines to paste into a baseline, nothing else
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

#: Lowest to highest. pnpm adds "info" below "low".
SEVERITIES = ("info", "low", "moderate", "high", "critical")

_ID = re.compile(r"^[A-Z0-9][A-Z0-9-]+$")


class AuditError(Exception):
    """The report cannot be trusted to mean 'nothing found'. Exit code 2."""


@dataclass(frozen=True)
class Finding:
    ids: frozenset          # every name this advisory goes by, upper-cased
    primary: str            # the one a baseline line should carry
    package: str
    version: str
    severity: Optional[str]  # None for pip-audit, which does not report one
    title: str
    fix: str


@dataclass(frozen=True)
class Verdict:
    new: tuple               # findings at or above the threshold that the baseline does not name
    accepted: tuple          # findings the baseline names
    below: tuple             # findings under the severity threshold (pnpm only)
    stale: tuple             # baseline ids that matched no finding at all


# ── reading a report ────────────────────────────────────────────────────────────

def pip_findings(report: object) -> list[Finding]:
    """pip-audit's JSON: {"dependencies": [{"name", "version", "vulns": [...]}], "fixes": [...]}."""
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise AuditError("the pip-audit report has no 'dependencies' list — the audit did not run")
    deps = report["dependencies"]
    if not deps:
        raise AuditError("pip-audit audited ZERO packages — an empty audit passes everything, so it is refused")
    seen: set = set()
    out: list[Finding] = []
    for dep in deps:
        for vuln in dep.get("vulns") or []:
            ids = frozenset({str(vuln["id"]).upper(), *(str(a).upper() for a in vuln.get("aliases") or [])})
            key = (dep["name"], dep["version"], vuln["id"])
            if key in seen:         # pip-audit lists a vulnerability once per alias it was found under
                continue
            seen.add(key)
            out.append(Finding(
                ids=ids, primary=str(vuln["id"]).upper(), package=dep["name"], version=dep["version"],
                severity=None, title=(vuln.get("description") or "").strip().split("\n")[0][:90],
                fix=", ".join(vuln.get("fix_versions") or []) or "no fixed version listed",
            ))
    return out


def pnpm_findings(report: object) -> list[Finding]:
    """`pnpm audit --json`: {"advisories": {id: {...}}, "metadata": {"totalDependencies": N}}."""
    if not isinstance(report, dict) or not isinstance(report.get("advisories"), dict):
        raise AuditError("the pnpm audit report has no 'advisories' object — the audit did not run "
                         "(a registry error prints an 'error' object instead)")
    meta = report.get("metadata") or {}
    if not meta.get("totalDependencies"):
        raise AuditError("pnpm audit covered ZERO dependencies — wrong directory or no lockfile, "
                         "and an empty audit passes everything")
    out: list[Finding] = []
    for adv in report["advisories"].values():
        ghsa = str(adv.get("github_advisory_id") or "").upper()
        cves = [str(c).upper() for c in adv.get("cves") or []]
        ids = frozenset(i for i in (ghsa, *cves) if i)
        if not ids:
            raise AuditError(f"an advisory for {adv.get('module_name')} carries no GHSA or CVE id to match a baseline on")
        versions = sorted({f.get("version", "?") for f in adv.get("findings") or []})
        sev = str(adv.get("severity") or "").lower()
        if sev not in SEVERITIES:
            raise AuditError(f"an advisory for {adv.get('module_name')} has an unknown severity {sev!r}")
        out.append(Finding(
            ids=ids, primary=ghsa or sorted(ids)[0], package=str(adv.get("module_name")),
            version=", ".join(versions) or "?", severity=sev,
            title=(adv.get("title") or "").strip()[:90],
            fix=str(adv.get("patched_versions") or "none"),
        ))
    return out


# ── the baseline ────────────────────────────────────────────────────────────────

def read_baseline(text: str) -> dict[str, str]:
    """{ID: note}. One id per line, `ID  # package version [severity] — title`; `#` lines are comments."""
    out: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        body, _, note = raw.partition("#")
        token = body.strip().upper()
        if not token:
            continue
        if not _ID.match(token):
            raise AuditError(f"baseline line {n} is not an advisory id: {raw!r}")
        if token in out:
            raise AuditError(f"baseline line {n}: {token} is listed twice")
        out[token] = note.strip()
    return out


def render_baseline(findings: Iterable[Finding]) -> str:
    """The lines for a baseline, one per finding, sorted so a diff shows only what changed."""
    rows = sorted(findings, key=lambda f: (f.package, f.primary))
    return "".join(
        f"{f.primary:<24} # {f.package} {f.version}"
        f"{f' [{f.severity}]' if f.severity else ''} — {f.title or 'see the advisory'} (fix: {f.fix})\n"
        for f in rows
    )


# ── the verdict ─────────────────────────────────────────────────────────────────

def judge(findings: list[Finding], baseline: dict[str, str], min_severity: Optional[str]) -> Verdict:
    floor = SEVERITIES.index(min_severity) if min_severity else None
    new, accepted, below = [], [], []
    matched: set = set()
    for f in findings:
        hit = f.ids & baseline.keys()
        matched |= hit
        if floor is not None and f.severity is not None and SEVERITIES.index(f.severity) < floor:
            below.append(f)
        elif hit:
            accepted.append(f)
        else:
            new.append(f)
    stale = tuple(sorted(set(baseline) - matched))
    return Verdict(tuple(new), tuple(accepted), tuple(below), stale)


# ── the command line ────────────────────────────────────────────────────────────

def _load_report(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AuditError(f"cannot read the report {path}: {exc}") from exc
    try:
        return json.loads(text)
    except ValueError as exc:
        raise AuditError(f"the report {path} is not JSON ({exc}); first bytes: {text[:120]!r}") from exc


def main(argv: Optional[list[str]] = None, env: Optional[dict] = None) -> int:
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", choices=("pip", "pnpm"), required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--min-severity", choices=SEVERITIES, default="high",
                    help="pnpm only; pip-audit reports no severity so every unbaselined advisory counts")
    ap.add_argument("--label", default=None, help="what was audited, for the log (default: the report's name)")
    ap.add_argument("--print-baseline", action="store_true")
    args = ap.parse_args(argv)
    label = args.label or args.report.name
    github = env.get("GITHUB_ACTIONS") == "true"

    try:
        report = _load_report(args.report)
        findings = pip_findings(report) if args.kind == "pip" else pnpm_findings(report)
        floor = None if args.kind == "pip" else args.min_severity
        if args.print_baseline:
            keep = [f for f in findings if floor is None or SEVERITIES.index(f.severity) >= SEVERITIES.index(floor)]
            sys.stdout.write(render_baseline(keep))
            return 0
        baseline = read_baseline(args.baseline.read_text(encoding="utf-8"))
    except (AuditError, OSError) as exc:
        print(f"{'::error title=Dependency audit did not run::' if github else 'ERROR '}{label}: {exc}")
        return 2

    v = judge(findings, baseline, floor)
    scope = "any advisory" if floor is None else f"{floor} and above"
    print(f"{label}: {len(findings)} advisories ({scope} counted) · {len(v.accepted)} in the baseline · "
          f"{len(v.new)} NEW · {len(v.below)} below the threshold · {len(v.stale)} stale baseline lines")
    for f in v.new:
        line = (f"{f.package} {f.version}: {f.primary}" + (f" [{f.severity}]" if f.severity else "") +
                f" — {f.title} (fix: {f.fix}). Upgrade, or add {f.primary} to the baseline with the reason.")
        print(f"::error title=New vulnerable dependency::{label}: {line}" if github else f"NEW  {line}")
    if v.stale:
        msg = f"{label}: these baseline lines match no current advisory — delete them: {', '.join(v.stale)}"
        print(f"::notice title=Stale audit baseline::{msg}" if github else f"NOTE {msg}")

    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        rows = [f"| {f.package} {f.version} | {f.primary} | {f.severity or 'n/a'} | {f.fix} |" for f in v.new]
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join([
                f"### Dependency audit — {label}",
                f"{len(findings)} advisories · **{len(v.new)} new** · {len(v.accepted)} accepted in the baseline "
                f"(known, unpatched exposures that may only shrink) · {len(v.stale)} stale",
                *(["", "| package | advisory | severity | fix |", "|---|---|---|---|", *rows] if rows else []),
                "",
            ]))
    return 1 if v.new else 0


if __name__ == "__main__":
    raise SystemExit(main())
