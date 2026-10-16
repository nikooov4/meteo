import shutil
import subprocess

import pytest

from meteo_bridge.resources import git_metadata


def test_git_metadata_tracks_unborn_clean_and_dirty(tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git is optional at runtime")
    assert git_metadata(tmp_path)["git_revision"] == "not_a_git_repository"
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    assert git_metadata(tmp_path)["git_revision"] == "unborn_or_unavailable"
    (tmp_path / "file.txt").write_text("test", encoding="utf8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "file.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Metadata test",
                    "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
                    "commit", "-m", "metadata test"], check=True, capture_output=True)
    revision = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    assert git_metadata(tmp_path) == {"git_revision": revision, "git_dirty": False}
    (tmp_path / "file.txt").write_text("changed", encoding="utf8")
    assert git_metadata(tmp_path) == {"git_revision": revision, "git_dirty": True}
