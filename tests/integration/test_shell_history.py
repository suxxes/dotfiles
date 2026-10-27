"""Exercise history migration using isolated homes and native shell consumers."""

import fcntl
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MIGRATOR = (
    Path(__file__).resolve().parents[2]
    / "dot_local/bin/executable_migrate-fish-history"
)
ZSH_READER = r"""
fc -p
HISTSIZE=1000000
fc -R "$1" || exit
print -s -- migration_reader_sentinel
zmodload zsh/parameter || exit
for event in ${(onk)history}; do
    stamp=$(fc -ln -t '%s' "$event" "$event") || exit
    print -rn -- "${stamp%% *}"$'\0'"${history[$event]}"$'\0'
done
"""


class ShellHistoryMigrationTests(unittest.TestCase):
    """All histories and subprocess environments belong to a temporary HOME."""

    def setUp(self) -> None:
        self.sandbox = tempfile.TemporaryDirectory(prefix="shell-history-test-")
        self.addCleanup(self.sandbox.cleanup)
        self.home = Path(self.sandbox.name)
        self.env = {
            "HOME": str(self.home),
            "PATH": os.environ["PATH"],
            "XDG_DATA_HOME": str(self.home / "data"),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_STATE_HOME": str(self.home / "state"),
            "ZDOTDIR": str(self.home / "zsh-config"),
            "LC_ALL": "C.UTF-8",
        }
        self.source = self.home / "data/fish/fish_history"
        self.source.parent.mkdir(parents=True)
        self.destination = self.home / ".zsh_history"
        self.fish = shutil.which("fish")
        self.zsh = shutil.which("zsh")
        self.assertIsNotNone(self.fish, "Real fish is required")
        self.assertIsNotNone(self.zsh, "Real zsh is required")

    def seed_fish(
        self, entries: list[tuple[int, str]], *, append: bool = False
    ) -> None:
        """Write fish's persisted fixture contract, including escaped newlines."""
        with self.source.open("a" if append else "w", encoding="utf-8") as stream:
            for timestamp, command in entries:
                escaped = command.replace("\\", "\\\\").replace("\n", "\\n")
                stream.write(f"- cmd: {escaped}\n  when: {timestamp}\n")

    def migrate(self, *, success: bool = True) -> subprocess.CompletedProcess[bytes]:
        """Run the actual helper without inheriting live shell settings."""
        result = subprocess.run(
            [str(MIGRATOR)],
            env=self.env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr.decode())
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def injected_migration(self, injection: str) -> subprocess.CompletedProcess[bytes]:
        """Inject filesystem failures in a child whose HOME is always disposable."""
        program = (
            "import os, runpy, sys; "
            "module = runpy.run_path(sys.argv[1], run_name='migration_test'); "
            + injection
            + "\nsys.argv = [sys.argv[1]]; sys.exit(module['main']())"
        )
        return subprocess.run(
            [sys.executable, "-I", "-c", program, str(MIGRATOR)],
            env=self.env,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def read_zsh(self) -> list[tuple[int, str]]:
        """Read commands and original epoch timestamps through zsh, never eval."""
        result = subprocess.run(
            [
                str(self.zsh),
                "-f",
                "-c",
                ZSH_READER,
                "history-reader",
                str(self.destination),
            ],
            env=self.env,
            capture_output=True,
            timeout=30,
            check=True,
        )
        fields = result.stdout.decode("utf-8").split("\0")
        self.assertEqual(fields.pop(), "")
        self.assertEqual(len(fields) % 2, 0)
        return [(int(fields[i]), fields[i + 1]) for i in range(0, len(fields), 2)]

    def test_native_round_trip_retains_multiline_unicode_and_duplicate_events(
        self,
    ) -> None:
        marker = self.home / "must-not-execute"
        entries = [
            (1700000001, 'printf "雪 ☃ 🐟 café е €"'),
            (1700000002, 'begin\n    echo "first"\n    echo "second"\nend'),
            (1700000003, r'printf "%s" "literal\n and \\ paths"'),
            (1700000004, "echo continuation\\\nnext"),
            (1700000005, "echo trailing slash\\"),
            (1700000006, "echo trailing slash and spaces\\  "),
            (1700000007, "\n echo leading and trailing newlines\n"),
            (1700000008, ": 123:0;looks like an extended history record"),
            (1700000009, f"touch {marker}; $(touch {marker}); `touch {marker}`"),
            (1700000010, "echo duplicate"),
            (1700000011, "echo duplicate"),
            (1700000011, "echo duplicate"),
        ]
        self.seed_fish(entries)
        with self.source.open("a") as stream:
            stream.write("  paths:\n    - /a/path with spaces\n")
        original = self.source.read_bytes()
        self.migrate()
        self.assertEqual(self.read_zsh(), entries)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(marker.exists())
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)
        self.migrate()
        self.assertEqual(self.read_zsh(), entries)

    def test_preserves_existing_bytes_and_imports_only_missing_events(self) -> None:
        original = (
            b": 1699999990:17;existing zsh command\n"
            b": 1700000001:3;echo overlap\n"
            b"plain old history\n"
            b"\\: literal colon\n"
        )
        self.destination.write_bytes(original)
        self.destination.chmod(0o644)
        self.seed_fish([(1700000001, "echo overlap"), (1700000002, "echo imported")])
        self.migrate()
        self.assertTrue(self.destination.read_bytes().startswith(original))
        entries = self.read_zsh()
        self.assertEqual(
            [command for _, command in entries],
            [
                "existing zsh command",
                "echo overlap",
                "plain old history",
                ": literal colon",
                "echo imported",
            ],
        )
        self.assertEqual(entries[-1], (1700000002, "echo imported"))
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)
        after = self.destination.read_bytes()
        self.migrate()
        self.assertEqual(self.destination.read_bytes(), after)

    def test_late_fish_writes_are_imported_even_with_older_timestamps(self) -> None:
        first = [(1700000002, "echo first")]
        self.seed_fish(first)
        self.migrate()
        later = [(1700000001, "echo late old session"), (1700000003, "echo first")]
        self.seed_fish(later, append=True)
        self.migrate()
        self.assertEqual(self.read_zsh(), first + later)
        after = self.destination.read_bytes()
        self.migrate()
        self.assertEqual(self.destination.read_bytes(), after)

    def test_missing_or_empty_source_does_not_create_or_change_zsh_history(
        self,
    ) -> None:
        self.migrate()
        self.assertFalse(self.destination.exists())
        self.source.write_bytes(b"")
        self.destination.write_bytes(b"existing\n")
        self.migrate()
        self.assertEqual(self.destination.read_bytes(), b"existing\n")

    def test_incomplete_source_fails_without_loss_then_retries(self) -> None:
        self.destination.write_bytes(b"existing\n")
        self.source.write_bytes(b"- cmd: echo partial\n  when: 1700000001")
        self.migrate(success=False)
        self.assertEqual(self.destination.read_bytes(), b"existing\n")
        with self.source.open("ab") as stream:
            stream.write(b"\n")
        self.migrate()
        self.assertEqual(self.read_zsh()[-1], (1700000001, "echo partial"))

    def test_refuses_symlink_destination_without_touching_its_target(self) -> None:
        target = self.home / "other-history"
        target.write_bytes(b"do not change\n")
        self.destination.symlink_to(target)
        self.seed_fish([(1700000001, "echo imported")])
        self.migrate(success=False)
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(target.read_bytes(), b"do not change\n")

    def test_existing_zsh_lock_is_not_removed_and_retry_succeeds(self) -> None:
        lock = self.home / ".zsh_history.LOCK"
        lock.symlink_to("/test-owned-lock")
        self.destination.write_bytes(b"existing\n")
        self.seed_fish([(1700000001, "echo imported")])
        self.migrate(success=False)
        self.assertEqual(os.readlink(lock), "/test-owned-lock")
        self.assertEqual(self.destination.read_bytes(), b"existing\n")
        lock.unlink()
        self.migrate()
        self.assertEqual(self.read_zsh()[-1], (1700000001, "echo imported"))

    def test_resume_after_interruption_before_or_after_atomic_replace(self) -> None:
        self.seed_fish([(1700000001, "echo imported")])
        original = b": 1699999999:0;existing\n"
        self.destination.write_bytes(original)
        before = self.injected_migration(
            "\ndef interrupt(*arguments):\n    os._exit(85)\nos.replace = interrupt\n"
        )
        self.assertEqual(before.returncode, 85, before.stderr.decode())
        self.assertEqual(self.destination.read_bytes(), original)
        after = self.injected_migration(
            "\nreplace = os.replace\n"
            "def interrupt(*arguments):\n"
            "    replace(*arguments)\n"
            "    os._exit(86)\n"
            "os.replace = interrupt\n"
        )
        self.assertEqual(after.returncode, 86, after.stderr.decode())
        committed = self.destination.read_bytes()
        self.migrate()
        self.assertEqual(self.destination.read_bytes(), committed)
        self.assertEqual(
            self.read_zsh(),
            [
                (1699999999, "existing"),
                (1700000001, "echo imported"),
            ],
        )

    def test_detects_in_place_zsh_write_without_overwriting_it(self) -> None:
        self.destination.write_bytes(b": 1699999999:0;existing\n")
        self.seed_fish([(1700000001, "echo imported")])
        result = self.injected_migration(
            "\nread_events = module['read_zsh_events']\n"
            "def concurrent_write(*arguments):\n"
            "    result = read_events(*arguments)\n"
            "    with open(os.path.join(os.environ['HOME'], '.zsh_history'), 'ab') as history:\n"
            "        history.write(b': 1700000002:0;concurrent writer\\n')\n"
            "    return result\n"
            "module['migrate_fish_history'].__globals__['read_zsh_events'] = concurrent_write\n"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            self.destination.read_bytes(),
            (b": 1699999999:0;existing\n: 1700000002:0;concurrent writer\n"),
        )
        self.migrate()
        self.assertEqual(
            self.read_zsh(),
            [
                (1699999999, "existing"),
                (1700000002, "concurrent writer"),
                (1700000001, "echo imported"),
            ],
        )

    def test_respects_zsh_fcntl_lock(self) -> None:
        original = b": 1699999999:0;existing\n"
        self.destination.write_bytes(original)
        self.seed_fish([(1700000001, "echo imported")])
        with self.destination.open("r+b") as stream:
            fcntl.lockf(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.migrate(success=False)
            self.assertEqual(self.destination.read_bytes(), original)
        self.migrate()
        self.assertEqual(self.read_zsh()[-1], (1700000001, "echo imported"))

    def test_unterminated_existing_history_keeps_its_last_command(self) -> None:
        for command in ["last command", "last slash\\", "slash and spaces\\  "]:
            with self.subTest(command=command):
                self.destination.write_bytes(f": 1699999999:0;{command}".encode())
                self.seed_fish([(1700000001, "echo imported")])
                self.migrate()
                self.assertEqual(
                    self.read_zsh(),
                    [
                        (1699999999, command),
                        (1700000001, "echo imported"),
                    ],
                )

    def test_unsupported_source_does_not_silently_drop_events(self) -> None:
        original = b"existing\n"
        self.destination.write_bytes(original)
        for source in [
            b"not a fish history\n",
            b"- cmd: echo missing timestamp\n",
            b"- cmd: echo future\n  when: 4102444800\n",
            b"- cmd: echo nul\0byte\n  when: 1700000001\n",
        ]:
            with self.subTest(source=source):
                self.source.write_bytes(source)
                self.migrate(success=False)
                self.assertEqual(self.destination.read_bytes(), original)
                self.assertEqual(self.source.read_bytes(), source)

    def test_shell_failures_preserve_histories_without_logging_commands(self) -> None:
        self.seed_fish([(1700000001, "echo imported")])
        self.destination.write_bytes(b"existing\n")
        directory = self.home / "bin"
        directory.mkdir()
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]
        for shell in ["fish", "zsh"]:
            with self.subTest(shell=shell):
                stub = directory / shell
                stub.write_text(
                    '#!/bin/sh\nprintf "sensitive-fixture-history" >&2\nexit 1\n'
                )
                stub.chmod(0o700)
                result = self.migrate(success=False)
                self.assertNotIn(
                    b"sensitive-fixture-history", result.stdout + result.stderr
                )
                self.assertEqual(self.destination.read_bytes(), b"existing\n")
                stub.unlink()
        self.migrate()
        self.assertEqual(self.read_zsh()[-1], (1700000001, "echo imported"))

    def test_default_data_directory_and_ignored_live_shell_settings(self) -> None:
        self.env.pop("XDG_DATA_HOME")
        self.env["fish_history"] = "unrelated-session"
        self.env["HISTFILE"] = str(self.home / "unrelated-history")
        self.source = self.home / ".local/share/fish/fish_history"
        self.source.parent.mkdir(parents=True)
        self.seed_fish([(1700000001, "echo imported")])
        self.migrate()
        self.assertEqual(self.read_zsh(), [(1700000001, "echo imported")])
        self.assertFalse((self.home / "unrelated-history").exists())

    def test_missing_source_does_not_require_shell_binaries(self) -> None:
        self.env["PATH"] = ""
        result = subprocess.run(
            [sys.executable, str(MIGRATOR)],
            env=self.env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertFalse(self.destination.exists())

    def test_does_not_reclaim_live_helper_lock(self) -> None:
        lock = self.home / ".zsh_history.LOCK"
        target = f"/fish-to-zsh/v1/pid-{os.getpid()}/host-{socket.gethostname()}"
        lock.symlink_to(target)
        self.seed_fish([(1700000001, "echo imported")])
        self.migrate(success=False)
        self.assertEqual(os.readlink(lock), target)
        self.assertFalse(self.destination.exists())

    def test_fcntl_lock_remains_held_until_atomic_publication(self) -> None:
        self.seed_fish([(1700000001, "echo imported")])
        self.destination.write_bytes(b": 1699999999:0;existing\n")
        probe = (
            "import fcntl, os, sys\n"
            "with open(os.path.join(os.environ['HOME'], '.zsh_history'), 'r+b') as history:\n"
            "    try:\n"
            "        fcntl.lockf(history.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "    except BlockingIOError:\n"
            "        sys.exit(0)\n"
            "sys.exit(99)\n"
        )
        result = self.injected_migration(
            "\nimport subprocess\nreplace = os.replace\n"
            "def check_lock(*arguments):\n"
            f"    probe = subprocess.run([sys.executable, '-I', '-c', {probe!r}], "
            "capture_output=True, timeout=10)\n"
            "    if probe.returncode != 0:\n"
            "        raise RuntimeError('test detected unlocked publication')\n"
            "    replace(*arguments)\n"
            "os.replace = check_lock\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(self.read_zsh()[-1], (1700000001, "echo imported"))


if __name__ == "__main__":
    unittest.main()
