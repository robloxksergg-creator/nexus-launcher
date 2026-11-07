"""Opt-in, schema-only support reports. No Telegram credential in the client."""
import hashlib
import re
import sys
import threading
import time


def failure_code(text):
    # Raw exception text is used only for classification and never retained/sent.
    value = str(text)[:16384]
    if 'GAME_TICKET_UNAVAILABLE' in value:
        return 'GAME_TICKET_UNAVAILABLE'
    if 'IncompleteRead' in value or 'DOWNLOAD_INTERRUPTED' in value:
        return 'DOWNLOAD_INTERRUPTED'
    if 'maven.neoforged.net' in value and any(x in value.lower() for x in ('timeout', 'timed out', 'connectionpool')):
        return 'NEOFORGE_UNAVAILABLE'
    return 'LAUNCH_FAILED'


class FailureReporter:
    """One worker, three distinct reports/hour; unknown writes never loop/retry.

    Server-side support limits and deterministic idempotency also apply across
    process restarts. An accepted ticket is NOT proof of Telegram delivery.
    """
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.seen = set()
        self.hour = None
        self.busy = False
        self.state = 'NOT_SENT'

    def submit(self, client, profile, text, version, *, enabled=False, allowed=lambda: True):
        if enabled is not True or profile is None:
            return False
        account = profile.user_id
        token = client.support_session(account)
        if not token:
            return False
        code = failure_code(text)
        version = version if isinstance(version, str) and re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,6}){2}', version) else 'unknown'
        platform = {'win32': 'windows', 'darwin': 'macos', 'linux': 'linux'}.get(sys.platform, 'other')
        hour = int(self.clock() // 3600)
        with self.lock:
            if self.hour != hour:
                self.hour, self.seen = hour, set()
            if self.busy or code in self.seen or len(self.seen) >= 3:
                return False
            self.seen.add(code)
            self.busy = True
            self.state = 'SENDING'
        idem = hashlib.sha256(f'launcher-diagnostic:{account}:{hour}:{version}:{code}'.encode()).hexdigest()
        payload = {'subject': 'NEXUS: ' + code, 'category': 'launcher_diagnostic',
                   'text': f'code={code}\nversion={version}\nplatform={platform}\nSchema-only automatic report; no logs attached.'}

        def work():
            try:
                if not allowed() or client.support_session(account) != token:
                    self.state = 'CANCELLED'
                    return
                result, _ = client._request('/api/v1/support/tickets', method='POST',
                    payload=payload, token=token, idempotency_key=idem)
                self.state = ('SAVED_TO_SUPPORT_QUEUE' if isinstance(result, dict)
                              and re.fullmatch(r'[a-f0-9]{64}', str(result.get('id', '')))
                              else 'UNKNOWN')
            except Exception:
                self.state = 'UNKNOWN'  # May have committed; no automatic resend.
            finally:
                with self.lock:
                    self.busy = False
        threading.Thread(target=work, name='nexus-failure-report', daemon=True).start()
        return True
