import threading
import time

import pytest

from nexus_launcher.parallel_downloads import run_staged


def test_bounded_parallelism_and_per_origin_limit():
    lock = threading.Lock()
    active = {}
    peak, host_peak = [0], {}
    barrier = threading.Barrier(3)
    started = [0]
    def work(item):
        host, index = item
        with lock:
            active[host] = active.get(host, 0) + 1
            peak[0] = max(peak[0], sum(active.values()))
            host_peak[host] = max(host_peak.get(host, 0), active[host])
            started[0] += 1
            first = started[0] <= 3
        if first: barrier.wait(timeout=3)
        time.sleep(.005)
        with lock: active[host] -= 1
        return item
    items = [('a', i) for i in range(8)] + [('b', i) for i in range(8)]
    assert sorted(run_staged(items, work, lambda x: x[0])) == sorted(items)
    assert peak[0] == 3
    assert all(n <= 2 for n in host_peak.values())
    assert sum(active.values()) == 0


def test_failure_joins_started_workers_before_caller_can_apply_or_recover():
    running = threading.Event()
    exited = threading.Event()
    def work(item):
        if item == 0:
            assert running.wait(2)
            raise ValueError('synthetic hash mismatch')
        running.set()
        time.sleep(.03)
        exited.set()
        return item
    with pytest.raises(ValueError, match='hash mismatch'):
        run_staged([0, 1], work, lambda _: 'same', workers=2, per_host=2)
    assert exited.is_set()


def test_empty_and_invalid_configuration():
    assert run_staged([], lambda _: pytest.fail('unexpected job'), str) == []
    with pytest.raises(ValueError): run_staged([], str, str, workers=100)
