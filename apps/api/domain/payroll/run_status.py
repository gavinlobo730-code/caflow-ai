"""Which payroll runs COUNT, and which have not yet paid anybody.

MOVED OUT OF `routers/payroll.py`, and the move is the point (PR 2, 25-09).
Both tuples lived in the router, so `services/client_metrics_service.py` —
which has to know that a draft has paid nobody before it puts a month of salary
into a benchmark of employment cost — could only reach them by importing a
router. That is the wrong direction and one refactor from a cycle; it is the
same reason Schedule II Part C moved out of `routers/fixed_assets.py` and
`compute_line_gst` moved to `domain/sales/line_tax.py`. The router re-exports
both names, so every existing importer and the test that pins the pair are
untouched.

⚠️ `_PAYROLL_UNRELEASED` IS NOT THE INVERSE OF `RELEASED`, and writing either
as "not the other" is the thing not to do. They answer different questions —
which runs COUNT, and which have not yet paid anybody — and a fifth status
would silently join both.
"""
from __future__ import annotations

#: The released statuses. `tds_return_service` names the same pair
#: `_PAYROLL_POSTED`; the ECR, the ESIC return, Form 16 and the 24Q all refuse
#: anything outside it, and migration 323 made RLS agree.
#:
#: PAY-04 is why every reader has to ask: a DRAFT run has deducted nothing, so
#: reading one credits an employee with §192 tax nobody withheld and keeps
#: somebody in ESI past the ₹21,000 ceiling on a contribution that never
#: happened.
PAYROLL_RELEASED: tuple[str, ...] = ("finalized", "paid")

#: The statuses a run may be REBUILT or thrown away in (PAY-21). Its own tuple,
#: never `not RELEASED` — see the module docstring.
PAYROLL_UNRELEASED: tuple[str, ...] = ("draft", "review")
