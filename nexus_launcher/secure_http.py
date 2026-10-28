"""HTTPS transport with explicit origin policy (including every redirect)."""

import urllib.parse
import urllib.request


def origin(url: str) -> tuple[str, str, int]:
    parts = urllib.parse.urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.fragment
        or parts.port not in (None, 443)
    ):
        raise ValueError("Only HTTPS without credentials on port 443 is allowed")
    return "https", parts.hostname.lower(), 443


class OriginRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_origins):
        super().__init__()
        self.allowed_origins = set(allowed_origins)

    def validate(self, url):
        if origin(url) not in self.allowed_origins:
            raise ValueError("Redirect to an untrusted origin is forbidden")

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.get_header('Authorization') or req.get_header('Cookie'):
            raise ValueError('Credentialed redirects are forbidden')
        self.validate(newurl)
        if req.get_header("Authorization") and origin(req.full_url) != origin(newurl):
            raise ValueError("Credentialed cross-origin redirect is forbidden")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and fp is not None:
            # Do not drain an unbounded redirect body before following Location.
            # HTTPResponse.read() returns empty once its stream is closed.
            fp.close()
        return redirected


def open_https(request, timeout, *, allowed_hosts=None):
    initial = origin(request.full_url)
    allowed = {initial} if allowed_hosts is None else {("https", host.lower(), 443) for host in allowed_hosts}
    if request.get_header("Authorization") or request.get_header("Cookie"):
        allowed = {initial}
    policy = OriginRedirects(allowed)
    policy.validate(request.full_url)
    response = urllib.request.build_opener(policy).open(request, timeout=timeout)
    try:
        policy.validate(response.geturl())
    except Exception:
        response.close()
        raise
    return response
