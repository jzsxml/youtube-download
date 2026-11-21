from app.core.errors import (
    format_youtube_auth_hint,
    is_cookie_infrastructure_error,
    is_format_unavailable,
    is_login_required_message,
)


def test_login_required_age_gate() -> None:
    err = "ERROR: Sign in to confirm your age"
    assert is_login_required_message(err) is True


def test_login_required_generic_sign_in_not_enough() -> None:
    assert is_login_required_message("network sign in timeout") is False


def test_format_unavailable() -> None:
    assert is_format_unavailable("Requested format is not available") is True


def test_cookie_copy_error() -> None:
    assert is_cookie_infrastructure_error("Could not copy Chrome cookie database") is True


def test_auth_hint_appends_for_age() -> None:
    base = "Sign in to confirm your age"
    out = format_youtube_auth_hint(base, "none", False)
    assert "年龄" in out or "登录" in out