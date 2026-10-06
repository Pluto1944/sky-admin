from scripts.verify_runtime_version import verify_runtime_payload


def _payload(commit="a" * 40):
    component = {
        "release_version": "v1.3.0",
        "git_commit": commit,
        "tracked_dirty": False,
        "health": "healthy",
    }
    return {
        "consistent": True,
        "components": {"api": dict(component), "scheduler": dict(component)},
    }


def test_verify_runtime_payload_accepts_expected_components():
    assert verify_runtime_payload(_payload(), "v1.3.0", "a" * 40) == []


def test_verify_runtime_payload_rejects_stale_scheduler():
    payload = _payload()
    payload["consistent"] = False
    payload["components"]["scheduler"]["health"] = "stale"

    errors = verify_runtime_payload(payload, "v1.3.0", "a" * 40)

    assert "scheduler 状态不是 healthy" in errors
    assert "API 与调度器运行身份不一致" in errors
