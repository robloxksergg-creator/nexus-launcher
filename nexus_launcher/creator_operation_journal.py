"""Creator operation journal: no credentials, no implicit mutation retry."""
import hashlib
import json
import re
import time


class JournalError(RuntimeError):
    pass


def canonical(payload):
    def check(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or any(x in key.lower() for x in ("token", "secret", "password", "cookie", "authorization", "credential", "private_key")):
                    raise JournalError("UNSAFE_JOURNAL_PAYLOAD")
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif not (value is None or isinstance(value, (str, int, float, bool))):
            raise JournalError("INVALID_PAYLOAD")
    check(payload)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw.encode()) > 128 * 1024:
        raise JournalError("PAYLOAD_TOO_LARGE")
    return raw


class CreatorOperationJournal:
    def __init__(self, path, binding_provider, writer, lock):
        self.path, self.binding_provider, self.writer, self.lock = path, binding_provider, writer, lock

    def binding(self):
        value = self.binding_provider() if self.binding_provider else None
        if not isinstance(value, tuple) or len(value) != 2 or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", str(value[0])) or not re.fullmatch(r"[a-f0-9]{64}", str(value[1])):
            raise JournalError("VERIFIED_ACCOUNT_BINDING_REQUIRED")
        return value

    def load(self):
        if not self.path.exists():
            return {"format": 1, "operations": {}}
        try:
            if self.path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError()
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if set(value) != {"format", "operations"} or value["format"] != 1 or not isinstance(value["operations"], dict):
                raise ValueError()
            for key, entry in value["operations"].items():
                if set(entry) != {"account", "session_binding", "operation", "resource", "key", "payload", "payload_hash", "version", "state", "updated_at", "upload_id"}:
                    raise ValueError()
                if key != entry["key"] or entry["state"] not in {"SENDING", "UNKNOWN", "CONFIRMED", "CONFLICT", "PRECONDITION", "EXPIRED", "BLOCKED"}:
                    raise ValueError()
                if hashlib.sha256(entry["payload"].encode()).hexdigest() != entry["payload_hash"] or canonical(json.loads(entry["payload"])) != entry["payload"]:
                    raise ValueError()
            return value
        except (ValueError, TypeError, KeyError, OSError, JournalError):
            raise JournalError("JOURNAL_CORRUPT_BLOCKED") from None

    def execute(self, operation, resource, key, payload, send):
        if operation not in {"create", "init", "complete", "finalize", "withdraw"} or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", resource) or not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
            raise JournalError("OPERATION_IDENTITY_REQUIRED")
        field = "expectedRevision" if operation == "create" else "expectedVersion"
        version = payload.get(field)
        if type(version) is not int or version < (0 if operation == "create" else 1):
            raise JournalError("VERSION_PRECONDITION_REQUIRED")
        raw = canonical(payload)
        account, session = self.binding()
        entry = dict(account=account, session_binding=session, operation=operation, resource=resource, key=key, payload=raw, payload_hash=hashlib.sha256(raw.encode()).hexdigest(), version=version, state="SENDING", updated_at=time.time(), upload_id=None)
        with self.lock(self.path.parent):
            document = self.load()
            old = document["operations"].get(key)
            if old:
                if any(old[k] != entry[k] for k in ("account", "session_binding", "operation", "resource", "payload", "payload_hash", "version")):
                    raise JournalError("OPERATION_BINDING_CONFLICT")
                # Even stored CONFIRMED is not an authoritative replay response.
                raise JournalError("STATUS_RECOVERY_REQUIRED")
            document["operations"][key] = entry
            self.writer(self.path, document)
            if self.binding() != (account, session):
                raise JournalError("ACCOUNT_CHANGED")
            try:
                result = send(json.loads(raw), {"Idempotency-Key": key, "X-Local-Session-Binding": session})
                required = {"create": "submissionId", "init": "uploadId", "complete": "artifactId", "finalize": "submissionId", "withdraw": "submissionId"}[operation]
                if not isinstance(result, dict) or not isinstance(result.get(required), str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", result[required]):
                    raise JournalError("INVALID_OPERATION_RESULT")
                if operation in {"finalize", "withdraw"} and (result["submissionId"] != resource or result.get("state") != {"finalize": "SUBMITTED", "withdraw": "WITHDRAWN"}[operation]):
                    raise JournalError("INVALID_OPERATION_RESULT")
                if operation in {"init", "complete"}:
                    entry["upload_id"] = result.get("uploadId")
            except Exception as error:
                status = getattr(error, "http_status", None)
                code = str(getattr(error, "code", ""))
                entry["state"] = "UNKNOWN" if "RECONCILIATION" in code else {409: "CONFLICT", 428: "PRECONDITION", 410: "EXPIRED"}.get(status, "UNKNOWN")
                entry["updated_at"] = time.time()
                self.writer(self.path, document)
                raise
            entry["state"] = "CONFIRMED"
            entry["updated_at"] = time.time()
            self.writer(self.path, document)
            if self.binding() != (account, session):
                raise JournalError("ACCOUNT_CHANGED")
            return result

    def recover(self, key, query):
        account, session = self.binding()
        with self.lock(self.path.parent):
            document = self.load()
            entry = document["operations"].get(key)
            if not entry or (entry["account"], entry["session_binding"]) != (account, session):
                raise JournalError("OPERATION_BINDING_CONFLICT")
            result = query(entry["operation"], entry["resource"], entry["key"], entry["payload_hash"], session)
            if self.binding() != (account, session):
                raise JournalError("ACCOUNT_CHANGED")
            state = result.get("state")
            if state not in {"CONFIRMED", "UNKNOWN", "BLOCKED"}:
                raise JournalError("INVALID_STATUS_RESPONSE")
            if state == "CONFIRMED" and (not isinstance(result.get("result"), dict) or result.get("status") not in {200, 201}):
                raise JournalError("INVALID_STATUS_RESPONSE")
            entry["state"], entry["updated_at"] = state, time.time()
            if state == "CONFIRMED" and "uploadId" in result["result"]:
                entry["upload_id"] = result["result"]["uploadId"]
            self.writer(self.path, document)
            if state != "CONFIRMED":
                raise JournalError("STATUS_RECOVERY_REQUIRED")
            return result["result"]
