"""进程启动时冻结的运行身份。

发布版本描述产品版本；Git 提交和工作区状态描述当前进程实际加载的代码。
这些值只应在进程启动时采集一次，避免磁盘代码更新但服务尚未重启时误报。
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from shared.release import VERSION_FILE, read_release_version


PROJECT_ROOT = VERSION_FILE.parent


@dataclass(frozen=True)
class RuntimeIdentity:
    component: str
    release_version: str
    git_commit: str
    git_describe: str
    tracked_dirty: bool
    started_at: str

    def as_dict(self) -> dict:
        return asdict(self)


def _git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def capture_runtime_identity(
    component: str,
    *,
    project_root: Path = PROJECT_ROOT,
    started_at: datetime | None = None,
) -> RuntimeIdentity:
    """采集并冻结一个组件的发布版本与 Git 身份。"""
    root = Path(project_root)
    version_file = root / "VERSION"
    commit = _git_output(root, "rev-parse", "HEAD") or "unknown"
    describe = _git_output(root, "describe", "--tags", "--always") or "unknown"
    tracked_changes = _git_output(root, "status", "--short", "--untracked-files=no")
    timestamp = (started_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return RuntimeIdentity(
        component=component,
        release_version=read_release_version(version_file),
        git_commit=commit,
        git_describe=describe,
        tracked_dirty=bool(tracked_changes),
        started_at=timestamp.isoformat(timespec="seconds"),
    )
