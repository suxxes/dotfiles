"""Exercise the rendered generator and generated exports without live credentials."""

import json
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class ShellGeneratorSandbox:
    """Run the real generator with an allowlisted PATH and disposable HOME."""

    home: Path
    source: Path
    env: dict[str, str]
    chezmoi: str
    fixture: Path
    calls: Path
    output: Path

    def run(
        self,
        items: dict[str, list[dict[str, object]]],
        *,
        profile: str = "personal",
        failure: str = "",
    ) -> subprocess.CompletedProcess[str]:
        self.fixture.write_text(json.dumps({"items": items, "failure": failure}))
        config = self.home / "chezmoi.toml"
        config.write_text(f'[data]\nosType = "darwin"\nprofile = "{profile}"\n')
        rendered = subprocess.run(
            [
                self.chezmoi,
                "--config",
                str(config),
                "--source",
                str(self.source),
                "--destination",
                str(self.home),
                "--cache",
                str(self.home / "cache"),
                "--persistent-state",
                str(self.home / "state.boltdb"),
                "execute-template",
                "--left-delimiter",
                "# {{",
                "--right-delimiter",
                "}}",
            ],
            input=(
                Path(__file__).resolve().parents[2]
                / "run_after_generate-secrets.sh.tmpl"
            ).read_text(),
            cwd=self.home,
            env=self.env,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        return subprocess.run(
            ["/bin/bash"],
            input=rendered.stdout,
            check=False,
            cwd=self.home,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=10,
        )


@pytest.fixture
def shell_generator(tmp_path: Path) -> ShellGeneratorSandbox:
    home = tmp_path / "shell-secrets-home"
    home.mkdir()
    bin_dir = home / "bin"
    bin_dir.mkdir()
    # No inherited PATH, op token, SSH agent, shell startup, or chezmoi config.
    for name in (
        "jq",
        "zsh",
        "date",
        "mkdir",
        "chmod",
        "sed",
        "tr",
        "mktemp",
        "mv",
        "rm",
    ):
        executable = shutil.which(name)
        assert executable is not None, f"Missing integration prerequisite: {name}"
        (bin_dir / name).symlink_to(executable)
    chezmoi = shutil.which("chezmoi")
    assert chezmoi is not None, "Missing integration prerequisite: chezmoi"
    hostname = bin_dir / "hostname"
    hostname.write_text('#!/bin/sh\nprintf "%s\\n" shell-secrets-host\n')
    hostname.chmod(0o700)
    fixture = home / "catalog.json"
    calls = home / "op-calls.jsonl"
    op = bin_dir / "op"
    op.write_text(
        f"#!{sys.executable} -I\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        'with Path(os.environ["FAKE_OP_CALLS"]).open("a") as log:\n'
        '    log.write(json.dumps(args) + "\\n")\n'
        'catalog = json.loads(Path(os.environ["FAKE_OP_CATALOG"]).read_text())\n'
        'if args[:2] == ["account", "list"]:\n'
        '    print(json.dumps([{"url": "shell-secrets.invalid"}]))\n'
        'elif args[:2] == ["item", "list"]:\n'
        '    vault = args[args.index("--vault") + 1]\n'
        '    print(json.dumps(catalog["items"].get(vault, [])))\n'
        'elif args[:2] == ["item", "get"]:\n'
        "    sys.stdin.read()  # A CLI must not consume the enclosing item loop.\n"
        '    vault = args[args.index("--vault") + 1]\n'
        '    item = next(item for item in catalog["items"][vault]\n'
        '                if item["title"] == args[2])\n'
        '    if args[2] == "Broken" and catalog["failure"] == "json":\n'
        '        print("{")\n'
        "    else:\n"
        '        print(json.dumps({"fields": item["fields"]}))\n'
        '    if args[2] == "Broken" and catalog["failure"] == "op":\n'
        "        sys.exit(7)\n"
        'elif args[:1] == ["read"]:\n'
        "    sys.exit(1)  # Never supply an SSH key.\n"
        "else:\n"
        '    sys.exit("Unexpected fake op invocation")\n'
    )
    op.chmod(0o700)
    source = home / "source"
    # Only inert hash inputs: rendering never traverses the real dotfiles source.
    template = source / "dot_config/zsh/secrets.zsh.tmpl"
    template.parent.mkdir(parents=True)
    template.write_text("# Isolated shell loader hash fixture\n")
    guard = home / ".config/zsh/resolve-export-names.zsh"
    guard.parent.mkdir(parents=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[2] / "dot_config/zsh/resolve-export-names.zsh",
        guard,
    )
    env = {
        "HOME": str(home),
        "ZDOTDIR": str(home),
        "PATH": str(bin_dir),
        "LC_ALL": "C",
        "FAKE_OP_CATALOG": str(fixture),
        "FAKE_OP_CALLS": str(calls),
    }
    return ShellGeneratorSandbox(
        home,
        source,
        env,
        chezmoi,
        fixture,
        calls,
        home / ".config" / "secrets" / "env.zsh",
    )


def shell_secret_item(
    title: str, fields: dict[str, str | None], *, vault: str = "Secrets"
) -> dict[str, object]:
    """Build synthetic 1Password fields, including its notes exclusion contract."""
    return {
        "id": f"{vault}:{title}",
        "title": title,
        "vault": {"id": vault},
        "fields": [
            {
                "id": "notesPlain" if label == "notes" else label,
                "label": label,
                "value": value,
            }
            for label, value in fields.items()
        ],
    }


def test_zsh_exports_preserve_values_without_execution(
    shell_generator: ShellGeneratorSandbox,
) -> None:
    values = {
        "PLAIN_TOKEN": "synthetic-token=with=equals",
        "QUOTED_TOKEN": "synthetic 'single' \"double\" \\ backslash",
        "SHELL_TOKEN": "synthetic $HOME $(printf injected > command-injected) `printf injected > backtick-injected` ; #",
        "MULTILINE_TOKEN": "synthetic first\nexport INJECTED=value\nlast\n\n",
        "WHITESPACE_TOKEN": " \tsynthetic spaced\r\nvalue \t ",
        "LEADING_TOKEN": "-n synthetic \\n literal",
        "HOME": str(shell_generator.home / "exported-home"),
        "PATH": "/synthetic/bin:/synthetic/other bin",
        "USER": "synthetic-service-user",
    }
    result = shell_generator.run(
        {
            "Secrets": [
                shell_secret_item(
                    "First",
                    dict(
                        values,
                        username="synthetic-user '\" $HOME `literal`\nlast\n",
                        notes="synthetic-notes",
                        EMPTY="",
                        NULL=None,
                    ),
                ),
                shell_secret_item(
                    "Second\nexport TITLE_INJECTED=yes",
                    {"second-token": "synthetic-second"},
                ),
            ]
        }
    )
    assert result.returncode == 0, result.stderr
    assert shell_generator.output.is_file(), result.stdout
    assert stat.S_IMODE(shell_generator.output.stat().st_mode) == 0o600
    assert not shell_generator.output.with_name("env.fish").exists()
    expected = dict(
        values,
        SECOND_TOKEN="synthetic-second",
        CREDENTIAL_USERNAME="synthetic-user '\" $HOME `literal`\nlast\n",
    )
    for value in (*expected.values(), "synthetic-notes"):
        assert value not in result.stdout + result.stderr
    omitted = ["INJECTED", "TITLE_INJECTED", "EMPTY", "NULL", "NOTES", "USERNAME"]
    sourced = subprocess.run(
        [
            "/bin/zsh",
            "-f",
            "-c",
            (
                "zmodload zsh/parameter; before_username=$USERNAME; "
                'before_attributes=${parameters[USERNAME]}; source "$1" || exit; '
                '[[ $USERNAME == "$before_username" && '
                '${parameters[USERNAME]} == "$before_attributes" ]] || exit 1; '
                'shift; exec "$@"'
            ),
            "shell-secret-test",
            str(shell_generator.output),
            sys.executable,
            "-I",
            "-c",
            (
                "import json, os, sys; "
                "print(json.dumps({key: os.environ.get(key) for key in sys.argv[1:]}))"
            ),
            *expected,
            *omitted,
        ],
        cwd=shell_generator.home,
        env=shell_generator.env,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert json.loads(sourced.stdout) == dict(expected, **dict.fromkeys(omitted))
    assert not (shell_generator.home / "command-injected").exists()
    assert not (shell_generator.home / "backtick-injected").exists()
    assert not (shell_generator.home / ".ssh" / "id_ed25519").exists()


@pytest.mark.parametrize(
    ("profile", "vaults"),
    [
        ("work", ["Secrets", "Secrets: Work"]),
        ("personal", ["Secrets", "Secrets: Personal"]),
        ("server", ["Secrets"]),
    ],
)
def test_shell_export_preserves_vault_and_item_policy(
    shell_generator: ShellGeneratorSandbox, profile: str, vaults: list[str]
) -> None:
    base_items = [
        shell_secret_item("Common", {"COMMON": "synthetic-common"}),
        shell_secret_item(
            "Service Account Token", {"FORBIDDEN": "synthetic-service-token"}
        ),
        shell_secret_item("LXC SSH Key", {"FORBIDDEN": "synthetic-ssh-key"}),
        shell_secret_item("AWS SSO: test", {}),
        shell_secret_item("AWS Key: test", {}),
        shell_secret_item("LXC: other-host", {"FORBIDDEN": "synthetic-other-host"}),
        shell_secret_item("LXC: shell-secrets-host", {"LOCAL": "synthetic-local"}),
    ]
    items = {"Secrets": base_items}
    for vault in ("Secrets: Work", "Secrets: Personal"):
        items[vault] = [shell_secret_item("Profile", {"PROFILE": vault}, vault=vault)]
    result = shell_generator.run(items, profile=profile)
    assert result.returncode == 0, result.stderr
    sourced = subprocess.run(
        [
            "/bin/zsh",
            "-f",
            "-c",
            (
                'source "$1" || exit; printf "%s\\0" "$COMMON" "$LOCAL" '
                '"${PROFILE-unset}" "${FORBIDDEN-unset}"'
            ),
            "shell-secret-test",
            str(shell_generator.output),
        ],
        cwd=shell_generator.home,
        env=shell_generator.env,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert sourced.stdout.split(b"\0") == [
        b"synthetic-common",
        b"synthetic-local",
        vaults[1].encode() if len(vaults) > 1 else b"unset",
        b"unset",
        b"",
    ]
    calls = [
        json.loads(line) for line in shell_generator.calls.read_text().splitlines()
    ]
    assert [
        args[args.index("--vault") + 1]
        for args in calls
        if args[:2] == ["item", "list"]
    ] == vaults


@pytest.mark.parametrize(
    ("failure", "label", "value"),
    [
        ("op", "VALID", "synthetic-broken"),
        ("json", "VALID", "synthetic-broken"),
        ("", "123 invalid", "synthetic-broken"),
        ("", "!!!", "synthetic-broken"),
        ("", "", "synthetic-broken"),
        ("", "λ", "synthetic-broken"),
        ("", "VALID", "synthetic\0broken"),
    ],
)
def test_failed_export_preserves_existing_private_file(
    shell_generator: ShellGeneratorSandbox, failure: str, label: str, value: str
) -> None:
    output = shell_generator.output
    output.parent.mkdir(parents=True)
    original = b"export EXISTING='synthetic-original'\n"
    output.write_bytes(original)
    output.chmod(0o600)
    result = shell_generator.run(
        {
            "Secrets": [
                shell_secret_item("A good item", {"GOOD": "synthetic-good"}),
                shell_secret_item(
                    "Broken", {"BEFORE_ERROR": "synthetic-partial", label: value}
                ),
            ]
        },
        failure=failure,
    )
    assert result.returncode != 0
    assert output.read_bytes() == original
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(output.parent.iterdir()) == [output]
    for secret in ("synthetic-good", "synthetic-partial", value):
        assert secret not in result.stdout + result.stderr


def test_empty_vaults_leave_existing_exports_unchanged(
    shell_generator: ShellGeneratorSandbox,
) -> None:
    shell_generator.output.parent.mkdir(parents=True)
    original = b"export EXISTING='synthetic-original'\n"
    shell_generator.output.write_bytes(original)
    result = shell_generator.run({})
    assert result.returncode == 0
    assert shell_generator.output.read_bytes() == original


@pytest.mark.parametrize("label", ["uid", "EUID", "GID", "EGID", "PPID", "SHLVL"])
def test_zsh_parameter_conflicts_preserve_existing_exports(
    shell_generator: ShellGeneratorSandbox, label: str
) -> None:
    output = shell_generator.output
    output.parent.mkdir(parents=True)
    original = b"export EXISTING='synthetic-original'\n"
    output.write_bytes(original)
    output.chmod(0o600)
    result = shell_generator.run(
        {
            "Secrets": [
                shell_secret_item("Identity", {label: "synthetic-conflicting-value"})
            ]
        }
    )
    assert result.returncode != 0
    assert (
        f"Shell secret export conflicts with zsh parameter: {label.upper()}"
        in result.stderr
    )
    assert output.read_bytes() == original
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(output.parent.iterdir()) == [output]
    assert "synthetic-conflicting-value" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("name", "failure"),
    [
        ("status", "conflicts with zsh parameter"),
        ("path", "conflicts with zsh parameter"),
        ("not-valid", "invalid variable name"),
    ],
)
def test_shared_export_resolver_validates_name_arguments(
    shell_generator: ShellGeneratorSandbox, name: str, failure: str
) -> None:
    result = subprocess.run(
        [
            "/bin/zsh",
            "-f",
            str(shell_generator.home / ".config/zsh/resolve-export-names.zsh"),
            "SYNTHETIC_TOKEN",
            name,
        ],
        cwd=shell_generator.home,
        env=shell_generator.env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert result.stderr == f"Shell secret export {failure}: {name}\n"
    assert result.stdout == ""


@pytest.mark.parametrize(
    "names",
    [
        ["USERNAME", "CREDENTIAL_USERNAME"],
        ["CREDENTIAL_USERNAME", "USERNAME"],
    ],
)
def test_ambiguous_username_names_preserve_existing_exports(
    shell_generator: ShellGeneratorSandbox, names: list[str]
) -> None:
    output = shell_generator.output
    output.parent.mkdir(parents=True)
    original = b"export EXISTING='synthetic-original'\n"
    output.write_bytes(original)
    output.chmod(0o600)
    result = shell_generator.run(
        {
            "Secrets": [
                shell_secret_item(
                    "Identity", dict.fromkeys(names, "synthetic-ambiguous")
                )
            ]
        }
    )
    assert result.returncode != 0
    assert (
        result.stderr
        == "Shell secret export ambiguous names: USERNAME CREDENTIAL_USERNAME\n"
    )
    assert output.read_bytes() == original
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(output.parent.iterdir()) == [output]
    assert "synthetic-ambiguous" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (
            ["SYNTHETIC_TOKEN", "USERNAME", "HOME", "PATH"],
            "SYNTHETIC_TOKEN\nCREDENTIAL_USERNAME\nHOME\nPATH\n",
        ),
        (["CREDENTIAL_USERNAME"], "CREDENTIAL_USERNAME\n"),
        ([], ""),
    ],
)
def test_export_name_resolver_returns_names_in_input_order(
    shell_generator: ShellGeneratorSandbox, names: list[str], expected: str
) -> None:
    result = subprocess.run(
        [
            "/bin/zsh",
            "-df",
            str(shell_generator.home / ".config/zsh/resolve-export-names.zsh"),
            *names,
        ],
        cwd=shell_generator.home,
        env=shell_generator.env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected
    assert result.stderr == ""


@pytest.mark.parametrize("second_vault", ["Secrets", "Secrets: Personal"])
def test_username_alias_collision_across_items_preserves_existing_exports(
    shell_generator: ShellGeneratorSandbox, second_vault: str
) -> None:
    output = shell_generator.output
    output.parent.mkdir(parents=True)
    original = b"export EXISTING='synthetic-original'\n"
    output.write_bytes(original)
    output.chmod(0o600)
    items = {
        "Secrets": [
            shell_secret_item("First identity", {"USERNAME": "synthetic-first-user"})
        ]
    }
    items.setdefault(second_vault, []).append(
        shell_secret_item(
            "Second identity",
            {"CREDENTIAL_USERNAME": "synthetic-second-user"},
            vault=second_vault,
        )
    )
    result = shell_generator.run(items)
    assert result.returncode != 0
    assert (
        result.stderr
        == "Shell secret export ambiguous names: USERNAME CREDENTIAL_USERNAME\n"
    )
    assert output.read_bytes() == original
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(output.parent.iterdir()) == [output]
    assert "synthetic-first-user" not in result.stdout + result.stderr
    assert "synthetic-second-user" not in result.stdout + result.stderr


def test_identical_original_keys_keep_last_selected_value(
    shell_generator: ShellGeneratorSandbox,
) -> None:
    result = shell_generator.run(
        {
            "Secrets": [
                shell_secret_item(
                    "A first",
                    {"USERNAME": "synthetic-first", "TOKEN": "synthetic-first"},
                ),
                shell_secret_item(
                    "Z last", {"USERNAME": "synthetic-last", "TOKEN": "synthetic-last"}
                ),
            ]
        }
    )
    assert result.returncode == 0, result.stderr
    sourced = subprocess.run(
        [
            "/bin/zsh",
            "-df",
            "-c",
            'source "$1" || exit; printf "%s\\0" "$CREDENTIAL_USERNAME" "$TOKEN"',
            "shell-secret-test",
            str(shell_generator.output),
        ],
        cwd=shell_generator.home,
        env=shell_generator.env,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert sourced.stdout == b"synthetic-last\0synthetic-last\0"
