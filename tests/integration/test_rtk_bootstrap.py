"""Run RTK setup with mise just installed and the original bootstrap PATH."""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_rtk_setup_finds_mise_installed_in_user_bin(tmp_path: Path) -> None:
    mise = tmp_path / ".local/bin/mise"
    mise.parent.mkdir(parents=True)
    mise.write_text(
        '#!/bin/sh\n'
        '[ "$*" = "activate bash --shims" ] || exit 1\n'
        'printf \'export PATH="$HOME/shims:$PATH"\\n\'\n'
    )
    mise.chmod(0o700)
    rtk = tmp_path / "shims/rtk"
    rtk.parent.mkdir()
    rtk.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$HOME/rtk-calls"\n')
    rtk.chmod(0o700)

    result = subprocess.run(
        ["/bin/bash", str(REPO / "run_onchange_after_install-rtk.sh")],
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )

    calls = tmp_path / "rtk-calls"
    assert calls.exists(), result.stderr
    assert calls.read_text().splitlines() == [
        "init --global --codex",
        "init --global --agent claude --auto-patch --trust-filters",
    ]
