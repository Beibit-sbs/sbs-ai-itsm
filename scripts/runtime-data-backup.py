#!/usr/bin/env python3
"""Create and safely restore encrypted application runtime-data archives."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import time
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from backup_crypto import decrypt_file, encrypt_file, load_backup_key  # noqa: E402


DEFAULT_SOURCES = (Path("backend/uploads"), Path("backend/static"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest(root: Path, paths: list[Path]) -> tuple[list[Path], list[dict[str, object]]]:
    existing: list[Path] = []
    entries: list[dict[str, object]] = []
    for relative in paths:
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"runtime-data source must be repository-relative: {relative}")
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise RuntimeError(f"runtime-data source escapes repository: {relative}")
        if not resolved.exists():
            continue
        existing.append(relative)
        all_paths = sorted(resolved.rglob("*"))
        symbolic_link = next((path for path in all_paths if path.is_symlink()), None)
        if symbolic_link is not None:
            raise RuntimeError(
                f"symbolic links are not allowed in runtime data: {symbolic_link}"
            )
        for file_path in (path for path in all_paths if path.is_file()):
            entries.append(
                {
                    "path": file_path.relative_to(root).as_posix(),
                    "bytes": file_path.stat().st_size,
                    "sha256": sha256_file(file_path),
                }
            )
    return existing, entries


def create_archive(
    *,
    root: Path,
    sources: list[Path],
    archive: Path,
    encryption_key_file: Path,
) -> dict[str, object]:
    if archive.exists():
        raise RuntimeError(f"refusing to overwrite runtime-data backup: {archive}")
    existing, entries = _source_manifest(root, sources)
    if not existing:
        raise RuntimeError("none of the configured runtime-data directories exist")
    started = time.perf_counter()
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=archive.parent, prefix=".runtime-backup-") as temp_dir:
        plain = Path(temp_dir) / "runtime-data.tar.gz"
        with tarfile.open(plain, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
            for relative in existing:
                bundle.add(root / relative, arcname=relative.as_posix(), recursive=True)
        encrypt_file(plain, archive, load_backup_key(encryption_key_file))
    manifest: dict[str, object] = {
        "format": "sbs-runtime-data-backup-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "artifact": archive.name,
        "artifact_bytes": archive.stat().st_size,
        "artifact_sha256": sha256_file(archive),
        "source_roots": [path.as_posix() for path in existing],
        "file_count": len(entries),
        "source_bytes": sum(int(entry["bytes"]) for entry in entries),
        "files": entries,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }
    manifest_path = archive.with_name(archive.name + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def _validate_members(members: list[tarfile.TarInfo]) -> None:
    for member in members:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise RuntimeError(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise RuntimeError(f"unsupported archive member type: {member.name}")


def restore_archive(
    *,
    archive: Path,
    target_root: Path,
    encryption_key_file: Path,
    confirm_restore: bool,
) -> dict[str, object]:
    if not confirm_restore:
        raise RuntimeError("restore blocked; pass --confirm-restore")
    if not archive.is_file():
        raise RuntimeError(f"runtime-data backup does not exist: {archive}")
    manifest_path = archive.with_name(archive.name + ".manifest.json")
    if not manifest_path.is_file():
        raise RuntimeError("runtime-data backup manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256_file(archive) != manifest.get("artifact_sha256"):
        raise RuntimeError("runtime-data backup checksum does not match its manifest")
    if target_root.exists() and any(target_root.iterdir()):
        raise RuntimeError(f"restore target must be empty: {target_root}")
    target_root.parent.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(dir=target_root.parent, prefix=".runtime-restore-") as temp_dir:
        plain = Path(temp_dir) / "runtime-data.tar.gz"
        decrypt_file(archive, plain, load_backup_key(encryption_key_file))
        with tarfile.open(plain, "r:gz") as bundle:
            members = bundle.getmembers()
            _validate_members(members)
            bundle.extractall(target_root, members=members, filter="data")
    restored_files = [
        path for path in target_root.rglob("*") if path.is_file()
    ]
    return {
        "restored_to": str(target_root),
        "file_count": len(restored_files),
        "restored_bytes": sum(path.stat().st_size for path in restored_files),
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("--source", action="append", type=Path, default=[])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--target-root", type=Path, default=Path("backups/runtime-restore"))
    parser.add_argument("--encryption-key-file", type=Path, required=True)
    parser.add_argument("--confirm-restore", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    archive = args.archive or Path("backups/data") / f"{timestamp}_runtime-data.tar.gz.enc"
    archive = archive if archive.is_absolute() else root / archive
    key_file = (
        args.encryption_key_file
        if args.encryption_key_file.is_absolute()
        else root / args.encryption_key_file
    )
    target_root = args.target_root if args.target_root.is_absolute() else root / args.target_root
    try:
        if args.action == "backup":
            manifest = create_archive(
                root=root,
                sources=args.source or list(DEFAULT_SOURCES),
                archive=archive,
                encryption_key_file=key_file,
            )
            print(json.dumps(manifest, sort_keys=True))
        else:
            result = restore_archive(
                archive=archive,
                target_root=target_root,
                encryption_key_file=key_file,
                confirm_restore=args.confirm_restore,
            )
            print(json.dumps(result, sort_keys=True))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
