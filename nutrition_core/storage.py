"""Explicit private POSIX storage with opt-in, immutable history segments."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time

try:
    import fcntl
except ImportError:  # Pure workflows remain importable on unsupported platforms.
    fcntl = None

from .common import NutritionError, require_keys

STORAGE_SCHEMA = "nutrition-record-v2"
LONG_TERM_SCHEMA = "nutrition-record-v3"
ARCHIVE_SCHEMA = "nutrition-record-archive-v1"
COMPACT_ARCHIVE_SCHEMA = "nutrition-archive-v1"
DELETE_SCHEMA = "nutrition-record-delete-v1"
MAX_REVISIONS = 50
MAX_REVISION_NUMBER = 2 ** 31 - 1
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_EXPORT_BYTES = 8 * 1024 * 1024
LOCK_TIMEOUT_SECONDS = 1.0
_SOURCE_ROOT = Path(__file__).resolve().parents[1]


def _member_id(member_id):
    if not isinstance(member_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", member_id):
        raise NutritionError("invalid_member_id", "member_id must be a supported lowercase identifier")
    return member_id


def _revision(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or not (0 if allow_zero else 1) <= value <= MAX_REVISION_NUMBER:
        raise NutritionError("invalid_revision", "Revision must be an integer in the supported range")
    return value


def _record_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise NutritionError("invalid_record_id", "record_id must be a 32-character lowercase hexadecimal record identifier")
    return value


def _expect_record(record, expected_record_id):
    if expected_record_id is None:
        raise NutritionError("record_id_required", "Updating or deleting requires the record_id returned by the prior read or save")
    if _record_id(expected_record_id) != record["record_id"]:
        raise NutritionError("record_conflict", "This member now has a different record; read its current state before acting")


def _data_path(data_dir):
    if fcntl is None or os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise NutritionError("storage_platform_unsupported", "Local storage currently requires POSIX file descriptors and flock")
    try:
        text = os.fspath(data_dir)
    except TypeError:
        raise NutritionError("storage_path_invalid", "data_dir must be an explicit absolute path") from None
    if not isinstance(text, str) or not text or "\x00" in text or len(text) > 4096:
        raise NutritionError("storage_path_invalid", "data_dir must be a bounded absolute text path")
    try:
        text.encode("utf-8", errors="strict")
        os.fsencode(text)
    except UnicodeError:
        raise NutritionError("storage_path_invalid", "data_dir must be encodable as UTF-8 and by the filesystem") from None
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts or path.anchor != "/":
        raise NutritionError("storage_path_invalid", "Relative paths and parent traversal are not allowed")
    home = Path.home().resolve()
    if path == Path("/") or path == home or path == _SOURCE_ROOT or path in _SOURCE_ROOT.parents or _SOURCE_ROOT in path.parents:
        raise NutritionError("storage_path_invalid", "Choose a dedicated directory outside the source tree, root, home and source ancestors")
    return path


def _private(info, *, directory=False):
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    mask = 0o700 if directory else 0o600
    if not expected(info.st_mode):
        raise NutritionError("storage_path_invalid", "Storage requires a real directory and regular member files")
    if stat.S_IMODE(info.st_mode) & ~mask or info.st_uid != os.geteuid():
        raise NutritionError("storage_permissions", "Existing storage must be owned by this user with private permissions; no permissions were changed")
    if not directory and info.st_nlink != 1:
        raise NutritionError("storage_path_invalid", "Hard-linked member files are not accepted")


def _open_directory(path, *, create=False):
    """Traverse by directory descriptors; never resolve or follow a symlink."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass  # A concurrent creator must still pass O_NOFOLLOW.
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _private(os.fstat(descriptor), directory=True)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _io_error(exc):
    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
        return NutritionError("storage_path_invalid", "Symlinks and non-directory path components are not allowed")
    if exc.errno in (errno.EACCES, errno.EPERM):
        return NutritionError("storage_permissions", "The requested storage operation lacks filesystem permission")
    if exc.errno == errno.ENOENT:
        return NutritionError("storage_not_found", "The requested storage directory or member record does not exist")
    return NutritionError("storage_io_error", "The filesystem operation did not complete successfully", {"errno": exc.errno})


@contextmanager
def _locked_directory(data_dir, *, create=False):
    path = _data_path(data_dir)
    descriptor = None
    locked = False
    try:
        descriptor = _open_directory(path, create=create)
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise NutritionError("storage_lock_timeout", "Storage is busy; no record was changed") from None
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        _private(os.fstat(descriptor), directory=True)
        yield descriptor, path
    except OSError as exc:
        raise _io_error(exc) from None
    finally:
        if descriptor is not None:
            try:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _validated_document(document, member_id):
    from .workflow import validate_document

    validated = validate_document(document)
    if validated["profile"]["id"] != member_id:
        raise NutritionError("storage_document_mismatch", "The document belongs to a different member")
    if validated["profile"].get("storage") != "local":
        raise NutritionError("storage_local_required", "This profile has not selected local storage")
    return validated


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise NutritionError("storage_invalid_record", "The stored JSON contains duplicate fields")
        result[key] = value
    return result


def _reject_json_decimal(value):
    raise NutritionError("storage_invalid_record", "Stored decimal values must be strings, not JSON floats or constants")


def _validate_record(record, member_id):
    try:
        if isinstance(record, dict) and record.get("storage_schema") == LONG_TERM_SCHEMA:
            return _validate_long_term(record, member_id)
        if isinstance(record, dict) and record.get("storage_schema") == DELETE_SCHEMA:
            return _validate_deletion(record, member_id)
        fields = {"storage_schema", "member_id", "record_id", "revision", "versions"}
        require_keys(record, fields, fields, "stored record")
        if record["storage_schema"] != STORAGE_SCHEMA or record["member_id"] != member_id:
            raise NutritionError("storage_invalid_record", "This file is not the requested managed member record")
        _record_id(record["record_id"])
        revision = _revision(record["revision"])
        if revision > MAX_REVISIONS:
            raise NutritionError("storage_invalid_record", "A v2 record cannot exceed 50 revisions")
        versions = record["versions"]
        if not isinstance(versions, list) or len(versions) != revision:
            raise NutritionError("storage_invalid_record", "Stored history must include every revision without gaps")
        for expected, entry in enumerate(versions, start=1):
            require_keys(entry, {"revision", "document"}, {"revision", "document"}, "stored version")
            if _revision(entry["revision"]) != expected:
                raise NutritionError("storage_invalid_record", "Stored revisions must be consecutive")
            _validated_document(entry["document"], member_id)
        return record
    except NutritionError as exc:
        if exc.code == "storage_invalid_record":
            raise
        raise NutritionError("storage_invalid_record", "The existing file failed managed-record validation", {"reason": exc.code}) from None


def _identity(info):
    return info.st_dev, info.st_ino


def _signature(info):
    return (*_identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_json(directory, filename, *, missing_ok=False):
    try:
        descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        if missing_ok:
            return None, None, None
        raise
    try:
        before = os.fstat(descriptor)
        _private(before)
        if before.st_size > MAX_RECORD_BYTES:
            raise NutritionError("storage_size_limit", "The member file exceeds the 4 MiB limit")
        chunks = []
        remaining = MAX_RECORD_BYTES + 1
        while remaining:
            block = os.read(descriptor, min(65536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        if len(raw) > MAX_RECORD_BYTES:
            raise NutritionError("storage_size_limit", "The member file exceeds the 4 MiB limit")
        if _signature(before) != _signature(os.fstat(descriptor)):
            raise NutritionError("storage_conflict", "The record changed during reading; no write was attempted")
    finally:
        os.close(descriptor)
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                            parse_float=_reject_json_decimal, parse_constant=_reject_json_decimal)
    except (ValueError, UnicodeError, RecursionError):
        raise NutritionError("storage_invalid_record", "The existing member file is not valid managed JSON") from None
    return record, before, raw


def _read_record(directory, filename, member_id, *, missing_ok=False):
    record, before, _ = _read_json(directory, filename, missing_ok=missing_ok)
    return (_validate_record(record, member_id) if before is not None else None), before


def _ensure_unchanged(directory, filename, before):
    try:
        current = os.stat(filename, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        current = None
    if current is not None:
        _private(current)
    if (before is None) != (current is None) or (before is not None and _signature(before) != _signature(current)):
        raise NutritionError("storage_conflict", "The member file changed outside this storage operation")


def _atomic_write(directory, filename, raw, before, *, operation="save_record"):
    temporary = f".{filename}.{secrets.token_hex(16)}.tmp"
    descriptor = None
    created = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        created = os.fstat(descriptor)
        os.fchmod(descriptor, 0o600)  # Only the new file created by this operation.
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError(errno.EIO, "Incomplete storage write")
            remaining = remaining[written:]
        os.fsync(descriptor)
        _ensure_unchanged(directory, filename, before)
        os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
        try:
            os.fsync(directory)
        except OSError:
            raise NutritionError("storage_durability_uncertain", "The replacement is visible but durability is unconfirmed; load the current revision before retrying",
                                 {"operation": operation, "replacement_visible": True}) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created is not None:
            try:
                candidate = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
                if _identity(candidate) == _identity(created):
                    os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass


def _result(path, member_id, revision, record_id):
    return {"status": "ok", "member_id": member_id, "record_id": record_id, "revision": revision,
            "path": str(path / f"{member_id}.json")}


def _json_bytes(value):
    try:
        return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise NutritionError("storage_invalid_document", "The document cannot be serialized as bounded structured JSON") from None


def _archive_name(member_id, record_id, first, last, digest):
    return f".{member_id}.{record_id}.{first}-{last}.{digest}.archive.json"


def _validate_versions(record, member_id):
    first, last = _revision(record["first_revision"]), _revision(record["revision"])
    versions = record["versions"]
    if first > last or not isinstance(versions, list) or len(versions) != last - first + 1 or len(versions) > MAX_REVISIONS:
        raise NutritionError("storage_invalid_record", "Each history segment must contain at most 50 consecutive revisions")
    for expected, entry in enumerate(versions, start=first):
        require_keys(entry, {"revision", "document"}, {"revision", "document"}, "stored version")
        if _revision(entry["revision"]) != expected:
            raise NutritionError("storage_invalid_record", "Stored revisions must be consecutive")
        _validated_document(entry["document"], member_id)


def _validate_long_term(record, member_id):
    fields = {"storage_schema", "member_id", "record_id", "revision", "first_revision", "versions", "archives"}
    require_keys(record, fields, fields, "long-term record")
    if record["member_id"] != member_id:
        raise NutritionError("storage_invalid_record", "This file belongs to a different member")
    _record_id(record["record_id"])
    if record["versions"] == []:
        revision = _revision(record["revision"])
        if type(record["first_revision"]) is not int or record["first_revision"] != revision + 1:
            raise NutritionError("storage_invalid_record", "An index-only manifest must end immediately before its next active revision")
    else:
        _validate_versions(record, member_id)
    if not isinstance(record["archives"], list):
        raise NutritionError("storage_invalid_record", "Archive references must be a list")
    next_revision = 1
    for item in record["archives"]:
        fields = {"filename", "first_revision", "revision", "sha256"}
        require_keys(item, fields, fields, "archive reference")
        first, last = _revision(item["first_revision"]), _revision(item["revision"])
        digest = item["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise NutritionError("storage_invalid_record", "Archive checksum must be a SHA-256 digest")
        if first != next_revision or not first <= last < first + MAX_REVISIONS:
            raise NutritionError("storage_invalid_record", "Archived history must be consecutive without overlaps")
        if item["filename"] != _archive_name(member_id, record["record_id"], first, last, digest):
            raise NutritionError("storage_invalid_record", "Archive filename does not match its exact managed identity")
        next_revision = last + 1
    if record["first_revision"] != next_revision:
        raise NutritionError("storage_invalid_record", "Active history must immediately follow archived history")
    return record


def _validate_deletion(record, member_id):
    fields = {"storage_schema", "member_id", "record_id", "revision", "deletion_pending", "deletion_archives"}
    require_keys(record, fields, fields, "deletion recovery marker")
    _record_id(record["record_id"])
    _revision(record["revision"])
    if record["member_id"] != member_id or record["deletion_pending"] is not True or not isinstance(record["deletion_archives"], list):
        raise NutritionError("storage_invalid_record", "The deletion marker is not valid for this member")
    seen = set()
    for item in record["deletion_archives"]:
        _validate_archive_reference(item, member_id, record["record_id"])
        if item["filename"] in seen:
            raise NutritionError("storage_invalid_record", "Deletion archive references cannot be duplicated")
        seen.add(item["filename"])
    return record


def _validate_archive_reference(item, member_id, record_id):
    fields = {"filename", "first_revision", "revision", "sha256"}
    require_keys(item, fields, fields, "archive reference")
    first, last = _revision(item["first_revision"]), _revision(item["revision"])
    digest = item["sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or not first <= last < first + MAX_REVISIONS:
        raise NutritionError("storage_invalid_record", "Archive range and checksum must be valid")
    if item["filename"] != _archive_name(member_id, record_id, first, last, digest):
        raise NutritionError("storage_invalid_record", "Archive filename does not match its exact managed identity")


def _archive_inventory(directory, record):
    """Include validated recovery segments, never broad-glob deletion targets."""
    references = {item["filename"]: item for item in record.get("archives", [])}
    prefix = f".{record['member_id']}.{record['record_id']}."
    for filename in os.listdir(directory):
        if not filename.startswith(prefix) or not filename.endswith(".archive.json"):
            continue
        suffix = filename[len(prefix):]
        match = re.fullmatch(r"([1-9][0-9]{0,9})-([1-9][0-9]{0,9})\.([0-9a-f]{64})\.archive\.json", suffix)
        if match is None:
            raise NutritionError("storage_invalid_record", "An unexpected file occupies this record's archive namespace; nothing was deleted")
        first, last, digest = match.groups()
        reference = {"filename": filename, "first_revision": int(first), "revision": int(last), "sha256": digest}
        _validate_archive_reference(reference, record["member_id"], record["record_id"])
        references[filename] = reference
    return list(references.values())


def _check_active(record):
    if record.get("deletion_pending"):
        raise NutritionError("storage_deletion_pending", "Deletion is incomplete; only the explicitly confirmed deletion may resume",
                             {"record_id": record["record_id"], "revision": record["revision"]})


def _read_archive(directory, member_id, record_id, reference, *, missing_ok=False):
    archive, before, raw = _read_json(directory, reference["filename"], missing_ok=missing_ok)
    if before is None:
        return None, None
    try:
        if isinstance(archive, dict) and archive.get("storage_schema") == COMPACT_ARCHIVE_SCHEMA:
            fields = {"storage_schema", "record_id", "versions"}
            require_keys(archive, fields, fields, "compact history archive")
            if not isinstance(archive["versions"], list) or len(archive["versions"]) != 1:
                raise NutritionError("storage_invalid_record", "A compact history archive must contain exactly one revision")
            archive = {**archive, "storage_schema": ARCHIVE_SCHEMA, "member_id": member_id,
                       "first_revision": reference["first_revision"], "revision": reference["revision"]}
        else:
            fields = {"storage_schema", "member_id", "record_id", "first_revision", "revision", "versions"}
            require_keys(archive, fields, fields, "history archive")
        if (archive["storage_schema"] != ARCHIVE_SCHEMA or archive["member_id"] != member_id
                or archive["record_id"] != record_id or archive["first_revision"] != reference["first_revision"]
                or archive["revision"] != reference["revision"] or hashlib.sha256(raw).hexdigest() != reference["sha256"]):
            raise NutritionError("storage_invalid_record", "The history archive does not match its identity and checksum")
        _validate_versions(archive, member_id)
    except NutritionError as exc:
        if exc.code == "storage_invalid_record":
            raise
        raise NutritionError("storage_invalid_record", "The history archive failed managed-record validation", {"reason": exc.code}) from None
    return archive, before


def _archive_payload(record):
    archive = {"storage_schema": ARCHIVE_SCHEMA, "member_id": record["member_id"], "record_id": record["record_id"],
               "first_revision": record.get("first_revision", 1), "revision": record["revision"], "versions": record["versions"]}
    raw = _json_bytes(archive)
    if len(raw) > MAX_RECORD_BYTES and len(archive["versions"]) == 1:
        # The compact envelope is smaller than a one-revision v2 record.
        # Range/member identity is still checked using the hashed reference,
        # exact filename, record_id and validated document profile.
        raw = _json_bytes({"storage_schema": COMPACT_ARCHIVE_SCHEMA, "record_id": record["record_id"],
                           "versions": archive["versions"]})
    if len(raw) > MAX_RECORD_BYTES:
        raise NutritionError("storage_size_limit", "A history segment or single structured document cannot fit the 4 MiB archive limit; no history was removed")
    digest = hashlib.sha256(raw).hexdigest()
    reference = {"filename": _archive_name(record["member_id"], record["record_id"], archive["first_revision"], archive["revision"], digest),
                 "first_revision": archive["first_revision"], "revision": archive["revision"], "sha256": digest}
    return reference, raw


def _archive_payloads(record):
    """Partition by actual serialized bytes, including each archive envelope."""
    payloads, entries = [], []
    for entry in record["versions"]:
        candidate_entries = [*entries, entry]
        segment = {**record, "first_revision": candidate_entries[0]["revision"],
                   "revision": candidate_entries[-1]["revision"], "versions": candidate_entries}
        try:
            payload = _archive_payload(segment)
        except NutritionError as exc:
            if exc.code != "storage_size_limit" or not entries:
                raise
            payloads.append(previous_payload)
            entries = [entry]
            segment.update(first_revision=entry["revision"], versions=entries)
            payload = _archive_payload(segment)
        else:
            entries = candidate_entries
        previous_payload = payload
    if entries:
        payloads.append(previous_payload)
    return payloads


def _write_archive(directory, record, reference, raw):
    # A failed main-file replacement can leave this exact immutable segment.
    # Reuse it only after validating its identity, checksum and full contents.
    existing, before = _read_archive(directory, record["member_id"], record["record_id"], reference, missing_ok=True)
    if existing is None:
        _atomic_write(directory, reference["filename"], raw, before, operation="write_archive")
    else:
        _ensure_unchanged(directory, reference["filename"], before)


def _rotate(record, document):
    if record["revision"] == MAX_REVISION_NUMBER:
        raise NutritionError("storage_revision_limit", "The supported revision-number range has been exhausted")
    payloads = _archive_payloads(record)
    revision = record["revision"] + 1
    candidate = {"storage_schema": LONG_TERM_SCHEMA, "member_id": record["member_id"], "record_id": record["record_id"],
                 "revision": revision, "first_revision": revision,
                 "versions": [{"revision": revision, "document": document}],
                 "archives": [*record.get("archives", []), *(reference for reference, _ in payloads)]}
    raw = _json_bytes(candidate)
    if len(raw) > MAX_RECORD_BYTES:
        # A near-limit valid document need not fit beside a growing index.
        # Archive this revision too; the manifest can reference the latest one.
        latest_payload = _archive_payload(candidate)
        payloads.append(latest_payload)
        candidate["archives"].append(latest_payload[0])
        candidate.update(first_revision=revision + 1, versions=[])
        raw = _json_bytes(candidate)
        if len(raw) > MAX_RECORD_BYTES:
            raise NutritionError("storage_size_limit", "The archive index itself would exceed 4 MiB; no history was removed")
    return candidate, raw, payloads


def _document_at(directory, record, revision):
    segment = record
    if record["storage_schema"] == LONG_TERM_SCHEMA and revision < record["first_revision"]:
        reference = next(item for item in record["archives"] if item["first_revision"] <= revision <= item["revision"])
        segment, _ = _read_archive(directory, record["member_id"], record["record_id"], reference)
    return deepcopy(segment["versions"][revision - segment.get("first_revision", 1)]["document"])


def _check_revision(record, expected_revision, expected_record_id):
    _expect_record(record, expected_record_id)
    if expected_revision != record["revision"]:
        raise NutritionError("revision_conflict", "The current revision differs from expected_revision",
                             {"expected_revision": expected_revision, "current_revision": record["revision"]})


def archive_record(data_dir: str | os.PathLike[str], member_id: str, expected_revision: int,
                   consent: bool, expected_record_id: str | None = None,
                   keep_from_date: str | None = None) -> dict:
    """Opt into segmented history; optionally keep only recent active dates.

    All previous documents remain in immutable archives. No historical record
    is deleted, and profiles or new non-date document fields are retained.
    """
    member_id = _member_id(member_id)
    expected_revision = _revision(expected_revision)
    if consent is not True:
        raise NutritionError("storage_consent_required", "Archiving requires explicit consent=true, including any keep_from_date cutoff")
    if keep_from_date is not None:
        try:
            if not isinstance(keep_from_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", keep_from_date):
                raise ValueError
            date.fromisoformat(keep_from_date)
        except ValueError:
            raise NutritionError("invalid_archive_date", "keep_from_date must be an exact valid ISO date") from None
    with _locked_directory(data_dir) as (directory, path):
        filename = f"{member_id}.json"
        record, before = _read_record(directory, filename, member_id)
        _check_active(record)
        _check_revision(record, expected_revision, expected_record_id)
        document = _document_at(directory, record, record["revision"])
        moved = {"days": 0, "journal": 0, "reviews": 0, "target_reviews": 0}
        if keep_from_date is not None:
            if "days" in document:
                original = document["days"]
                document["days"] = {day: value for day, value in original.items() if day >= keep_from_date}
                moved["days"] = len(original) - len(document["days"])
            for field, date_field in (("journal", "date"), ("reviews", "as_of"), ("target_reviews", "as_of")):
                if field in document:
                    original = document[field]
                    document[field] = [item for item in original if item[date_field] >= keep_from_date]
                    moved[field] = len(original) - len(document[field])
        document = _validated_document(document, member_id)
        candidate, raw, payloads = _rotate(record, document)
        for reference, archive_raw in payloads:
            _write_archive(directory, record, reference, archive_raw)
        _atomic_write(directory, filename, raw, before, operation="archive_record")
        result = _result(path, member_id, candidate["revision"], record["record_id"])
        result.update(storage_schema=LONG_TERM_SCHEMA, keep_from_date=keep_from_date,
                      moved_out_of_active_document=moved, history_preserved=True)
        return result


def save_record(data_dir: str | os.PathLike[str], member_id: str, document: dict,
                expected_revision: int, consent: bool, expected_record_id: str | None = None) -> dict:
    """Append one validated revision, then atomically replace its managed file."""
    member_id = _member_id(member_id)
    expected_revision = _revision(expected_revision, allow_zero=True)
    if consent is not True:
        raise NutritionError("storage_consent_required", "Saving requires explicit consent=true")
    if expected_revision == 0 and expected_record_id is not None:
        raise NutritionError("invalid_record_id", "Initial creation requires expected_record_id=None; the new identifier is generated by storage")
    document = _validated_document(document, member_id)
    with _locked_directory(data_dir, create=True) as (directory, path):
        filename = f"{member_id}.json"
        record, before = _read_record(directory, filename, member_id, missing_ok=True)
        current = record["revision"] if record else 0
        if expected_revision != current:
            raise NutritionError("revision_conflict", "The current revision differs from expected_revision",
                                 {"expected_revision": expected_revision, "current_revision": current})
        if record is not None:
            _check_active(record)
            _expect_record(record, expected_record_id)
        if record is not None and record["storage_schema"] == LONG_TERM_SCHEMA:
            if current == MAX_REVISION_NUMBER:
                raise NutritionError("storage_revision_limit", "The supported revision-number range has been exhausted")
            candidate = deepcopy(record)
            candidate["revision"] = current + 1
            candidate["versions"].append({"revision": current + 1, "document": document})
            raw = _json_bytes(candidate)
            if len(candidate["versions"]) > MAX_REVISIONS or len(raw) > MAX_RECORD_BYTES:
                candidate, raw, payloads = _rotate(record, document)
                for reference, archive_raw in payloads:
                    _write_archive(directory, record, reference, archive_raw)
            _atomic_write(directory, filename, raw, before)
            return _result(path, member_id, current + 1, record["record_id"])
        if current >= MAX_REVISIONS:
            raise NutritionError("storage_revision_limit", "The v2 50-revision limit has been reached; use explicit archive_record to preserve history and enable long-term storage")
        if record is None:
            record = {"storage_schema": STORAGE_SCHEMA, "member_id": member_id,
                      "record_id": secrets.token_hex(16), "revision": 0, "versions": []}
        record["revision"] = current + 1
        record["versions"].append({"revision": current + 1, "document": document})
        raw = _json_bytes(record)
        if len(raw) > MAX_RECORD_BYTES:
            raise NutritionError("storage_size_limit", "The complete member history would exceed 4 MiB; no history was removed")
        _atomic_write(directory, filename, raw, before)
        return _result(path, member_id, current + 1, record["record_id"])


def load_record(data_dir: str | os.PathLike[str], member_id: str,
                version: int | None = None) -> dict:
    """Read a selected revision; current_revision remains available for CAS."""
    member_id = _member_id(member_id)
    if version is not None:
        _revision(version)
    with _locked_directory(data_dir) as (directory, path):
        record, _ = _read_record(directory, f"{member_id}.json", member_id)
        _check_active(record)
        selected = record["revision"] if version is None else version
        if selected > record["revision"]:
            raise NutritionError("storage_version_not_found", "The requested historical revision does not exist")
        result = _result(path, member_id, selected, record["record_id"])
        if record["storage_schema"] == LONG_TERM_SCHEMA:
            result.update(document=_document_at(directory, record, selected),
                          current_revision=record["revision"], storage_schema=LONG_TERM_SCHEMA,
                          available_versions=list(range(record["first_revision"], record["revision"] + 1)),
                          available_versions_truncated=record["first_revision"] > 1,
                          history_range={"first_version": 1, "last_version": record["revision"]})
            return result
        result.update(document=deepcopy(record["versions"][selected - 1]["document"]),
                      current_revision=record["revision"], available_versions=list(range(1, record["revision"] + 1)))
        return result


def export_record(data_dir: str | os.PathLike[str], member_id: str,
                  start_version: int | None = None, limit: int | None = None) -> dict:
    """Return bounded history pages; the original unpaged v2 export is unchanged."""
    member_id = _member_id(member_id)
    if start_version is not None:
        _revision(start_version)
    if limit is not None and (type(limit) is not int or not 1 <= limit <= MAX_REVISIONS):
        raise NutritionError("invalid_export_limit", "Export limit must be an integer from 1 through 50")
    with _locked_directory(data_dir) as (directory, path):
        record, _ = _read_record(directory, f"{member_id}.json", member_id)
        _check_active(record)
        result = _result(path, member_id, record["revision"], record["record_id"])
        if record["storage_schema"] == STORAGE_SCHEMA and start_version is None and limit is None:
            result["record"] = deepcopy(record)
            return result
        first = start_version or 1
        if first > record["revision"]:
            raise NutritionError("storage_version_not_found", "The requested export start revision does not exist")
        last = min(first + (limit or MAX_REVISIONS) - 1, record["revision"])
        versions, size = [], 0
        for entry in _export_versions(directory, record, first, last):
            entry_size = len(_json_bytes(entry))
            if versions and size + entry_size > MAX_EXPORT_BYTES:
                break
            versions.append(entry)
            size += entry_size
        last = versions[-1]["revision"]
        result.update(scope="history_page", storage_schema=record["storage_schema"],
                      first_version=first, last_version=last, total_versions=record["revision"],
                      next_version=last + 1 if last < record["revision"] else None,
                      export_complete=first == 1 and last == record["revision"], versions=deepcopy(versions))
        return result


def _export_versions(directory, record, first, last):
    for reference in record.get("archives", []):
        if reference["revision"] < first or reference["first_revision"] > last:
            continue
        segment, _ = _read_archive(directory, record["member_id"], record["record_id"], reference)
        yield from (entry for entry in segment["versions"] if first <= entry["revision"] <= last)
    yield from (entry for entry in record["versions"] if first <= entry["revision"] <= last)


def delete_record(data_dir: str | os.PathLike[str], member_id: str,
                  expected_revision: int, confirmed: bool, expected_record_id: str | None = None) -> dict:
    """Delete exactly the confirmed member file and its contained revisions."""
    member_id = _member_id(member_id)
    expected_revision = _revision(expected_revision)
    if confirmed is not True:
        raise NutritionError("storage_confirmation_required", "Deletion requires explicit confirmed=true")
    with _locked_directory(data_dir) as (directory, path):
        filename = f"{member_id}.json"
        record, before = _read_record(directory, filename, member_id)
        _expect_record(record, expected_record_id)
        if expected_revision != record["revision"]:
            raise NutritionError("revision_conflict", "The current revision differs from the deletion confirmation",
                                 {"expected_revision": expected_revision, "current_revision": record["revision"]})
        if record["storage_schema"] in {LONG_TERM_SCHEMA, DELETE_SCHEMA} or _archive_inventory(directory, record):
            return _delete_long_term(directory, path, filename, record, before)
        _ensure_unchanged(directory, filename, before)
        os.unlink(filename, dir_fd=directory)
        try:
            os.fsync(directory)
        except OSError:
            raise NutritionError("storage_durability_uncertain", "The file was removed but durability is unconfirmed; check the member record before retrying",
                                 {"operation": "delete_record", "deletion_visible": True}) from None
        result = _result(path, member_id, record["revision"], record["record_id"])
        result["deleted"] = True
        return result


def _delete_long_term(directory, path, filename, record, before):
    """Mark a deletion durably before removing any referenced archive."""
    pending = record.get("deletion_pending") is True
    archives = []
    references = record.get("deletion_archives", []) if pending else _archive_inventory(directory, record)
    for reference in references:
        _, info = _read_archive(directory, record["member_id"], record["record_id"], reference, missing_ok=pending)
        archives.append((reference, info))
    if not pending:
        marker = {"storage_schema": DELETE_SCHEMA, "member_id": record["member_id"], "record_id": record["record_id"],
                  "revision": record["revision"], "deletion_pending": True, "deletion_archives": references}
        marker_raw = _json_bytes(marker)
        if len(marker_raw) > MAX_RECORD_BYTES:
            raise NutritionError("storage_size_limit", "The deletion recovery marker would exceed 4 MiB; nothing was deleted")
        _atomic_write(directory, filename, marker_raw, before, operation="delete_record")
        record, before = _read_record(directory, filename, record["member_id"])
    else:
        # A previous marker replacement may have reported uncertain directory
        # durability. Make it durable before unlinking any remaining archive.
        try:
            os.fsync(directory)
        except OSError:
            raise NutritionError("storage_durability_uncertain", "The deletion marker's durability is unconfirmed; no further archive was removed",
                                 {"operation": "delete_record", "deletion_pending": True}) from None
    for reference, info in archives:
        if info is not None:
            _ensure_unchanged(directory, reference["filename"], info)
            os.unlink(reference["filename"], dir_fd=directory)
    try:
        # Persist archive removals while the durable marker still permits recovery.
        os.fsync(directory)
    except OSError:
        raise NutritionError("storage_durability_uncertain", "Archive removal durability is unconfirmed; the deletion marker remains and the same confirmed deletion can resume",
                             {"operation": "delete_record", "deletion_pending": True}) from None
    _ensure_unchanged(directory, filename, before)
    os.unlink(filename, dir_fd=directory)
    try:
        os.fsync(directory)
    except OSError:
        raise NutritionError("storage_durability_uncertain", "The member and referenced archives were removed but durability is unconfirmed; reconcile before retrying",
                             {"operation": "delete_record", "deletion_visible": True}) from None
    result = _result(path, record["member_id"], record["revision"], record["record_id"])
    result.update(deleted=True, deletion_scope="member_and_owned_archives", archived_segments_deleted=len(archives))
    return result
