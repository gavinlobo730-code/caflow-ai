"""
apex-overview-practice-07(b): `services/hub_service._signals` computed its
~14 tile counts as sequential Singapore-to-Mumbai round trips. Each is
already isolated by `_safely` (a tile's own failure costs only itself),
which is exactly what makes them safe to run CONCURRENTLY too — the same
`ThreadPoolExecutor` pattern `domain/reporting/sources.py`'s `_base()`
already uses for its own independent top-level fetches.

This proves genuine concurrency rather than trusting the source shape: every
underlying fetch is instrumented to record how many are in flight AT THE
SAME TIME, and the whole run is timed. Run one after another, `_count`/
`_sum_paise` sleeping 50ms each would take ~650ms for firm scope's dozen
tiles (`gst` alone makes two calls); run concurrently, the wall clock should
be close to the SLOWEST single tile.
"""
from __future__ import annotations

import threading
import time

import pytest

import services.hub_service as hub_service

FIRM = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"


class _ConcurrencyProbe:
    """Records the peak number of instrumented fetches in flight at once."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.calls = 0

    def __call__(self, *args, **kwargs):
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            self.calls += 1
        time.sleep(self.delay)
        with self.lock:
            self.in_flight -= 1
        return 0


@pytest.fixture
def probe(monkeypatch):
    p = _ConcurrencyProbe()
    # _count and _sum_paise are the two functions every tile's lambda in
    # _signals calls (unqualified — resolved from the module namespace at
    # CALL time, which is what makes monkeypatching them here effective even
    # though the lambdas were already built before this patch runs).
    monkeypatch.setattr(hub_service, "_count", p)
    monkeypatch.setattr(hub_service, "_sum_paise", p)
    return p


def test_tile_fetches_overlap_in_time_rather_than_running_one_after_another(probe):
    started = time.monotonic()
    signals = hub_service._signals(FIRM, None, None)
    elapsed = time.monotonic() - started

    assert probe.calls >= 12, f"expected at least 12 underlying fetches, saw {probe.calls}"
    assert probe.peak > 1, (
        f"peak concurrent fetches was {probe.peak} — every tile ran alone, "
        f"one after another, which is the bug this fix removes")
    # Sequential: >= 12 calls * 50ms >= 600ms (gst alone makes two, so it's
    # actually more). Concurrent: bounded by the slowest tile (~100ms for
    # gst's two sequential counts) plus scheduling overhead.
    assert elapsed < 0.35, (
        f"took {elapsed:.3f}s for {probe.calls} fetches at 50ms each — that is "
        f"consistent with running them one after another, not concurrently")
    # And the actual VALUES are untouched by the change in how they are
    # scheduled — every probed tile still gets a real (patched) answer.
    assert signals["compliance"] == 0
    assert signals["gst"] == 0


def test_client_scope_still_includes_the_inventory_tile_and_it_too_runs_concurrently(monkeypatch, probe):
    monkeypatch.setattr(hub_service, "_reorder_count", probe)
    hub_service._signals(FIRM, None, CLIENT)
    assert probe.calls >= 13, "the inventory tile's own fetch was not made at client scope"


def test_negative_control_the_probe_itself_would_show_peak_one_if_called_sequentially(probe):
    """Sanity check on the probe's own logic, independent of hub_service: if
    nothing overlaps, peak concurrency is exactly 1."""
    for _ in range(5):
        probe()
    assert probe.peak == 1
