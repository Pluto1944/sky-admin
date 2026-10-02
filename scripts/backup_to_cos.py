#!/usr/bin/env python3
"""Create a recoverable daily backup on an existing COS FUSE mount.

The final ``manifest.json`` is written only after every payload is copied and
hash-verified. A directory without a manifest is incomplete and cannot be
used for recovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MOUNT = "/sky_coc"
DEFAULT_PREFIX = "rebuild/sky-admin"

# ``python scripts/backup_to_cos.py`` puts scripts/ rather than the repository
# root on sys.path, while the project configuration lives at the root.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path* without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sqlite(path: Path) -> None:
    """Fail unless a read-only SQLite integrity check succeeds."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute("PRAGMA integrity_check").fetchall()
    finally:
        connection.close()
    if rows != [("ok",)]:
        raise RuntimeError(f"SQLite integrity check failed for {path.name}: {rows!r}")


def snapshot_sqlite(source_path: Path, target_path: Path) -> None:
    """Use SQLite Online Backup API to make a consistent copy of a live database."""
    if not source_path.is_file():
        raise FileNotFoundError(f"database does not exist: {source_path}")
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        with target:
            source.backup(target)
    finally:
        target.close()
        source.close()
    verify_sqlite(target_path)


def is_cosfs_mount(mount: Path) -> bool:
    """Return whether *mount* is an active fuse.cosfs mount.

    The check prevents a missing FUSE mount from turning a COS backup into a
    local write below /sky_coc.
    """
    if not mount.is_dir():
        return False
    mountpoint = subprocess.run(
        ["mountpoint", "-q", str(mount)], check=False, capture_output=True
    )
    if mountpoint.returncode != 0:
        return False
    filesystem = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", str(mount)],
        check=False,
        capture_output=True,
        text=True,
    )
    return filesystem.returncode == 0 and filesystem.stdout.strip() == "fuse.cosfs"


def safe_prefix(value: str) -> PurePosixPath:
    """Validate a relative COS path prefix."""
    prefix = PurePosixPath(value)
    if not value or prefix.is_absolute() or ".." in prefix.parts or str(prefix) == ".":
        raise ValueError("prefix must be a non-empty relative path without '..'")
    return prefix


def git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def create_git_bundle(target: Path) -> None:
    subprocess.run(
        ["git", "bundle", "create", str(target), "--all"],
        cwd=PROJECT_ROOT,
        check=True,
    )
    subprocess.run(["git", "bundle", "verify", str(target)], check=True, capture_output=True)


def iter_context_paths() -> Iterable[Path]:
    """Yield recovery context, excluding all local databases and backups."""
    fixed_paths = [
        PROJECT_ROOT / "config" / "settings.yaml",
        PROJECT_ROOT / ".env.example",
        PROJECT_ROOT / "requirements.txt",
        PROJECT_ROOT / "deploy",
    ]
    for path in fixed_paths:
        if path.exists():
            yield path

    data_dir = PROJECT_ROOT / "data"
    if data_dir.exists():
        for path in sorted(data_dir.rglob("*")):
            if path.is_file() and path.suffix != ".db" and "backups" not in path.parts:
                yield path


def create_context_archive(target: Path) -> None:
    """Archive selected recovery context; .env and database files stay excluded."""
    with tarfile.open(target, "w:gz") as archive:
        for path in iter_context_paths():
            archive.add(path, arcname=path.relative_to(PROJECT_ROOT), recursive=path.is_dir())


def copy_and_verify(source: Path, destination: Path) -> str:
    """Copy a payload via a temporary name, then verify COS contents by SHA-256."""
    temporary = destination.with_name(f".{destination.name}.uploading")
    if temporary.exists():
        raise RuntimeError(f"unexpected stale upload path: {temporary}")
    shutil.copy2(source, temporary)
    local_digest = sha256_file(source)
    remote_digest = sha256_file(temporary)
    if remote_digest != local_digest:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch after upload: {destination.name}")
    temporary.rename(destination)
    return local_digest


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def backup(
    *, mount: Path, prefix: PurePosixPath, dry_run: bool, now: datetime | None = None
) -> Path | None:
    """Create and publish one backup. Return remote directory, or None for dry run."""
    from shared.config.env_loader import load_env

    load_env()
    import config
    from modules.war_layout.settings import WarLayoutSettings

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    main_db = (PROJECT_ROOT / config.DB_PATH).resolve()
    war_layout_db = WarLayoutSettings.from_env().db_path.resolve()
    sources = [("league.db", main_db)]
    if war_layout_db.is_file():
        sources.append(("war_layout.db", war_layout_db))

    with tempfile.TemporaryDirectory(prefix="sky-admin-cos-backup-") as temporary_name:
        temporary = Path(temporary_name)
        payloads: list[tuple[str, Path]] = []
        for filename, source in sources:
            snapshot = temporary / filename
            snapshot_sqlite(source, snapshot)
            payloads.append((filename, snapshot))

        bundle = temporary / "sky-admin.bundle"
        create_git_bundle(bundle)
        payloads.append((bundle.name, bundle))

        context_archive = temporary / "recovery-context.tar.gz"
        create_context_archive(context_archive)
        payloads.append((context_archive.name, context_archive))

        checksums = {filename: sha256_file(path) for filename, path in payloads}
        manifest = {
            "schema_version": 1,
            "created_at_utc": timestamp,
            "git_revision": git_revision(),
            "payloads": [
                {"name": filename, "sha256": checksums[filename], "size_bytes": path.stat().st_size}
                for filename, path in payloads
            ],
            "secret_policy": "The project .env and all credentials are deliberately excluded.",
        }
        sums_path = temporary / "SHA256SUMS"
        sums_path.write_text(
            "".join(f"{checksums[filename]}  {filename}\n" for filename, _ in payloads),
            encoding="utf-8",
        )
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)

        if dry_run:
            print(f"dry run verified {len(payloads)} payloads; no COS data written")
            return None

        if not is_cosfs_mount(mount):
            raise RuntimeError(f"refusing backup: {mount} is not an active fuse.cosfs mount")
        destination = mount.joinpath(*prefix.parts, timestamp)
        destination.mkdir(mode=0o750, parents=True, exist_ok=False)
        for filename, path in payloads:
            copy_and_verify(path, destination / filename)
        copy_and_verify(sums_path, destination / sums_path.name)
        # Manifest last is the completion marker for recovery tooling.
        copy_and_verify(manifest_path, destination / manifest_path.name)
        print(f"backup complete: {destination}")
        return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount", default=os.getenv("COS_BACKUP_MOUNT", DEFAULT_MOUNT))
    parser.add_argument("--prefix", default=os.getenv("COS_BACKUP_PREFIX", DEFAULT_PREFIX))
    parser.add_argument("--dry-run", action="store_true", help="create and validate snapshots without COS writes")
    return parser.parse_args()


def main() -> int:
    # Parse configurable non-secret defaults only after the repository .env has
    # been loaded. Explicit process environment still takes precedence.
    from shared.config.env_loader import load_env

    load_env()
    args = parse_args()
    try:
        backup(mount=Path(args.mount), prefix=safe_prefix(args.prefix), dry_run=args.dry_run)
    except Exception as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
