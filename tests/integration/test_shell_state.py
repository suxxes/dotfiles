"""Check fish environment migration without reading the real account."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATOR = REPO / "dot_local/bin/executable_migrate-fish-state"


class ShellStateTest(unittest.TestCase):
    def test_preserves_exports_paths_and_existing_zsh_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shell-state-") as directory:
            home = Path(directory)
            guard = home / ".config/zsh/resolve-export-names.zsh"
            guard.parent.mkdir(parents=True)
            shutil.copyfile(REPO / "dot_config/zsh/resolve-export-names.zsh", guard)
            config = home / ".config"
            (config / "fish").mkdir(parents=True)
            (config / "fish/config.fish").write_text("")
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("XDG_", "FISH_"))
            }
            env.update(
                HOME=directory,
                XDG_CONFIG_HOME=str(config),
                XDG_DATA_HOME=str(home / ".local/share"),
            )
            subprocess.run(
                [
                    "fish",
                    "-c",
                    'set -Ux MIGRATION_SAMPLE "quote \' dollar \\$ literal"; set -U fish_user_paths "$HOME/space dir/bin"',
                ],
                env=env,
                check=True,
                capture_output=True,
            )
            secrets = config / "secrets"
            secrets.mkdir(mode=0o700)
            (secrets / "env.fish").write_text(
                'set -gx SAMPLE_TOKEN "literal \' dollar \\$ value"\n'
            )
            # No helper exists before the change. Check the missing behavior, not an import failure.
            if MIGRATOR.exists():
                subprocess.run(
                    [str(MIGRATOR)],
                    env=env,
                    check=True,
                    capture_output=True,
                    timeout=20,
                )
            self.assertTrue(
                (config / "zsh/local-env.zsh").exists(),
                "Fish exports must have a zsh input file",
            )
            self.assertTrue((secrets / "env.zsh").exists())
            result = subprocess.run(
                [
                    "zsh",
                    "-f",
                    "-c",
                    'source "$HOME/.config/zsh/local-env.zsh"; source "$HOME/.config/secrets/env.zsh"; python3 -I -c \'import os,json; print(json.dumps([os.environ["MIGRATION_SAMPLE"],os.environ["SAMPLE_TOKEN"],os.environ["PATH"].split(":")[0]]))\'',
                ],
                env=env,
                text=True,
                capture_output=True,
                check=True,
                timeout=20,
            )
            self.assertEqual(
                json.loads(result.stdout),
                [
                    "quote ' dollar $ literal",
                    "literal ' dollar $ value",
                    str(home / "space dir/bin"),
                ],
            )
            self.assertEqual((secrets / "env.zsh").stat().st_mode & 0o777, 0o600)
            (secrets / "env.zsh").write_text("export SAMPLE_TOKEN=newer\n")
            subprocess.run(
                [str(MIGRATOR)], env=env, check=True, capture_output=True, timeout=20
            )
            self.assertEqual(
                (secrets / "env.zsh").read_text(), "export SAMPLE_TOKEN=newer\n"
            )
            self.assertTrue((secrets / "env.fish").exists())

    def test_rejects_unknown_secret_format_without_replacing_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shell-state-invalid-") as directory:
            home = Path(directory)
            guard = home / ".config/zsh/resolve-export-names.zsh"
            guard.parent.mkdir(parents=True)
            shutil.copyfile(REPO / "dot_config/zsh/resolve-export-names.zsh", guard)
            secrets = home / ".config/secrets"
            secrets.mkdir(parents=True)
            source = secrets / "env.fish"
            source.write_text("unsupported command\n")
            env = {
                **os.environ,
                "HOME": directory,
                "XDG_CONFIG_HOME": str(home / ".config"),
            }
            result = subprocess.run(
                [str(MIGRATOR)], env=env, capture_output=True, timeout=20, check=False
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((secrets / "env.zsh").exists())
            self.assertEqual(source.read_text(), "unsupported command\n")

    def test_renames_credential_username_without_changing_shell_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shell-state-special-") as directory:
            home = Path(directory)
            guard = home / ".config/zsh/resolve-export-names.zsh"
            guard.parent.mkdir(parents=True)
            shutil.copyfile(REPO / "dot_config/zsh/resolve-export-names.zsh", guard)
            secrets = home / ".config/secrets"
            secrets.mkdir(parents=True)
            (secrets / "env.fish").write_text('set -gx USERNAME "migration_fixture"\n')
            env = {
                **os.environ,
                "HOME": directory,
                "XDG_CONFIG_HOME": str(home / ".config"),
            }
            result = subprocess.run(
                [str(MIGRATOR)], env=env, capture_output=True, timeout=20, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            exported = subprocess.run(
                [
                    "zsh",
                    "-dfc",
                    'source "$HOME/.config/secrets/env.zsh"; print -r -- "$CREDENTIAL_USERNAME"; [[ $USERNAME != migration_fixture ]]',
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertEqual(exported.stdout, "migration_fixture\n")

    def test_rejects_alias_collision_across_universals_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shell-state-collision-") as directory:
            home = Path(directory)
            config = home / ".config"
            guard = config / "zsh/resolve-export-names.zsh"
            guard.parent.mkdir(parents=True)
            shutil.copyfile(REPO / "dot_config/zsh/resolve-export-names.zsh", guard)
            (config / "fish").mkdir()
            (config / "fish/config.fish").write_text("")
            secrets = config / "secrets"
            secrets.mkdir()
            (secrets / "env.fish").write_text(
                'set -gx CREDENTIAL_USERNAME "second_fixture"\n'
            )
            env = {**os.environ, "HOME": directory, "XDG_CONFIG_HOME": str(config)}
            subprocess.run(
                ["fish", "-c", "set -Ux USERNAME first_fixture"],
                env=env,
                capture_output=True,
                check=True,
            )
            result = subprocess.run(
                [str(MIGRATOR)], env=env, capture_output=True, timeout=20, check=False
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((secrets / "env.zsh").exists())
            self.assertFalse((config / "zsh/local-env.zsh").exists())
            self.assertNotIn(b"first_fixture", result.stderr)
            self.assertNotIn(b"second_fixture", result.stderr)


if __name__ == "__main__":
    unittest.main()
