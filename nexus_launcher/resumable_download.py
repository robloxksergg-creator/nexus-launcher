"""Bounded anonymous download retries; origin policy remains with the caller.

Only a caller-owned temporary file may be passed. No final installation path
is modified. A completed transfer still needs the caller's signed hash check.
"""
import http.client
import math
import re
import ssl
import time
import urllib.error
from datetime import UTC,datetime
from email.utils import parsedate_to_datetime


def _header(headers,name):
    values=getattr(headers,'get_all',lambda _:None)(name)
    if values and len(values)!=1:
        raise ValueError('Ambiguous download header')
    return headers.get(name,headers.get(name.lower()))


def _retry_wait(error,attempt,base,deadline):
    delay=min(base*(2**attempt),8)
    if isinstance(error,urllib.error.HTTPError):
        value=_header(error.headers or {},'Retry-After')
        if value:
            try:
                if len(value)>128:raise ValueError('Invalid retry hint')
                if value.isascii() and value.isdigit():requested=int(value)
                else:
                    date=parsedate_to_datetime(value)
                    if date.tzinfo is None:raise ValueError('Ambiguous retry date')
                    requested=max(0,(date-datetime.now(UTC)).total_seconds())
                # Do not hammer an origin that asked for a longer wait, nor sleep indefinitely.
                if requested>60:raise TimeoutError('Server retry delay exceeds policy')
                delay=max(delay,requested)
            except (ValueError,TypeError,OverflowError):pass
    if delay>=deadline-time.monotonic():raise TimeoutError('Download time budget exceeded')
    if delay:time.sleep(delay)


def receive(output, open_response, *, size, limit, progress, timeout=1800, attempts=3,retry_delay=.5):
    if type(size) is not int or type(limit) is not int or not 0 <= size <= limit or limit <= 0:
        raise ValueError('Invalid download size')
    if (type(attempts) is not int or not 1<=attempts<=8
            or type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<=timeout<=3600
            or type(retry_delay) not in (int,float) or not math.isfinite(retry_delay) or not 0<=retry_delay<=8):
        raise ValueError('Invalid download retry budget')
    deadline = time.monotonic() + timeout
    output.seek(0)
    output.truncate()
    done = 0
    for attempt in range(attempts):
        network_step=False
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError('Download time budget exceeded')
            network_step=True
            with open_response(done) as response:
                network_step=False
                status = getattr(response, 'status', 200)
                headers = getattr(response, 'headers', {})
                if _header(headers,'Content-Encoding') not in (None,'','identity'):
                    raise ValueError('Encoded download body is forbidden')
                content_range = _header(headers,'Content-Range') or ''
                end=None
                expected=size
                if done and status == 206:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range)
                    if (not match or int(match[1]) != done or int(match[2]) < done
                            or int(match[3]) > limit or int(match[2]) >= int(match[3])
                            or size and int(match[3]) != size):
                        raise ValueError('Invalid download range')
                    expected=size or int(match[3])
                    end=int(match[2])+1
                elif status == 200:
                    if content_range:raise ValueError('Unexpected full-response range')
                    # Range ignored (or no range requested): never append a full body.
                    done = 0
                    output.seek(0)
                    output.truncate()
                else:
                    raise ValueError('Unexpected download response')
                length = _header(headers,'Content-Length')
                if length is not None:
                    if len(str(length))>20 or not str(length).isascii() or not str(length).isdigit():
                        raise ValueError('Invalid download length')
                    length = int(length)
                    if done + length > limit or (end is not None and done+length!=end) or (status==200 and size and length!=size):
                        raise ValueError('Download size mismatch')
                    if end is None:end=done+length
                    expected = expected or end
                read = getattr(response, 'read1', response.read)
                progress(done, expected)
                while True:
                    network_step=True
                    block = read(min(256 * 1024,(end if end is not None else limit)-done+1))
                    network_step=False
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Download time budget exceeded')
                    if not block:
                        break
                    if done + len(block) > limit or expected and done + len(block) > expected or end is not None and done+len(block)>end:
                        raise ValueError('Download exceeds byte limit')
                    if output.write(block)!=len(block):raise OSError('Short write to download cache')
                    done += len(block)
                    progress(done, expected)
                if expected and done != expected:
                    network_step=True
                    raise http.client.IncompleteRead(b'', expected - done)
                output.flush()
                return done
        except (OSError, urllib.error.URLError, http.client.IncompleteRead) as error:
            # Certificate failures, HTTP refusals and exhausted budgets are not
            # reasons to weaken validation, switch host or retry indefinitely.
            reason = getattr(error, 'reason', error)
            if isinstance(error,urllib.error.HTTPError):error.close()
            if (not network_step or isinstance(reason, ssl.SSLError)
                    or isinstance(error, urllib.error.HTTPError) and error.code not in {408, 429, 500, 502, 503, 504}
                    or attempt + 1 == attempts or time.monotonic() >= deadline):
                raise
            output.flush()
            _retry_wait(error,attempt,retry_delay,deadline)
    raise RuntimeError('Unreachable download state')
