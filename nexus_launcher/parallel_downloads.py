"""Bounded scheduling of independent staging jobs, never installation writes."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import deque


def run_staged(items, work, host, *, workers=3, per_host=2):
    if not 1 <= workers <= 4 or not 1 <= per_host <= workers:
        raise ValueError('Invalid download concurrency')
    groups = {}
    for item in items:
        groups.setdefault(host(item), deque()).append(item)
    hosts = deque(groups)
    results = []
    active = {}
    counts = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='nexus-download') as pool:
        try:
            while any(groups.values()) or active:
                while len(active) < workers:
                    key = next((key for key in hosts if groups[key] and counts.get(key, 0) < per_host), None)
                    if key is None:
                        break
                    item = groups[key].popleft()
                    hosts.rotate(-1)
                    counts[key] = counts.get(key, 0) + 1
                    active[pool.submit(work, item)] = key
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                # Check all completed results before scheduling any more work.
                for future in done:
                    key = active.pop(future)
                    counts[key] -= 1
                    results.append(future.result())
        except BaseException:
            for future in active:
                future.cancel()
            # Executor joins started downloads before the caller can recover
            # or remove staging. No worker may outlive this operation.
            raise
    return results
