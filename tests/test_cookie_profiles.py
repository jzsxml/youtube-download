from app.core.cookie_profiles import delete_profile


def test_delete_profile_rejects_path_traversal_id() -> None:
    assert delete_profile("../../bad") is False
    assert delete_profile("not-hex-id!") is False