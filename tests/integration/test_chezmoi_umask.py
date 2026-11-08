"""Apply managed files in disposable homes to check modes ignore the caller's umask."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHEZMOI = shutil.which("chezmoi")


def run_chezmoi_in_home(home: Path, umask: int, *args: str) -> None:
    assert CHEZMOI is not None, "Missing integration prerequisite: chezmoi"
    subprocess.run(
        [
            CHEZMOI,
            "--source",
            str(REPO),
            "--destination",
            str(home),
            "--config",
            str(home / "chezmoi.toml"),
            "--cache",
            str(home / "chezmoi-cache"),
            "--persistent-state",
            str(home / "state.db"),
            "--no-tty",
            *args,
        ],
        env={"HOME": str(home), "PATH": os.environ["PATH"], "LC_ALL": "C"},
        cwd=home,
        check=True,
        capture_output=True,
        timeout=30,
        preexec_fn=lambda: os.umask(umask),
    )


@pytest.mark.parametrize("caller_umask", [0o077, 0o002])
def test_applied_file_mode_ignores_caller_umask(
    tmp_path: Path, caller_umask: int
) -> None:
    home = tmp_path / f"chezmoi-umask-{caller_umask:03o}"
    home.mkdir(mode=0o700)
    (home / ".chezmoi-profile").write_text("personal\n")
    run_chezmoi_in_home(home, caller_umask, "init")
    run_chezmoi_in_home(
        home, caller_umask, "apply", "--exclude=scripts", str(home / ".zshrc")
    )
    assert stat.S_IMODE((home / ".zshrc").stat().st_mode) == 0o644
