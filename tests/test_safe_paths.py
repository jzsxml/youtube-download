from pathlib import Path

from app.core.safe_paths import is_safe_output_file


def test_safe_output_under_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "dl"
    out_dir.mkdir()
    good = out_dir / "video.mp4"
    good.write_text("x", encoding="utf-8")
    assert is_safe_output_file(good, out_dir) is True


def test_rejects_outside_download_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "dl"
    out_dir.mkdir()
    outsider = tmp_path / "other" / "secret.exe"
    outsider.parent.mkdir()
    outsider.write_text("x", encoding="utf-8")
    assert is_safe_output_file(outsider, out_dir) is False


def test_rejects_missing_file(tmp_path: Path) -> None:
    out_dir = tmp_path / "dl"
    out_dir.mkdir()
    assert is_safe_output_file(out_dir / "nope.mp4", out_dir) is False