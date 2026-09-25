"""Client health scoring — the rules, separate from the router that serves them.

`scoring` holds Product Bible Chapter 16's weights, bands and composite; the
router re-exports them, the same shape `domain/fixed_assets/schedule_ii.py`
took when Schedule II Part C moved out of `routers/fixed_assets.py`. A domain
module must not import a router, and a service reaching through one for a
table of constants is one refactor away from a cycle.

`overrides` is the manual correction a CA records against a dimension.
"""
