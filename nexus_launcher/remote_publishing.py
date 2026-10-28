"""Authenticated staging publishing and signed catalogue clients."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from nexus_launcher.publishing import WorldCatalogueRepository
from nexus_launcher.resource_limits import read_limited
from nexus_launcher.secure_http import open_https, origin
from nexus_launcher.user_instances import atomic_json
from nexus_launcher.update_state import update_lock
from nexus_launcher.creator_operation_journal import CreatorOperationJournal, JournalError

MAX_RESPONSE = 2 * 1024 * 1024
DEFAULT_PART_SIZE = 16 * 1024 * 1024


class RemotePublishingError(RuntimeError):
    def __init__(self, code, message, request_id="", http_status=None):
        super().__init__(message)
        self.code, self.request_id, self.http_status = code, request_id, http_status


class ControlPlaneClient:
    def __init__(self, base_url: str, token_provider, timeout=30, opener=open_https):
        origin(base_url)
        self.base_url, self.token_provider, self.timeout, self.opener = base_url.rstrip("/"), token_provider, timeout, opener

    def request(self, path, *, method="GET", payload=None, data=None, headers=None):
        if not path.startswith("/") or path.startswith("//") or "\\" in path:
            raise ValueError("Invalid control-plane path")
        token = self.token_provider()
        if not token:
            raise RemotePublishingError("AUTH_REQUIRED", "Войдите в аккаунт NEXUS")
        request_headers = {"Accept": "application/json", "Authorization": f"Bearer {token}",
                           "User-Agent": "NEXUS-Launcher/0.9.24", "X-Request-Id": str(uuid.uuid4())}
        supplied_headers = dict(headers or {})
        local_binding_keys = [k for k in supplied_headers if k.lower() == "x-local-session-binding"]
        if len(local_binding_keys) > 1 or any(k.lower() in {"authorization", "cookie", "host"} for k in supplied_headers):
            raise RemotePublishingError("INVALID_AUTH_HEADERS", "Caller cannot replace authenticated transport context")
        expected_binding = supplied_headers.pop(local_binding_keys[0], None) if local_binding_keys else None
        if expected_binding is not None and hashlib.sha256(token.encode()).hexdigest() != expected_binding:
            raise RemotePublishingError("ACCOUNT_CHANGED", "Session changed before request dispatch")
        request_headers.update(supplied_headers)
        body = data
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=body, headers=request_headers, method=method)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                value = json.loads(read_limited(response, MAX_RESPONSE).decode())
                if not isinstance(value, dict):
                    raise ValueError("Invalid response")
                return value
        except urllib.error.HTTPError as error:
            try:
                value = json.loads(read_limited(error, MAX_RESPONSE).decode())
            except Exception:
                value = {}
            raise RemotePublishingError(str(value.get("code", "HTTP_ERROR")),
                                        str(value.get("message", "Control plane rejected the request")),
                                        str(value.get("requestId", "")), http_status=error.code) from error


class RemoteSubmissionRepository:
    def __init__(self, client: ControlPlaneClient, recovery_file: Path, *, binding_provider=None):
        self.client, self.recovery_file = client, recovery_file
        self.journal = CreatorOperationJournal(recovery_file.with_name(recovery_file.name + ".operations"), binding_provider, atomic_json, update_lock)

    def capabilities(self):
        return self.client.request("/api/v1/capabilities")

    def create(self, metadata: dict, idempotency_key: str | None = None):
        return self.journal.execute("create", "account", idempotency_key, metadata,
            lambda payload, headers: self.client.request("/api/v1/submissions", method="POST", payload=payload, headers=headers))

    def recover_operation(self, key):
        def query(operation, resource, operation_key, payload_hash, expected_binding):
            parameters = urllib.parse.urlencode(dict(operation=operation, resource=resource, key=operation_key, payloadHash=payload_hash))
            return self.client.request("/api/v1/operations/status?" + parameters, headers={"X-Local-Session-Binding": expected_binding})
        return self.journal.recover(key, query)

    def list(self):
        return self.client.request("/api/v1/submissions").get("submissions", [])

    def get(self, submission_id):
        return self.client.request(f"/api/v1/submissions/{submission_id}").get("submission")

    def upload(self, submission_id: str, kind: str, artifact: Path, progress=lambda _done, _total: None):
        # Legacy recovery lacked account/version/unknown-part evidence. Never dispatch it.
        raise JournalError("MULTIPART_CLIENT_RECOVERY_BLOCKED")

    def finalize(self, submission_id, expected_version=None, operation_key=None):
        return self.journal.execute("finalize", submission_id, operation_key, {"expectedVersion": expected_version},
            lambda payload, headers: self.client.request(f"/api/v1/submissions/{submission_id}/finalize", method="POST", payload=payload, headers=headers))

    def withdraw(self, submission_id, expected_version=None, operation_key=None):
        return self.journal.execute("withdraw", submission_id, operation_key, {"expectedVersion": expected_version},
            lambda payload, headers: self.client.request(f"/api/v1/submissions/{submission_id}/withdraw", method="POST", payload=payload, headers=headers))

    def _recovery(self):
        raise JournalError("LEGACY_RECOVERY_BLOCKED")

    def _save_recovery(self, value):
        raise JournalError("LEGACY_RECOVERY_BLOCKED")


class RemoteReviewRepository:
    def __init__(self, client: ControlPlaneClient): self.client = client
    def inbox(self): return self.client.request("/api/v1/review/submissions").get("submissions", [])
    def decide(self, submission_id, decision, expected_version, *, category="General", message="", target=""):
        if decision in {"request_changes", "reject"} and not message.strip():
            raise ValueError("Review comment is required")
        return self.client.request(f"/api/v1/review/submissions/{submission_id}/decision", method="POST",
            payload={"decision":decision,"expectedVersion":expected_version,"comment":message,
                     "category":category,"target":target}, headers={"Idempotency-Key":str(uuid.uuid4())})
    def publish_staging(self, submission_id):
        return self.client.request(f"/api/v1/staging/publish/{submission_id}", method="POST", payload={},
                                   headers={"Idempotency-Key":str(uuid.uuid4())})


class RemoteTechRepository:
    def __init__(self, client: ControlPlaneClient): self.client=client
    def overview(self): return self.client.request("/api/v1/tech/overview")
    def audit(self, *, action="", target=""):
        query=urllib.parse.urlencode({"action":action,"target":target})
        return self.client.request("/api/v1/tech/audit?"+query).get("events",[])


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()


class RemoteWorldCatalogueRepository(WorldCatalogueRepository):
    def __init__(self, url: str, keys: dict[str,str], state_file: Path, cache_file: Path, opener=open_https):
        origin(url); self.url,self.keys,self.state_file,self.cache_file,self.opener=url,dict(keys),state_file,cache_file,opener

    def list_worlds(self):
        request=urllib.request.Request(self.url,headers={"Accept":"application/json","User-Agent":"NEXUS-Launcher/0.9.24"})
        with self.opener(request,timeout=15) as response: envelope=json.loads(read_limited(response,MAX_RESPONSE))
        payload=self._verify(envelope); self.cache_file.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(self.cache_file,envelope); atomic_json(self.state_file,{"sequence":payload["sequence"]})
        return list(payload["worlds"])

    def _verify(self,envelope):
        if not isinstance(envelope,dict) or envelope.get("schema")!=1: raise ValueError("Unsupported catalogue envelope")
        payload=envelope.get("catalogue"); key=self.keys.get(envelope.get("keyId"))
        if not isinstance(payload,dict) or not key: raise ValueError("Untrusted catalogue key")
        try: Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(base64.b64decode(envelope["signature"],validate=True),_canonical(payload))
        except (InvalidSignature,ValueError,TypeError,KeyError) as error: raise ValueError("Catalogue signature is invalid") from error
        sequence=payload.get("sequence"); worlds=payload.get("worlds")
        if type(sequence) is not int or sequence<1 or not isinstance(worlds,list) or len(worlds)>500: raise ValueError("Invalid catalogue payload")
        try: highest=json.loads(self.state_file.read_text())["sequence"]
        except (OSError,ValueError,TypeError,KeyError): highest=0
        if sequence<highest: raise ValueError("Catalogue rollback is forbidden")
        return payload


class FallbackWorldCatalogueRepository(WorldCatalogueRepository):
    def __init__(self, remote, cached, bundled): self.remote,self.cached,self.bundled=remote,cached,bundled
    def list_worlds(self):
        for repository in (self.remote,self.cached,self.bundled):
            try:
                worlds=repository.list_worlds()
                if worlds: return worlds
            except (OSError,ValueError,RemotePublishingError,urllib.error.URLError): pass
        return []
