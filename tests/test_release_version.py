from pathlib import Path

import pytest

import api_server.routes as routes
from shared.release import read_release_version, validate_release_version


def test_validate_release_version_accepts_semver_tag():
    assert validate_release_version(" v1.1.1\n") == "v1.1.1"


@pytest.mark.parametrize("value", ["1.1.1", "v1.01.1", "v1.1", "v1.1.1-dev"])
def test_validate_release_version_rejects_non_release_tags(value):
    with pytest.raises(ValueError):
        validate_release_version(value)


def test_read_release_version_reads_declared_file(tmp_path: Path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("v2.0.3\n", encoding="utf-8")

    assert read_release_version(version_file) == "v2.0.3"


def test_ping_reports_declared_release_version():
    assert routes.ping()["version"] == read_release_version()
