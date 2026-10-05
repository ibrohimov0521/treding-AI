"""Append-only JSONL audit log with a verifiable SHA-256 hash chain."""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

GENESIS_HASH = "0" * 64
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AuditVerification:
    event_count: int
    last_hash: str


class AuditLog:
    """Append and verify structured events without rewriting earlier records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        verification = self.verify(path)
        self.sequence = verification.event_count
        self.last_hash = verification.last_hash

    def append(
        self,
        event_type: str,
        payload: dict[str, object],
        *,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Durably append one event and return the complete record."""
        if not event_type.strip():
            raise ValueError("Audit event_type must not be empty")
        event_time = occurred_at or datetime.now(UTC)
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise ValueError("Audit timestamps must be timezone-aware")
        body: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "sequence": self.sequence + 1,
            "event_type": event_type,
            "occurred_at": event_time.astimezone(UTC).isoformat(),
            "payload": payload,
            "previous_hash": self.last_hash,
        }
        event_hash = hashlib.sha256(_canonical_json(body)).hexdigest()
        record = {**body, "event_hash": event_hash}
        line = _canonical_json(record) + b"\n"

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        try:
            remaining = memoryview(line)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("Audit append wrote no bytes")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(self.path, 0o600)
        self.sequence += 1
        self.last_hash = event_hash
        return record

    @staticmethod
    def verify(path: Path) -> AuditVerification:
        """Verify sequence numbers and every link in an existing audit chain."""
        if not path.exists():
            return AuditVerification(event_count=0, last_hash=GENESIS_HASH)
        expected_sequence = 1
        previous_hash = GENESIS_HASH
        try:
            with path.open("rb") as audit_file:
                for line_number, line in enumerate(audit_file, start=1):
                    if not line.endswith(b"\n"):
                        raise ValueError(f"Audit event {line_number} is incomplete")
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError(f"Audit event {line_number} must be an object")
                    event_hash = record.pop("event_hash", None)
                    if record.get("schema_version") != SCHEMA_VERSION:
                        raise ValueError(f"Audit event {line_number} has an unsupported schema")
                    if record.get("sequence") != expected_sequence:
                        raise ValueError(f"Audit event {line_number} has an invalid sequence")
                    if record.get("previous_hash") != previous_hash:
                        raise ValueError(f"Audit event {line_number} breaks the hash chain")
                    calculated_hash = hashlib.sha256(_canonical_json(record)).hexdigest()
                    if event_hash != calculated_hash:
                        raise ValueError(f"Audit event {line_number} hash does not match")
                    previous_hash = calculated_hash
                    expected_sequence += 1
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not verify audit file {path}: {exc}") from exc
        return AuditVerification(
            event_count=expected_sequence - 1,
            last_hash=previous_hash,
        )


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Audit record is not JSON-safe: {exc}") from exc


__all__ = ["AuditLog", "AuditVerification"]
