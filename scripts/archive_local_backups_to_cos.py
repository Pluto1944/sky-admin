#!/usr/bin/env python3
"""Archive immutable local Sky Admin SQLite backups to the COS cold tier.

Only ``data/backups`` is eligible.  The live database, ``.env``, runtime
directories and arbitrary user paths are deliberately outside this tool's
scope.  Uploads are checksum-verified and a manifest is written last; local
copies are removed only with both ``--apply`` and ``--prune-local``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Direct execution places ``scripts/`` rather than the repository root on
# sys.path.  Keep this aligned with backup_to_cos.py, which is also run by
# systemd as a script file.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backup_to_cos import (  # noqa: E402
    DEFAULT_MOUNT,
    copy_and_verify,
    is_cosfs_mount,
    safe_prefix,
    sha256_file,
    verify_sqlite,
)


DEFAULT_SOURCE_DIR = PROJECT_ROOT / "data" / "backups"
DEFAULT_PREFIX = "archive/sky-admin/local-db-backups"
SQLITE_MAGIC = b"SQLite format 3\x00"


def is_sqlite_backup(path: Path) -> bool:
    """Identify SQLite by content, because historical names need not end in .db."""
    with path.open("rb") as source:
        return source.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC


def backup_files(source_dir: Path) -> list[Path]:
    """Return immutable SQLite backup files in deterministic order."""
    if not source_dir.is_dir():
        raise FileNotFoundError(f"backup source directory does not exist: {source_dir}")
    return sorted(
        (path for path in source_dir.iterdir() if path.is_file() and is_sqlite_backup(path)),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )


def local_prune_candidates(files: list[Path], keep_local: int) -> list[Path]:
    """Select all but the newest ``keep_local`` files for post-upload removal."""
    if keep_local < 0:
        raise ValueError("keep_local must be non-negative")
    newest_first = sorted(files, key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
    return newest_first[keep_local:]


def _manifest(created_at: str, files: list[Path], prefix: PurePosixPath) -> dict:
    return {
        "schema_version": 1,
        "created_at_utc": created_at,
        "source": "sky-admin/data/backups",
        "cold_archive_prefix": str(prefix),
        "payloads": [
            {"name": path.name, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
            for path in files
        ],
        "completion_rule": "manifest.json is written last after every payload checksum matches",
    }


def archive(
    *,
    mount: Path,
    prefix: PurePosixPath,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    apply: bool = False,
    prune_local: bool = False,
    keep_local: int = 2,
    now: datetime | None = None,
) -> Path | None:
    """Archive verified local SQLite backups and optionally prune older copies."""
    if prune_local and not apply:
        raise ValueError("--prune-local requires --apply")
    source_dir = source_dir.resolve()
    if source_dir != DEFAULT_SOURCE_DIR.resolve():
        raise ValueError("only the project data/backups directory may be archived")

    files = backup_files(source_dir)
    for path in files:
        verify_sqlite(path)
    prune_candidates = local_prune_candidates(files, keep_local)
    if not files:
        print("no local SQLite backups to archive")
        return None
    if not apply:
        print(
            f"dry run verified {len(files)} backup(s); "
            f"would retain {min(keep_local, len(files))} local backup(s)"
        )
        return None
    if not is_cosfs_mount(mount):
        raise RuntimeError(f"refusing archive: {mount} is not an active fuse.cosfs mount")

    created_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = mount.joinpath(*prefix.parts, created_at)
    destination.mkdir(mode=0o750, parents=True, exist_ok=False)
    manifest = _manifest(created_at, files, prefix)
    try:
        for path in files:
            copy_and_verify(path, destination / path.name)
        with tempfile.TemporaryDirectory(prefix="sky-admin-cos-archive-") as temporary_name:
            manifest_path = Path(temporary_name) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            copy_and_verify(manifest_path, destination / manifest_path.name)
    except Exception:
        # No local file is removed unless the archive completed and its marker exists.
        raise

    if prune_local:
        for path in prune_candidates:
            path.unlink()
        print(f"archive complete: {destination}; pruned {len(prune_candidates)} local backup(s)")
    else:
        print(f"archive complete: {destination}; local backups retained")
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount", default=os.getenv("COS_BACKUP_MOUNT", DEFAULT_MOUNT))
    parser.add_argument("--prefix", default=os.getenv("COS_LOCAL_BACKUP_ARCHIVE_PREFIX", DEFAULT_PREFIX))
    parser.add_argument("--apply", action="store_true", help="write the verified archive to COS")
    parser.add_argument("--prune-local", action="store_true", help="remove older local copies after a completed archive")
    parser.add_argument("--keep-local", type=int, default=2, help="number of newest local backups to retain")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        archive(
            mount=Path(args.mount),
            prefix=safe_prefix(args.prefix),
            apply=args.apply,
            prune_local=args.prune_local,
            keep_local=args.keep_local,
        )
    except Exception as exc:
        print(f"archive failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
