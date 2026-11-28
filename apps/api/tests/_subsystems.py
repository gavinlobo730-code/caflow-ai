"""Which part of the product a test file is about (POST-A-191, the first half, done without moving a file).

THE QUESTION THIS ANSWERS. `tests/` holds about 1,800 test files in one directory. Each is named for the behaviour it holds, which says what
ONE file is about and nothing about which files belong together: "run the payroll tests" and "which tests are about TDS?" had no answer but
reading the listing. The finding asked for subsystem folders.

WHY THE FILES WERE NOT MOVED. Moving 1,800 files one level down was measured on 28-11-2026 and decided against, for three reasons that are
about safety and not effort:
  - about a thousand of them find the application through their own path (`Path(__file__).resolve().parents[1]` and a dozen other spellings).
    A guard that scans `routers/` from a path that is now one level wrong finds NOTHING, and a guard that finds nothing passes: the move would
    not break those tests, it would silently empty them. Some carry a floor against that and many do not;
  - 108 applied migrations cite a test by its path in their comments, and an applied migration is never edited, not even a comment
    (POST-A-583 was a rename doing exactly that: it changed their bytes, the runner applied six of them a second time, and production's
    ledger posting function went back to an old definition);
  - the real-Postgres job of the required checks collects its files with a shell glob one level deep; a glob that misses after a move
    collects fewer tests and reports success.
So the grouping is this module: a file's subsystem is DERIVED from what it imports and what it is called, and nothing is listed by hand.

HOW IT IS USED
    pytest tests --subsystem payroll              the payroll tests, and only them
    pytest tests --subsystem gst,tds              two together
    python3 scripts/tests_by_subsystem.py         how many files each holds
    python3 scripts/tests_by_subsystem.py tds     the files of one

WHAT IT IS AND IS NOT. A way to find and run related tests. It is a judgement read off names and imports, so a file about two things sits in
one of them (the first rule that scores highest), and a file no rule reaches is `other` (a real-Postgres file, `database`). It is NOT a
boundary and nothing may be skipped in the required checks because of it: CI runs every file, always.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

#: (subsystem, the application modules that say so when a test imports them, the words in the file's own name that say so). ORDER MATTERS:
#: a tie goes to the earlier line, so the narrower subject comes first.
RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("payroll", ("domain.payroll", "routers.payroll", "services.payroll", "routers.employee", "services.employee_portal", "services.payslip"),
     ("payroll", "payslip", "salary", "employee", "epf", "esi_", "gratuity", "ecr", "form_16", "leave_", "attendance", "wage", "bonus")),
    ("gst", ("domain.gst", "routers.gst", "services.gst", "routers.einvoice", "routers.eway", "services.itc", "services.rule_37"),
     ("gst", "gstr", "itc", "irn", "eway", "e_way", "hsn", "uqc", "place_of_supply", "reverse_charge", "rcm", "cess", "rule_37", "rule_43")),
    ("tds", ("domain.tds", "routers.tds", "services.tds", "services.vendor_tds", "routers.form_26as"),
     ("tds", "tcs", "26as", "26q", "24q", "27q", "deductor", "section_194", "section_195", "194", "206a", "lower_deduction")),
    ("income_tax", ("domain.income_tax", "routers.itr", "routers.income_tax", "services.itr", "routers.capital_gains", "routers.tax_audit"),
     ("itr", "income_tax", "capital_gain", "3cd", "tax_audit", "advance_tax", "140a", "115bac", "regime", "house_property", "brought_forward",
      "carried_forward", "44a", "43b", "234")),
    ("banking", ("domain.banking", "routers.banking", "routers.bank", "services.bank", "services.reconciliation", "services.post_dated_cheque"),
     ("bank", "cheque", "reconcil", "matching_rule", "credit_card")),
    ("inventory_and_assets", ("domain.inventory", "routers.inventory", "services.inventory", "services.stock", "routers.fixed_assets",
                              "services.fixed_asset", "domain.fixed_assets", "services.depreciation", "services.section_32"),
     ("stock", "inventory", "godown", "batch", "asset", "depreciation", "cwip", "landed_cost", "reorder")),
    ("documents", ("routers.sales_invoices", "routers.purchase_bills", "routers.credit_notes", "routers.debit_notes", "routers.receipts",
                   "routers.purchase_payments", "services.receipt", "services.purchase_payment", "routers.customers", "routers.vendors",
                   "services.sales_cycle", "services.purchase_cycle", "routers.sales_debit_notes", "routers.purchase_credit_notes",
                   "services.party_credit", "services.invoice", "services.customer_statement", "services.vendor_statement"),
     ("invoice", "bill", "receipt", "payment", "credit_note", "debit_note", "customer", "vendor", "supplier", "quote", "sales_order",
      "purchase_order", "delivery_challan", "party_credit", "statement", "price_list", "recurring")),
    ("ledger_and_reports", ("services.phase2_journal", "domain.reporting", "routers.accounting", "services.period_lock", "services.year_end",
                            "routers.year_end", "services.opening_balance", "services.trial_balance", "domain.accounting", "services.reversal",
                            "services.ledger_door", "services.report"),
     ("journal", "ledger", "posting", "trial_balance", "balance_sheet", "profit", "cash_flow", "schedule_iii", "ageing", "aging", "year_end",
      "year_lock", "period", "opening", "voucher", "day_book", "multi_currency", "fx_", "currency", "paise", "rupee", "money", "report")),
    ("compliance_and_filing", ("services.compliance", "routers.compliance", "services.filing_demo", "routers.filing", "routers.mca",
                               "services.mca", "domain.filing"),
     ("compliance", "filing", "filed", "obligation", "deadline", "mca", "xbrl", "dsc", "due_date", "calendar")),
    ("ai", ("domain.ai", "routers.ai", "services.groq", "routers.assistant", "routers.document_intelligence", "services.ai", "routers.health",
            "services.health"),
     ("ai_", "_ai", "copilot", "assistant", "model_call", "groq", "gemini", "extraction", "redact", "insight", "health_score", "health")),
    ("security_and_tenancy", ("core.auth", "core.authz", "core.permissions", "core.platform_auth", "core.portal_auth", "middleware.rate_limit",
                              "services.audit_service", "services.user_permission"),
     ("rls", "tenan", "firm_scope", "another_firm", "cross_tenant", "signed_in", "privileged", "permission", "rbac", "mfa", "auth", "audit",
      "scope", "assignment", "grant", "policy", "policies", "session", "token", "pin", "portal", "upload", "storage", "secur",
      "who_is_calling", "written_by_the_api", "access", "rate_limit", "definer")),
    ("practice", ("routers.tasks", "routers.engagement", "routers.billing", "routers.time", "routers.lifecycle", "routers.knowledge",
                  "routers.workflow", "domain.workflow", "routers.relationships", "routers.notifications", "services.email",
                  "domain.tally", "routers.clients"),
     ("task", "engagement", "retainer", "lead", "pipeline", "time_", "knowledge", "workflow", "relationship", "notification", "mail", "email",
      "team", "practice", "internal_client", "client", "onboarding", "digest", "dashboard", "tally", "import", "export")),
    ("platform_and_ci", ("core.schema_guard", "jobs.scheduler", "core.ist_clock"),
     ("ci_", "_ci", "migration", "schema", "lint", "ruff", "coverage", "render", "docker", "deploy", "scheduler", "boot", "requirements",
      "dependency", "open_items", "design_record", "claude_md", "named_in_a_test", "file_in_tests", "file_is_named", "frontend", "browser", "marketing", "smoke", "pdf",
      "sentry", "log", "request_id", "header", "indian_day", "ist_", "utc", "date", "fy_", "ay_", "layers", "worker", "lock")),
]

SUBSYSTEMS: tuple[str, ...] = tuple(name for name, _, _ in RULES) + ("database", "other")


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def subsystem_from(name: str, imports: set[str]) -> str:
    """The rule itself, on a file's name (without `test_` and `.py`) and the modules it imports. A word in the name weighs more than an import:
    the name is what the author said the file is about, and an import is only what it had to reach."""
    scores: dict[str, int] = {}
    for subsystem, modules, words in RULES:
        score = 3 * sum(1 for word in words if word in name)
        score += 2 * sum(1 for module in modules if any(i == module or i.startswith(module) for i in imports))
        if score:
            scores[subsystem] = score
    if not scores:
        return "database" if name.endswith("_pg") else "other"
    best = max(scores.values())
    return next(subsystem for subsystem, _, _ in RULES if scores.get(subsystem) == best)


@functools.lru_cache(maxsize=None)
def subsystem_of(path: str) -> str:
    """The subsystem of one test file, by its path. Read once per file for the life of the process."""
    p = Path(path)
    stem = p.stem[len("test_"):] if p.stem.startswith("test_") else p.stem
    return subsystem_from(stem, _imports(p))


def files_of(tests_dir: Path) -> list[Path]:
    """Every test file of the directory (named so pytest does not take THIS function for a test where it is imported)."""
    return sorted(tests_dir.glob("test_*.py"))


def wanted(option: str) -> set[str]:
    """`--subsystem gst,tds` as a set, refusing a name that is not one (a typo that selected nothing would read as a clean run)."""
    asked = {part.strip() for part in option.split(",") if part.strip()}
    unknown = asked - set(SUBSYSTEMS)
    if unknown or not asked:
        raise ValueError(f"--subsystem takes one or more of {', '.join(SUBSYSTEMS)} (comma-separated); got {option!r}")
    return asked
