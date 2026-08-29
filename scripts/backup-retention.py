#!/usr/bin/env python3
"""Apply a safe grandfather-father-son retention policy to encrypted backups."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path


def retention_plan(
    artifacts: list[Path],
    *,
    daily: int,
    weekly: int,
    monthly: int,
) -> tuple[set[Path], set[Path]]:
    ordered = sorted(
        artifacts,
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    keep: set[Path] = set()
    buckets: dict[str, dict[object, Path]] = {
        "daily": {},
        "weekly": {},
        "monthly": {},
    }
    for artifact in ordered:
        stamp = datetime.fromtimestamp(artifact.stat().st_mtime, UTC)
        keys = {
            "daily": stamp.date(),
            "weekly": (stamp.isocalendar().year, stamp.isocalendar().week),
            "monthly": (stamp.year, stamp.month),
        }
        for kind, key in keys.items():
            buckets[kind].setdefault(key, artifact)
    for kind, limit in (("daily", daily), ("weekly", weekly), ("monthly", monthly)):
        keep.update(list(buckets[kind].values())[:limit])
    if ordered:
        keep.add(ordered[0])
    return keep, set(ordered) - keep


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("backups"))
    parser.add_argument("--daily", type=int, default=7)
    parser.add_argument("--weekly", type=int, default=4)
    parser.add_argument("--monthly", type=int, default=6)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete expired artifacts; without this flag the command is a dry run",
    )
    args = parser.parse_args()
    if min(args.daily, args.weekly, args.monthly) < 0:
        print("[FAIL] retention values cannot be negative")
        return 1

    repository = Path(__file__).resolve().parents[1]
    approved_root = (repository / "backups").resolve()
    root = args.root if args.root.is_absolute() else repository / args.root
    root = root.resolve()
    if root != approved_root and not root.is_relative_to(approved_root):
        print("[FAIL] retention root must stay within the repository backups directory")
        return 1
    if not root.exists():
        print(json.dumps({"mode": "dry-run", "kept": [], "expired": []}))
        return 0

    artifacts = sorted(path for path in root.rglob("*.enc") if path.is_file())
    streams: dict[Path, list[Path]] = {}
    for artifact in artifacts:
        streams.setdefault(artifact.parent, []).append(artifact)
    keep: set[Path] = set()
    expired: set[Path] = set()
    for stream_artifacts in streams.values():
        stream_keep, stream_expired = retention_plan(
            stream_artifacts,
            daily=args.daily,
            weekly=args.weekly,
            monthly=args.monthly,
        )
        keep.update(stream_keep)
        expired.update(stream_expired)
    removed: list[str] = []
    if args.apply:
        for artifact in sorted(expired):
            artifact.unlink()
            manifest = artifact.with_name(artifact.name + ".manifest.json")
            manifest.unlink(missing_ok=True)
            removed.append(str(artifact.relative_to(repository)))
    payload = {
        "mode": "apply" if args.apply else "dry-run",
        "policy": {
            "daily": args.daily,
            "weekly": args.weekly,
            "monthly": args.monthly,
        },
        "kept": sorted(str(path.relative_to(repository)) for path in keep),
        "expired": sorted(str(path.relative_to(repository)) for path in expired),
        "removed": removed,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
