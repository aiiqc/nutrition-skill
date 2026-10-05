"""Explicit private POSIX storage for one member and bounded revision history."""

from contextlib import contextmanager
from copy import deepcopy
import errno
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
MAX_REVISIONS = 50
MAX_RECORD_BYTES = 4 * 1024 * 1024
LOCK_TIMEOUT_SECONDS = 1.0
_SOURCE_ROOT = Path(__file__).resolve().parents[1]


def _member_id(member_id):
    if not isinstance(member_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", member_id):
        raise NutritionError("invalid_member_id", "member_id must be a supported lowercase identifier")
    return member_id


def _revision(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or not (0 if allow_zero else 1) <= value <= MAX_REVISIONS:
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
        fields = {"storage_schema", "member_id", "record_id", "revision", "versions"}
        require_keys(record, fields, fields, "stored record")
        if record["storage_schema"] != STORAGE_SCHEMA or record["member_id"] != member_id:
            raise NutritionError("storage_invalid_record", "This file is not the requested managed member record")
        _record_id(record["record_id"])
        revision = _revision(record["revision"])
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


def _read_record(directory, filename, member_id, *, missing_ok=False):
    try:
        descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        if missing_ok:
            return None, None
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
    return _validate_record(record, member_id), before


def _ensure_unchanged(directory, filename, before):
    try:
        current = os.stat(filename, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        current = None
    if current is not None:
        _private(current)
    if (before is None) != (current is None) or (before is not None and _signature(before) != _signature(current)):
        raise NutritionError("storage_conflict", "The member file changed outside this storage operation")


def _atomic_write(directory, filename, raw, before):
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
                                 {"operation": "save_record", "replacement_visible": True}) from None
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
            _expect_record(record, expected_record_id)
        if current >= MAX_REVISIONS:
            raise NutritionError("storage_revision_limit", "The 50-revision limit has been reached; no history was removed")
        if record is None:
            record = {"storage_schema": STORAGE_SCHEMA, "member_id": member_id,
                      "record_id": secrets.token_hex(16), "revision": 0, "versions": []}
        record["revision"] = current + 1
        record["versions"].append({"revision": current + 1, "document": document})
        try:
            raw = (json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise NutritionError("storage_invalid_document", "The document cannot be serialized as bounded structured JSON") from None
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
        selected = record["revision"] if version is None else version
        if selected > record["revision"]:
            raise NutritionError("storage_version_not_found", "The requested historical revision does not exist")
        result = _result(path, member_id, selected, record["record_id"])
        result.update(document=deepcopy(record["versions"][selected - 1]["document"]),
                      current_revision=record["revision"], available_versions=list(range(1, record["revision"] + 1)))
        return result


def export_record(data_dir: str | os.PathLike[str], member_id: str) -> dict:
    """Return all managed structured history; do not write an export destination."""
    member_id = _member_id(member_id)
    with _locked_directory(data_dir) as (directory, path):
        record, _ = _read_record(directory, f"{member_id}.json", member_id)
        result = _result(path, member_id, record["revision"], record["record_id"])
        result["record"] = deepcopy(record)
        return result


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
