#!/usr/bin/env python3
"""将一个待发布 Git Tag 同步到后端和小程序的版本元数据。

此脚本只准备可提交文件，不创建或推送 Git Tag。创建 Tag 前后均应确认
VERSION 的内容和 Tag 完全一致。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_version(value: str) -> tuple[str, str, int]:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("版本号必须为 v主版本.次版本.修订版本，例如 v1.1.1")
    major, minor, patch = (int(part) for part in match.groups())
    plain = f"{major}.{minor}.{patch}"
    # 微信 versionCode 单调递增；每个分段预留两位。
    return f"v{plain}", plain, major * 10000 + minor * 100 + patch


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def prepare_release_version(version: str, root_dir: Path = ROOT_DIR) -> None:
    tag, plain, version_code = parse_version(version)
    (root_dir / "VERSION").write_text(f"{tag}\n", encoding="utf-8")

    release_js = root_dir / "uni-app" / "config" / "release.js"
    release_js.parent.mkdir(parents=True, exist_ok=True)
    release_js.write_text(
        "// 由 scripts/prepare_release_version.py 在发版前同步，必须与 Git Tag 一致。\n"
        f"export const APP_VERSION = '{tag}'\n",
        encoding="utf-8",
    )

    manifest_path = root_dir / "uni-app" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["versionName"] = plain
    manifest["versionCode"] = str(version_code)
    write_json(manifest_path, manifest)

    package_path = root_dir / "uni-app" / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = plain
    write_json(package_path, package)

    lock_path = root_dir / "uni-app" / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["version"] = plain
    if "" in lock.get("packages", {}):
        lock["packages"][""]["version"] = plain
    write_json(lock_path, lock)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="待发布 Git Tag，例如 v1.1.1")
    args = parser.parse_args()
    try:
        prepare_release_version(args.version)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
