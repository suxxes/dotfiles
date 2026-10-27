"""Check the command that tmux uses to start a new shell."""

import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class TmuxShellTest(unittest.TestCase):
    def test_new_pane_uses_zsh_when_parent_still_uses_fish(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tmux-shell-") as directory:
            root = Path(directory)
            config = root / "chezmoi.toml"
            config.write_text('[data]\nosType = "darwin"\nprofile = "personal"\n')
            rendered = subprocess.run(
                [
                    "chezmoi",
                    "-c",
                    str(config),
                    "execute-template",
                    "--left-delimiter",
                    "# {{",
                    "--right-delimiter",
                    "}}",
                ],
                input=(REPO / "dot_tmux.conf.tmpl").read_text(),
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            settings = {}
            for line in rendered.splitlines():
                words = shlex.split(line, comments=True)
                if len(words) == 4 and words[0] in ("set", "set-option"):
                    settings[words[2]] = words[3]
            self.assertEqual(settings["default-shell"], "/bin/zsh")
            # A test-owned executable replaces the shell at the final exec.
            shell = root / "zsh"
            shell.write_text('#!/bin/sh\nprintf "zsh-started:%s" "$*"\n')
            shell.chmod(0o700)
            command = settings["default-command"].replace("/bin/zsh", str(shell))
            result = subprocess.run(
                ["/bin/zsh", "-f", "-c", command],
                env={
                    **os.environ,
                    "HOME": str(root),
                    "SHELL": "/bin/false",
                    "TERM": "xterm",
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("zsh-started:-l", result.stdout)


if __name__ == "__main__":
    unittest.main()
