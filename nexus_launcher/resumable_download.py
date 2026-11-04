"""Bounded anonymous download retries; origin policy remains with the caller.

Only a caller-owned temporary file may be passed. No final installation path
is modified. A completed transfer still needs the caller's signed hash check.
"""
import http.client
import re
import ssl
import time
import urllib.error


def receive(output, open_response, *, size, limit, progress, timeout=1800, attempts=3):
    if type(size) is not int or type(limit) is not int or not 0 <= size <= limit or limit <= 0:
        raise ValueError('Invalid download size')
    deadline = time.monotonic() + timeout
    output.seek(0)
    output.truncate()
    done = 0
    for attempt in range(attempts):
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError('Download time budget exceeded')
            with open_response(done) as response:
                status = getattr(response, 'status', 200)
                headers = getattr(response, 'headers', {})
                content_range = headers.get('Content-Range', '')
                if done and status == 206:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range)
                    if (not match or int(match[1]) != done or int(match[2]) < done
                            or int(match[3]) > limit or int(match[2]) >= int(match[3])
                            or size and int(match[3]) != size):
                        raise ValueError('Invalid download range')
                elif status == 200:
                    # Range ignored (or no range requested): never append a full body.
                    done = 0
                    output.seek(0)
                    output.truncate()
                else:
                    raise ValueError('Unexpected download response')
                length = headers.get('Content-Length')
                expected = size
                if length is not None:
                    if not str(length).isascii() or not str(length).isdigit():
                        raise ValueError('Invalid download length')
                    length = int(length)
                    if done + length > limit or size and done + length != size:
                        raise ValueError('Download size mismatch')
                    expected = size or done + length
                read = getattr(response, 'read1', response.read)
                progress(done, expected)
                while True:
                    block = read(min(256 * 1024, limit - done + 1))
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Download time budget exceeded')
                    if not block:
                        break
                    if done + len(block) > limit or expected and done + len(block) > expected:
                        raise ValueError('Download exceeds byte limit')
                    output.write(block)
                    done += len(block)
                    progress(done, expected)
                if expected and done != expected:
                    raise http.client.IncompleteRead(b'', expected - done)
                output.flush()
                return done
        except (OSError, urllib.error.URLError, http.client.IncompleteRead) as error:
            # Certificate failures, HTTP refusals and exhausted budgets are not
            # reasons to weaken validation, switch host or retry indefinitely.
            reason = getattr(error, 'reason', error)
            if (isinstance(reason, ssl.SSLError)
                    or isinstance(error, urllib.error.HTTPError) and error.code not in {408, 429, 500, 502, 503, 504}
                    or attempt + 1 == attempts or time.monotonic() >= deadline):
                raise
            output.flush()
    raise RuntimeError('Unreachable download state')
