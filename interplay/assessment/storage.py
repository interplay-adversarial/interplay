"""Private append-only stage journal and explicit-schema analytics snapshots."""

import fcntl
import json
import os
import stat
from pathlib import Path

from .models import AssessmentRecord


def json_bytes(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


def private_file(path, limit=128 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_size > limit
        ):
            raise ValueError("assessment-private-file-required")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("assessment-file-limit")
        return data


def atomic_file(path, data):
    temporary = path.with_suffix(path.suffix + ".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def to_arrow(
    records, *, record_cls=AssessmentRecord, schema_version=None, int_fields=(), bool_fields=()
):
    import pyarrow as pa

    # Nested forensic values stay canonical JSON strings, avoiding schema drift
    # between empty, error, tool-call and successful observations.
    int_fields = int_fields or ("ordinal", "round_index")
    bool_fields = bool_fields or ("release_eligible", "capture_complete")
    schema_version = schema_version or "interplay-assessment/2"
    fields = []
    for name in record_cls.model_fields:
        kind = (
            pa.int32() if name in int_fields else pa.bool_() if name in bool_fields else pa.string()
        )
        fields.append(pa.field(name, kind))
    schema = pa.schema(fields, metadata={b"schema_version": schema_version.encode()})
    return pa.Table.from_pylist([r.model_dump(mode="json") for r in records], schema=schema)


class AssessmentStore:
    """Append-only private journal and matching analytics export.

    Generic over ``record_cls`` so other result sinks (for example the shared
    red-teaming runner result sink) reuse this same locking, fsync and atomic
    export discipline instead of reimplementing it; each caller's own
    ``schema_version``/journal filename keeps the on-disk layouts independent.
    """

    def __init__(self, output: Path, *, recover=False, record_cls=AssessmentRecord):
        self.record_cls = record_cls
        if not recover:
            output.mkdir(mode=0o700, exist_ok=False)
        info = output.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("assessment-private-directory-required")
        self.root = output.resolve()
        self.lock = os.open(
            self.root / "campaign.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if recover:
                for name in ("records.jsonl", "records.parquet", "records.arrow", "manifest.json"):
                    pending = self.root / (name + ".pending")
                    if pending.exists() or pending.is_symlink():
                        private_file(pending)
                        pending.unlink()
        except BaseException:
            os.close(self.lock)
            raise

    def close(self):
        if self.lock is not None:
            fd, self.lock = self.lock, None
            os.close(fd)

    def stage(self, record):
        record = self.record_cls.model_validate(record)
        data = json_bytes(record.model_dump(mode="json")) + b"\n"
        if len(data) > 512 * 1024:
            raise ValueError("assessment-record-limit")
        fd = os.open(
            self.root / "events.jsonl",
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        with os.fdopen(fd, "ab") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError("assessment-private-file-required")
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def export(self, records, *, schema_version=None, int_fields=(), bool_fields=()):
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = to_arrow(
            records,
            record_cls=self.record_cls,
            schema_version=schema_version,
            int_fields=int_fields,
            bool_fields=bool_fields,
        )
        atomic_file(
            self.root / "records.jsonl",
            b"".join(json_bytes(r.model_dump(mode="json")) + b"\n" for r in records),
        )
        parquet = pa.BufferOutputStream()
        pq.write_table(table, parquet)
        atomic_file(self.root / "records.parquet", parquet.getvalue().to_pybytes())
        ipc = pa.BufferOutputStream()
        with pa.ipc.new_file(ipc, table.schema) as writer:
            writer.write_table(table)
        atomic_file(self.root / "records.arrow", ipc.getvalue().to_pybytes())


def recover_assessment(output: Path):
    """Export latest committed stages; never re-execute a target or judge."""
    store = AssessmentStore(output, recover=True)
    try:
        raw = private_file(store.root / "events.jsonl")
        latest = {}
        campaign_id = None
        truncated = bool(raw and not raw.endswith(b"\n"))
        lines = raw.splitlines()[:-1] if truncated else raw.splitlines()
        for line in lines:
            record = AssessmentRecord.model_validate_json(line)
            if campaign_id is not None and campaign_id != record.campaign_id:
                raise ValueError("assessment-journal-binding-changed")
            campaign_id = record.campaign_id
            previous = latest.get(record.attempt_id)
            if previous and (
                any(
                    getattr(previous, key) != getattr(record, key)
                    for key in (
                        "ordinal",
                        "schema_version",
                        "round_index",
                        "parent_attempt_id",
                        "selection_reason",
                        "feedback_json",
                        "assessment_description",
                        "success_criteria",
                        "probe",
                        "adversarial_intent",
                        "strategy",
                        "provenance_json",
                        "created_at",
                    )
                )
                or any(
                    getattr(previous, key) is not None
                    and getattr(previous, key) != getattr(record, key)
                    for key in ("response", "logs_json", "traces_json", "conversation_trace_json")
                )
                or (previous.status in ("complete", "incomplete") and previous != record)
            ):
                raise ValueError("assessment-journal-binding-changed")
            if not previous:
                if any(r.ordinal == record.ordinal for r in latest.values()):
                    raise ValueError("assessment-journal-binding-changed")
                if record.parent_attempt_id is not None:
                    parent = latest.get(record.parent_attempt_id)
                    if (
                        parent is None
                        or parent.status != "complete"
                        or parent.judge_verdict == "inconclusive"
                        or json.loads(record.feedback_json)["judge_verdict"] != parent.judge_verdict
                        or record.round_index != parent.round_index + 1
                        or record.ordinal != parent.ordinal + 1
                        or record.selection_reason != "refine-previous"
                    ):
                        raise ValueError("assessment-journal-lineage-invalid")
                elif record.round_index != 0 or record.selection_reason == "refine-previous":
                    raise ValueError("assessment-journal-lineage-invalid")
            latest[record.attempt_id] = record
            if len(latest) > 50:
                raise ValueError("assessment-journal-limit")
        records = [
            r
            if r.status == "complete"
            else r.model_copy(
                update={
                    "status": "incomplete",
                    "error_code": "interrupted",
                    "judge_verdict": "inconclusive",
                }
            )
            for r in sorted(latest.values(), key=lambda r: r.ordinal)
        ]
        store.export(records)
        return {
            "records": len(records),
            "recovered": True,
            "journal_truncated": truncated,
            "assessment_complete": False,
            "release_eligible": False,
        }
    finally:
        store.close()
