"""Off-path, atomic transport for canonical PAPER portfolio dashboard snapshots.

This module is intentionally independent from strategy, provider, and execution
code.  The authoritative PortfolioAccounting writer publishes inception/export
files; a separate process may package those files and move the package to another
host.  The receiving side validates the package and atomically advances a local
read-only generation pointer consumed by the dashboard.

Nothing here initializes a portfolio, acquires market data, performs conversion,
or writes back to the trading runtime.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

from .portfolio_accounting import LANES, SCHEMA_EXPORT, canonical, validate_inception


SCHEMA_SNAPSHOT = "meme-machine-dashboard-snapshot-v1"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_BUNDLE_BYTES = 9 * 1024 * 1024
MAX_RETAINED_GENERATIONS = 4
DEFAULT_RETAINED_GENERATIONS = 2
IDENTITY_FIELDS = ("source_sha", "policy_hash", "config_hash", "source_diff_sha256")
_HEX = re.compile(r"^[0-9a-f]{40,128}$")
_GENERATION = re.compile(r"^generation-([0-9]{20})-([0-9a-f]{12})$")


class SnapshotTransportError(RuntimeError):
    """Fail-closed snapshot transport boundary."""


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _stamp(value):
    if not isinstance(value, str):
        raise SnapshotTransportError("snapshot_timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SnapshotTransportError("invalid_snapshot_timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotTransportError("snapshot_timestamp_must_be_aware")
    return parsed


def _read_bounded(path, limit):
    path = Path(path)
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > limit:
                raise SnapshotTransportError("snapshot_input_capacity")
            data = stream.read(limit + 1)
    except OSError as error:
        raise SnapshotTransportError("snapshot_input_unavailable") from error
    if len(data) > limit:
        raise SnapshotTransportError("snapshot_input_capacity")
    return data


def _loads(data, *, error_code):
    try:
        value = json.loads(data.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise SnapshotTransportError(error_code) from error
    if not isinstance(value, dict):
        raise SnapshotTransportError(error_code)
    return value


def _reject_float(value):
    if isinstance(value, float):
        raise SnapshotTransportError("binary_float_forbidden")
    if isinstance(value, dict):
        for child in value.values():
            _reject_float(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_float(child)


def _identity_hash(value):
    if value is None:
        return
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise SnapshotTransportError("invalid_source_identity")


def _source_identity(export):
    portfolio = {}
    for field in IDENTITY_FIELDS:
        value = export.get(field)
        if value is not None:
            _identity_hash(value)
            portfolio[field] = value
    lanes = export.get("lane_identities")
    if not isinstance(lanes, dict) or set(lanes) != set(LANES):
        raise SnapshotTransportError("lane_identity_binding_required")
    normalized = {}
    for lane in LANES:
        row = lanes[lane]
        if not isinstance(row, dict):
            raise SnapshotTransportError("invalid_lane_identity")
        selected = {}
        for field in IDENTITY_FIELDS:
            value = row.get(field)
            if value is not None:
                _identity_hash(value)
                selected[field] = value
        if "source_sha" not in selected or "policy_hash" not in selected:
            raise SnapshotTransportError("lane_source_policy_identity_required")
        normalized[lane] = selected
    return {"portfolio": portfolio, "lanes": normalized}


def _validate_export(export, receipt):
    _reject_float(export)
    if export.get("schema") != SCHEMA_EXPORT or export.get("mode") != "canonical":
        raise SnapshotTransportError("canonical_export_required")
    receipt_hash = _digest(receipt)
    if export.get("epoch_id") != receipt["epoch_id"]:
        raise SnapshotTransportError("snapshot_epoch_mismatch")
    if export.get("inception_sha256") != receipt_hash:
        raise SnapshotTransportError("snapshot_inception_mismatch")
    if export.get("complete_lifecycle_coverage") is not True:
        raise SnapshotTransportError("complete_lifecycle_coverage_required")
    sequence = export.get("sequence")
    if type(sequence) is not int or sequence < 0:
        raise SnapshotTransportError("invalid_snapshot_sequence")
    as_of = _stamp(export.get("as_of"))
    valid_until = _stamp(export.get("valid_until"))
    if as_of < _stamp(receipt["inception_at"]) or valid_until < as_of:
        raise SnapshotTransportError("invalid_snapshot_validity")
    positions = export.get("positions")
    history = export.get("history")
    if not isinstance(positions, list) or len(positions) > 5000:
        raise SnapshotTransportError("snapshot_position_capacity")
    if not isinstance(history, list) or len(history) > 2000:
        raise SnapshotTransportError("snapshot_history_capacity")
    if export.get("external_adjustments") not in (None, []):
        raise SnapshotTransportError("unsupported_external_adjustments")
    return {
        "sequence": sequence,
        "as_of": export["as_of"],
        "valid_until": export["valid_until"],
        "source_identity": _source_identity(export),
    }


def build_snapshot(receipt, export):
    """Build one deterministic transport bundle from already-published facts."""
    receipt = validate_inception(deepcopy(receipt))
    export = deepcopy(export)
    checked = _validate_export(export, receipt)
    receipt_hash = _digest(receipt)
    body = {
        "schema": SCHEMA_SNAPSHOT,
        "epoch_id": receipt["epoch_id"],
        "inception_sha256": receipt_hash,
        "sequence": checked["sequence"],
        "as_of": checked["as_of"],
        "valid_until": checked["valid_until"],
        "source_identity_sha256": _digest(checked["source_identity"]),
        "receipt_sha256": receipt_hash,
        "export_sha256": _digest(export),
        "receipt": receipt,
        "export": export,
    }
    result = dict(body)
    result["snapshot_sha256"] = _digest(body)
    return result


def validate_snapshot(value):
    """Validate hashes, epoch binding, identities, and canonical export semantics."""
    if not isinstance(value, dict) or value.get("schema") != SCHEMA_SNAPSHOT:
        raise SnapshotTransportError("snapshot_schema")
    snapshot_hash = value.get("snapshot_sha256")
    if not isinstance(snapshot_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot_hash):
        raise SnapshotTransportError("snapshot_hash")
    body = {key: deepcopy(child) for key, child in value.items() if key != "snapshot_sha256"}
    if _digest(body) != snapshot_hash:
        raise SnapshotTransportError("snapshot_hash_mismatch")
    receipt = validate_inception(deepcopy(value.get("receipt")))
    export = deepcopy(value.get("export"))
    checked = _validate_export(export, receipt)
    if value.get("epoch_id") != receipt["epoch_id"]:
        raise SnapshotTransportError("snapshot_epoch_mismatch")
    receipt_hash = _digest(receipt)
    if value.get("inception_sha256") != receipt_hash or value.get("receipt_sha256") != receipt_hash:
        raise SnapshotTransportError("snapshot_inception_mismatch")
    if value.get("export_sha256") != _digest(export):
        raise SnapshotTransportError("snapshot_export_hash_mismatch")
    if value.get("sequence") != checked["sequence"]:
        raise SnapshotTransportError("snapshot_sequence_mismatch")
    if value.get("as_of") != checked["as_of"] or value.get("valid_until") != checked["valid_until"]:
        raise SnapshotTransportError("snapshot_clock_mismatch")
    if value.get("source_identity_sha256") != _digest(checked["source_identity"]):
        raise SnapshotTransportError("snapshot_source_identity_mismatch")
    return value


def _json_bytes(value):
    return (canonical(value) + "\n").encode("utf-8")


def _fsync_directory(path):
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path, value, *, mode=0o440):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(value)
    if len(data) > MAX_BUNDLE_BYTES:
        raise SnapshotTransportError("snapshot_output_capacity")
    handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{path.name}.", suffix=".tmp",
        dir=path.parent, delete=False,
    )
    temp = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temp.unlink()
        except OSError:
            pass
        raise


def publish_snapshot(receipt_path, export_path, bundle_path):
    """Package current authoritative projections without mutating their producer."""
    receipt = _loads(
        _read_bounded(receipt_path, MAX_SOURCE_BYTES),
        error_code="invalid_inception_projection",
    )
    export = _loads(
        _read_bounded(export_path, MAX_SOURCE_BYTES),
        error_code="invalid_accounting_projection",
    )
    bundle = build_snapshot(receipt, export)
    _atomic_json(bundle_path, bundle)
    return deepcopy(bundle)


def load_snapshot(bundle_path):
    value = _loads(
        _read_bounded(bundle_path, MAX_BUNDLE_BYTES),
        error_code="invalid_snapshot_bundle",
    )
    return validate_snapshot(value)


def _write_generation(root, generation, bundle):
    target = root / generation
    if target.exists():
        existing = load_snapshot(target / "snapshot.json")
        if existing["snapshot_sha256"] != bundle["snapshot_sha256"]:
            raise SnapshotTransportError("generation_equivocation")
        return target
    staging = root / f".{generation}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        staging.mkdir(mode=0o700)
        _atomic_json(staging / "inception.json", bundle["receipt"])
        _atomic_json(staging / "accounting.json", bundle["export"])
        _atomic_json(staging / "snapshot.json", bundle)
        _fsync_directory(staging)
        os.replace(staging, target)
        _fsync_directory(root)
        return target
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _current_bundle(root):
    current = root / "current"
    if not current.exists():
        return None
    if not current.is_symlink():
        raise SnapshotTransportError("replica_current_pointer_invalid")
    try:
        target = current.resolve(strict=True)
    except OSError as error:
        raise SnapshotTransportError("replica_current_pointer_invalid") from error
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise SnapshotTransportError("replica_pointer_escape") from error
    return load_snapshot(target / "snapshot.json")


def _advance_pointer(root, generation):
    current = root / "current"
    temporary = root / f".current.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        os.symlink(generation, temporary)
        os.replace(temporary, current)
        _fsync_directory(root)
    finally:
        try:
            if temporary.exists() or temporary.is_symlink():
                temporary.unlink()
        except OSError:
            pass


def _cleanup_generations(root, *, retain):
    generations = []
    for path in root.iterdir():
        match = _GENERATION.fullmatch(path.name)
        if path.is_dir() and match:
            generations.append((int(match.group(1)), path.name, path))
    generations.sort(reverse=True)
    for _sequence, _name, path in generations[retain:]:
        shutil.rmtree(path)


def apply_snapshot(bundle_path, replica_root, *, retain=DEFAULT_RETAINED_GENERATIONS):
    """Validate then atomically expose a local dashboard replica generation."""
    if type(retain) is not int or not 1 <= retain <= MAX_RETAINED_GENERATIONS:
        raise SnapshotTransportError("snapshot_retention_bounds")
    bundle = load_snapshot(bundle_path)
    root = Path(replica_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = _current_bundle(root)
    if current is not None:
        if current["epoch_id"] != bundle["epoch_id"]:
            raise SnapshotTransportError("replica_cross_epoch")
        if current["inception_sha256"] != bundle["inception_sha256"]:
            raise SnapshotTransportError("replica_inception_changed")
        if current["source_identity_sha256"] != bundle["source_identity_sha256"]:
            raise SnapshotTransportError("replica_source_identity_changed")
        if bundle["sequence"] < current["sequence"]:
            raise SnapshotTransportError("replica_sequence_regression")
        if bundle["sequence"] == current["sequence"]:
            if bundle["snapshot_sha256"] != current["snapshot_sha256"]:
                raise SnapshotTransportError("replica_sequence_equivocation")
            paths = current_paths(root)
            return {
                "applied": False,
                "idempotent": True,
                "sequence": bundle["sequence"],
                "snapshot_sha256": bundle["snapshot_sha256"],
                **paths,
            }

    generation = (
        f"generation-{bundle['sequence']:020d}-"
        f"{bundle['snapshot_sha256'][:12]}"
    )
    _write_generation(root, generation, bundle)
    _advance_pointer(root, generation)
    _cleanup_generations(root, retain=retain)
    return {
        "applied": True,
        "idempotent": False,
        "sequence": bundle["sequence"],
        "snapshot_sha256": bundle["snapshot_sha256"],
        **current_paths(root),
    }


def current_paths(replica_root):
    """Return fixed read-only paths suitable for dashboard Reader/start flags."""
    root = Path(replica_root)
    current = root / "current"
    return {
        "inception_path": str(current / "inception.json"),
        "accounting_path": str(current / "accounting.json"),
        "snapshot_path": str(current / "snapshot.json"),
    }


def mirror_once(receipt_path, export_path, bundle_path, replica_root, *, retain=DEFAULT_RETAINED_GENERATIONS):
    """Offline/local proof helper; production topology may copy bundle between steps."""
    publish_snapshot(receipt_path, export_path, bundle_path)
    return apply_snapshot(bundle_path, replica_root, retain=retain)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    publish = commands.add_parser("publish")
    publish.add_argument("--inception", required=True)
    publish.add_argument("--accounting", required=True)
    publish.add_argument("--bundle", required=True)

    apply = commands.add_parser("apply")
    apply.add_argument("--bundle", required=True)
    apply.add_argument("--replica-root", required=True)
    apply.add_argument("--retain", type=int, default=DEFAULT_RETAINED_GENERATIONS)

    mirror = commands.add_parser("mirror-once")
    mirror.add_argument("--inception", required=True)
    mirror.add_argument("--accounting", required=True)
    mirror.add_argument("--bundle", required=True)
    mirror.add_argument("--replica-root", required=True)
    mirror.add_argument("--retain", type=int, default=DEFAULT_RETAINED_GENERATIONS)

    args = parser.parse_args(argv)
    if args.command == "publish":
        result = publish_snapshot(args.inception, args.accounting, args.bundle)
        output = {
            "schema": result["schema"],
            "epoch_id": result["epoch_id"],
            "sequence": result["sequence"],
            "snapshot_sha256": result["snapshot_sha256"],
        }
    elif args.command == "apply":
        output = apply_snapshot(args.bundle, args.replica_root, retain=args.retain)
    else:
        output = mirror_once(
            args.inception, args.accounting, args.bundle, args.replica_root,
            retain=args.retain,
        )
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
