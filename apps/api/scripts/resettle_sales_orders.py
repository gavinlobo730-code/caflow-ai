#!/usr/bin/env python3
"""Derive the status of every live sales order again, once (ledger POST-A-421, part c).

    python3 scripts/resettle_sales_orders.py --firm <firm id> [--client <client id>]            # a dry run: lists what would change
    python3 scripts/resettle_sales_orders.py --firm <firm id> [--client <client id>] --apply    # writes it

WHY. An order the old rule left `delivered` or `partially_delivered` (by a challan whose goods were marked received back, or a word a
person set) keeps that status until a challan on it is next issued, cancelled or marked back, when it is derived again. The rule that derives
it is Python, so this is a data step and not a migration: it reads each live order through the same position the screens read and writes
the status the position says, through the same writer. `closed` and `cancelled` orders are decisions and are not touched.

IT IS A DRY RUN UNTIL `--apply`, as `seed_demo_firm.py` is. It writes to whichever database the environment names (SUPABASE_URL and the
service key), so look at the dry run first. Nothing runs it by itself, and it has not been run against production.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--firm", required=True)
    parser.add_argument("--client")
    parser.add_argument("--apply", action="store_true", help="write the statuses; without it nothing is written")
    args = parser.parse_args(argv)
    from core.supabase_client import get_service_supabase
    from services import sales_cycle_service

    changes = sales_cycle_service.orders_whose_status_would_change(get_service_supabase(), args.firm, args.client, apply=args.apply)
    for c in changes:
        print(f"{c['document_no']}: {c['from']} -> {c['to']}  (order {c['order_id']}, client {c['client_id']})")
    print(f"{len(changes)} order(s) {'changed' if args.apply else 'would change (dry run; pass --apply to write)'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
