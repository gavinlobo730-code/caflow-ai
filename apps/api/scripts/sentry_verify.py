#!/usr/bin/env python3
"""Send one test posting failure and one test soft failure to Sentry, the way the product would (ops-10).

    SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project> \\
        python3 scripts/sentry_verify.py --send --environment staging

WHAT IT IS FOR. "Confirm backend Sentry is on and that the alert rules fire" needs a failure to fire them
with, and waiting for a real posting to fail is the wrong way to find out the rule is wrong. This goes
through `core.observability` — the same two functions every fail-soft call site uses, the same `init_error_reporting`
main.py starts — so what arrives in Sentry is what a real swallowed failure looks like: tagged
`posting_operation` / `soft_operation`, tagged `firm_id` and `source_id`, fingerprinted by operation. If it
arrives WITHOUT those tags the rules cannot match, which is the defect `core/observability.py` records.

IT IS A DRY RUN UNTIL `--send`, as `seed_demo_firm.py` is, because the event is indistinguishable from a real
one and is MEANT to trip the rule — a person may be paged. Without `--send` it prints what it would send and
to which project, and touches nothing.

`--environment` defaults to `production` (what Render runs), so run it with `staging` first unless a page is
what you are testing. The operation is `sentry_verification`, the firm is `verification`: a rule that should
stay quiet for a test can filter on either; a rule being TESTED must not.

It needs `SENTRY_DSN` in the environment of whoever runs it. The dashboard value lives in Render, which the
repository cannot read, and this script does not ask for it on the command line: a DSN in shell history is a
credential in shell history.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Callable, Optional

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

import sentry_sdk  # noqa: E402

from core import observability as obs  # noqa: E402

OPERATION = "sentry_verification"


def _project_of(dsn: str) -> str:
    """The DSN without its public key — enough to tell which project a run will hit."""
    return re.sub(r"//[^@/]+@", "//<key>@", dsn)


def main(argv: Optional[list[str]] = None, env: Optional[dict] = None,
         transport: Optional[Callable] = None) -> int:
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--send", action="store_true", help="actually send; without it this is a dry run")
    ap.add_argument("--environment", default=env.get("ENVIRONMENT", "production"),
                    help="the Sentry environment tag (default: $ENVIRONMENT, else production)")
    args = ap.parse_args(argv)

    dsn = env.get("SENTRY_DSN", "").strip()
    if not dsn:
        print("SENTRY_DSN is not set in this shell. That is also what an unconfigured Render service looks "
              "like: swallowed financial-posting failures reach its log stream only.")
        return 2

    print(f"Target: {_project_of(dsn)} (environment {args.environment!r})")
    print(f"Would send: a posting failure and a soft failure, operation {OPERATION!r}, firm 'verification'.")
    if not args.send:
        print("Dry run. Nothing was sent. Re-run with --send.")
        return 0

    obs.init_error_reporting(dsn, environment=args.environment, transport=transport)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for report, label in ((obs.capture_posting_failure, "posting"), (obs.capture_soft_failure, "soft")):
        try:
            raise RuntimeError(f"Sentry verification ({label}) — not a real failure, sent by scripts/sentry_verify.py")
        except RuntimeError as exc:
            report(exc, operation=OPERATION, firm_id="verification", client_id="verification",
                   source_type="verification", source_id=stamp)
    # flush() returns nothing; a timeout is logged by the SDK. Delivery is confirmed in Sentry, not here.
    sentry_sdk.flush(timeout=10)
    print(f"Sent two events, source_id {stamp}. In Sentry look for operation {OPERATION!r} carrying the tags "
          "posting_operation / soft_operation, firm_id, source_id. No tags means no rule can match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
