"""Full-package startup backend for an already provisioned managed installation.

No default endpoint or process adapter: neither may be inferred from the old
EXE-only updater. Callers must supply a reviewed native health adapter. This
module does not migrate the distributed RC4 layout or publish releases.
"""
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path

from nexus_launcher.portable_bootstrap import run_prepared_transition
from nexus_launcher.portable_package import (MAX_TOTAL_BYTES, _verify_staged_files, stage_portable_archive,
                              verify_installed_inventory, verify_portable_inventory)
from nexus_launcher.portable_transition import _pointer, _read, prepare_transition
from nexus_launcher.resource_limits import MAX_RESPONSE_BYTES, copy_limited, ensure_space, read_limited
from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.secure_http import open_https, origin
from nexus_launcher.signed_release import verify_envelope
from nexus_launcher.update_state import update_lock


class PackageTransport:
    """Anonymous HTTPS GET only; explicit host policy applies to redirects too."""

    def __init__(self, manifest_url, *, allowed_hosts, timeout=8):
        self.allowed_hosts = frozenset(allowed_hosts)
        self.timeout = timeout
        self.manifest_url = manifest_url
        self._validate(manifest_url)

    def _validate(self, url):
        if not isinstance(url, str) or url != url.strip() or any(ord(c) < 33 or ord(c) == 127 for c in url):
            raise ValueError("Invalid package URL")
        _, host, _ = origin(url)
        if host not in self.allowed_hosts:
            raise ValueError("Untrusted package origin")

    def _open(self, url):
        self._validate(url)
        return open_https(urllib.request.Request(url, headers={"User-Agent": "NEXUS-Package-Bootstrap/1",
                                                              "Accept-Encoding": "identity"}),
                          timeout=self.timeout, allowed_hosts=self.allowed_hosts)

    def manifest(self):
        with self._open(self.manifest_url) as response:
            # Full runtime inventories are larger than the legacy EXE manifest.
            return json.loads(read_limited(response, MAX_RESPONSE_BYTES, timeout=20))

    def download(self, payload, cache, progress):
        self._validate(payload["url"])
        size = payload["size"]
        if type(size) is not int or not 0 < size <= MAX_TOTAL_BYTES:
            raise ValueError("Invalid signed archive size")
        if not isinstance(payload["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", payload["sha256"]):
            raise ValueError("Invalid signed archive hash")
        with pinned_directory(cache, create=True):
            ensure_space(cache, size)
            fd, name = tempfile.mkstemp(prefix="package-", suffix=".zip", dir=cache)
            target = Path(name)
            try:
                digest = hashlib.sha256()
                with os.fdopen(fd, "wb") as output, self._open(payload["url"]) as response:
                    class ProgressReader:
                        done = 0

                        def read(self, amount):
                            block = getattr(response, "read1", response.read)(amount)
                            self.done += len(block)
                            if self.done <= size:
                                progress(self.done, size)
                            return block

                    actual = copy_limited(ProgressReader(), output, limit=size, digest=digest, timeout=300)
                    output.flush()
                    os.fsync(output.fileno())
                if actual != size or digest.hexdigest() != payload["sha256"]:
                    raise ValueError("Downloaded package integrity mismatch")
                return target
            except BaseException:
                # Only this attempt's exclusive cache file; never a caller path.
                target.unlink(missing_ok=True)
                raise


class PortableStartupBackend:
    def __init__(self, root, *, transport, adapter, platform, arch, keys=None):
        required = ("wait_parent", "launch", "await_health", "stop_and_wait", "launch_current")
        if adapter is None or any(not callable(getattr(adapter, name, None)) for name in required):
            raise ValueError("Reviewed native process and health adapter required")
        self.root, self.transport, self.adapter = Path(root).absolute(), transport, adapter
        self.platform, self.arch, self.keys = platform, arch, keys

    def _current(self):
        # Installed signature remains valid after manifest freshness expires.
        transition = checked_path(self.root, "transition.json")
        if transition.exists() and _read(self.root, "transition.json").get("phase") not in {"COMPLETE", "ROLLED_BACK"}:
            raise ValueError("Unresolved package transition")
        name = _pointer(self.root)["slot"]
        if not isinstance(name, str) or not re.fullmatch(r"portable-stage-[A-Za-z0-9_-]+", name):
            raise ValueError("Invalid installed package pointer")
        slot = checked_path(self.root, "slots/" + name)
        if _read(slot, "journal.json") != {"schema": 1, "phase": "READY"}:
            raise ValueError("Installed slot incomplete")
        inventory = verify_installed_inventory(_read(slot, "envelope.json"), keys=self.keys)
        with pinned_directory(checked_path(slot, "files")):
            _verify_staged_files(slot / "files", inventory)
        return name, inventory

    def can_launch_current(self):
        try:
            with update_lock(self.root):
                self._current()
            return True
        except Exception:
            return False

    def check(self):
        envelope = self.transport.manifest()
        payload = verify_envelope(envelope, keys=self.keys)
        if payload.get("platform") != self.platform or payload.get("arch") != self.arch:
            raise ValueError("Wrong package platform")
        if payload.get("available") is False:
            return None
        if payload.get("available") is not True:
            raise ValueError("Package availability is not explicit")
        inventory = verify_portable_inventory(envelope, keys=self.keys)
        with update_lock(self.root):
            _, current = self._current()
        def version(value):
            return tuple(int(part) for part in value.split(".")) + (0,) * (4 - len(value.split(".")))
        if version(inventory.version) <= version(current.version):
            return None
        return json.loads(json.dumps(envelope, allow_nan=False))

    def download(self, release, progress):
        payload = verify_envelope(release, keys=self.keys)
        verify_portable_inventory(release, keys=self.keys)
        return self.transport.download(payload, checked_path(self.root, "cache"), progress)

    def stage(self, archive, release):
        # A transport cannot nominate arbitrary user files for extraction.
        archive = Path(archive).absolute()
        if archive.parent != checked_path(self.root, "cache") or not re.fullmatch(r"package-[A-Za-z0-9_-]+\.zip", archive.name):
            raise ValueError("Archive is not in owned update cache")
        checked_path(archive.parent, archive.name)
        with pinned_directory(checked_path(self.root, "slots")):
            return stage_portable_archive(archive, release, self.root / "slots", keys=self.keys)

    def activate(self, candidate):
        candidate = Path(candidate).absolute()
        if candidate.parent != checked_path(self.root, "slots"):
            raise ValueError("Candidate is outside managed slots")
        with update_lock(self.root):
            previous, _ = self._current()
        prepare_transition(self.root, candidate.name, previous, platform=self.platform, arch=self.arch, keys=self.keys)
        return run_prepared_transition(self.root, adapter=self.adapter, keys=self.keys)["phase"]

    def launch_current(self):
        # Adapter must hold the installation's process lease, authenticate the
        # exact reverified child, and return only after real readiness. Mere
        # Popen success/show()/loadFinished is not this contract.
        with update_lock(self.root):
            name, inventory = self._current()
            files = checked_path(self.root, "slots/" + name + "/files")
            with pinned_directory(files):
                return self.adapter.launch_current(checked_path(files, inventory.entrypoint), files) is True
