"""GitHub is a package host, never an update signing authority."""
import re
from urllib.parse import urlsplit

from nexus_launcher.startup_portable_backend import PackageTransport

REPOSITORY = "robloxksergg-creator/nexus-launcher"
GITHUB_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com",
                          "objects.githubusercontent.com"})


class GitHubPackageTransport(PackageTransport):
    """Read a signed envelope and package from one explicitly selected repository.

    Signature, channel, freshness, version, inventory and activation checks remain
    owned by the existing backend. No GitHub API credentials are accepted.
    """

    def __init__(self, manifest_url, *, timeout=8):
        super().__init__(manifest_url, allowed_hosts=GITHUB_HOSTS, timeout=timeout)

    def _validate(self, url):
        super()._validate(url)
        parts = urlsplit(url)
        prefix = f"/{REPOSITORY}/releases/download/"
        if parts.hostname != "github.com" or parts.query or not parts.path.startswith(prefix):
            raise ValueError("Update must name an asset in the configured GitHub repository")
        suffix = parts.path[len(prefix):]
        # Literal tag and filename only; reject path escapes and encoded aliases.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", suffix):
            raise ValueError("Invalid GitHub release asset path")
        if any(component in {".", ".."} for component in suffix.split("/")):
            raise ValueError("Invalid GitHub release asset path")
