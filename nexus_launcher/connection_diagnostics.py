"""Bounded credential-free account transport probes; never requests an email."""
import socket
import ssl
import sys
from pathlib import Path


def transport_failure(error):
    cause = error.__cause__ or error
    reason = getattr(cause, "reason", cause)
    if isinstance(reason, ssl.SSLCertVerificationError):
        category = "TLS_CERTIFICATE"
    elif isinstance(reason, ssl.SSLError):
        category = "TLS"
    elif isinstance(reason, socket.gaierror):
        category = "DNS"
    elif isinstance(reason, TimeoutError):
        category = "TIMEOUT"
    elif isinstance(reason, PermissionError) or getattr(reason, "winerror", None) == 10013:
        category = "CONNECTION_DENIED"
    elif isinstance(reason, OSError):
        category = "CONNECTION"
    else:
        category = "UNCLASSIFIED"
    result = {"category": category, "exception_type": type(error).__name__,
              "cause_type": type(reason).__name__}
    frames = []
    traceback = getattr(reason, "__traceback__", None)
    while traceback is not None and len(frames) < 12:
        code = traceback.tb_frame.f_code
        frames.append({"file": Path(code.co_filename).name, "function": code.co_name, "line": traceback.tb_lineno})
        traceback = traceback.tb_next
    result["frames"] = frames
    for name in ("errno", "winerror", "verify_code"):
        value = getattr(reason, name, None)
        if type(value) is int:
            result[name] = value
    return result


def probe_account_connection():
    from nexus_launcher.nexus_account import AccountError, NexusAccountClient
    from nexus_launcher.secure_http import origin
    client = NexusAccountClient(timeout=15)
    result = {"frozen": bool(getattr(sys, "frozen", False)), "host": origin(client.base_url)[1],
              "credentials_sent": False, "email_requested": False, "probes": []}
    try:
        result["certificate_store"] = ssl.create_default_context().cert_store_stats()
    except OSError as error:
        result["certificate_store"] = "UNAVAILABLE"
        result["certificate_error"] = transport_failure(error)
    result["windows_stores"] = {}
    if sys.platform == "win32":
        for name in ("CA", "ROOT"):
            try:
                result["windows_stores"][name] = {"count": len(ssl.enum_certificates(name))}
            except OSError as error:
                result["windows_stores"][name] = {"error": type(error).__name__, "winerror": getattr(error, "winerror", None)}
    # No cookie, bearer, device ID, email or password. The deliberately empty
    # POST validates the existing route; it cannot identify a mail recipient.
    for path, method, payload, expected in [
        ("/api/launcher/profile", "GET", None, 401),
        ("/api/auth/email/request-code", "POST", {}, 400),
    ]:
        probe = {"path": path, "method": method, "expected_status": expected}
        try:
            client._request(path, method=method, payload=payload)
            probe["result"] = "UNEXPECTED_SUCCESS"
        except AccountError as error:
            probe.update(status=error.http_status, outcome=error.outcome)
            if error.http_status is not None:
                probe["result"] = "EXPECTED_RESPONSE" if error.http_status == expected else "UNEXPECTED_RESPONSE"
            else:
                probe.update(result="TRANSPORT_FAILURE", failure=transport_failure(error))
        result["probes"].append(probe)
    return result
