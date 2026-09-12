"""Fixed assets: the statutory table, and the rules that read it.

Schedule II to the Companies Act 2013 is data, and where a register departs
from it is a rule over that data. Neither needs a database, and both are read
from more than one place — `routers/fixed_assets.py` serves the table to the
Add Asset form and reports the departures on demand, and
`services/reconciliation_service.py` runs the same checks in the nightly sweep.
They live here so those two read one copy.
"""
