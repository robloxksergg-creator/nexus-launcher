import io

import pytest
from nexus_launcher.resource_limits import copy_limited, read_limited


@pytest.mark.parametrize("copy", [False, True])
def test_slow_drip_has_total_deadline(monkeypatch, copy):
    clock = [0]
    monkeypatch.setattr("nexus_launcher.resource_limits.time.monotonic", lambda: clock[0])

    class Drip:
        def read(self, _size):
            raise AssertionError("Buffered read must not be used")

        def read1(self, _size):
            clock[0] += 2
            return b"x"

    with pytest.raises(TimeoutError):
        if copy:
            copy_limited(Drip(), io.BytesIO(), timeout=3)
        else:
            read_limited(Drip(), timeout=3)
    assert clock[0] <= 4
