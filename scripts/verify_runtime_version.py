#!/usr/bin/env python3
"""部署后校验 API 与调度器是否运行预期发布提交。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.release import read_release_version  # noqa: E402


def _head_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip()


def verify_runtime_payload(payload: dict, expected_version: str, expected_commit: str) -> list[str]:
    errors: list[str] = []
    components = payload.get("components") or {}
    for name in ("api", "scheduler"):
        component = components.get(name) or {}
        if component.get("release_version") != expected_version:
            errors.append(f"{name} 版本不是 {expected_version}")
        if component.get("git_commit") != expected_commit:
            errors.append(f"{name} 提交不是 {expected_commit[:12]}")
        if component.get("health") != "healthy":
            errors.append(f"{name} 状态不是 healthy")
        if component.get("tracked_dirty"):
            errors.append(f"{name} 启动时存在已跟踪的未提交改动")
    if not payload.get("consistent"):
        errors.append("API 与调度器运行身份不一致")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/api/system/version",
        help="运行状态接口",
    )
    parser.add_argument("--expected-version", default=read_release_version())
    parser.add_argument("--expected-commit", default=None)
    args = parser.parse_args()
    expected_commit = args.expected_commit or _head_commit()

    try:
        with urlopen(args.url, timeout=5) as response:  # noqa: S310 - URL 由运维显式传入
            payload = json.load(response)
    except (OSError, URLError, ValueError) as exc:
        print(f"运行版本接口读取失败: {exc}", file=sys.stderr)
        return 2

    errors = verify_runtime_payload(payload, args.expected_version, expected_commit)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"OK: API 与调度器均运行 {args.expected_version} ({expected_commit[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
