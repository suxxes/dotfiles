"""Apply the rendered crust scripts against spy tools in disposable homes."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CRUST_TOOL = "github:suxxes/crust"
FAKE_TOKEN = "crust-test-'$(false)'-token"


def write_spy_tool(bin_dir: Path, name: str, behavior: str = "") -> None:
    """Record calls without logging credential values."""
    spy = bin_dir / name
    spy.write_text(
        f"#!{sys.executable} -I\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "home = Path(os.environ['HOME'])\n"
        "with (home / 'calls.jsonl').open('a') as log:\n"
        f"    log.write(json.dumps({{'argv': [{name!r}, *args],"
        " 'disabled': os.environ.get('MISE_DISABLE_TOOLS'),"
        " 'no_autoremove': os.environ.get('HOMEBREW_NO_AUTOREMOVE'),"
        f" 'token': os.environ.get('GITHUB_TOKEN') == {FAKE_TOKEN!r},"
        " 'other_secret': 'CRUST_TEST_UNRELATED_SECRET' in os.environ}) + '\\n')\n"
        + behavior
    )
    spy.chmod(0o700)


@pytest.fixture
def crust_home(tmp_path: Path) -> Path:
    home = tmp_path / "crust-install-home"
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True)
    write_spy_tool(bin_dir, "brew")
    write_spy_tool(
        bin_dir,
        "mise",
        "replacement = home / 'mise-install' / 'bin' / 'crust'\n"
        "if args[:1] == ['upgrade']:\n"
        "    if not os.environ.get('GITHUB_TOKEN'):\n"
        "        sys.exit('Missing fake mise credential')\n"
        "    if os.environ.get('CRUST_TEST_INSTALL') == 'fail':\n"
        "        sys.exit('Fake mise download failed')\n"
        "    if os.environ.get('CRUST_TEST_INSTALL') == 'success':\n"
        "        replacement.parent.mkdir(parents=True, exist_ok=True)\n"
        "        replacement.write_text('#!/bin/sh\\nexit 0\\n')\n"
        "        replacement.chmod(0o700)\n"
        "elif args[:1] == ['which']:\n"
        "    if not replacement.exists():\n"
        "        sys.exit(1)\n"
        f"    print({CRUST_TOOL!r} if '--plugin' in args else replacement)\n",
    )
    write_spy_tool(
        bin_dir,
        "op",
        "catalog = home / 'fake-op-field-list.json'\n"
        "if args[:2] == ['account', 'list'] and catalog.exists():\n"
        "    print('[]')\n"
        "elif args[:2] == ['item', 'list'] and args[3] == 'Secrets':\n"
        "    print('[{\"id\":\"fixture\",\"title\":\"Fixture\",\"vault\":{\"id\":\"Secrets\"}}]')\n"
        "elif args[:2] == ['item', 'list']:\n"
        "    print('[]')\n"
        "elif args[:2] == ['item', 'get']:\n"
        "    print(catalog.read_text())\n"
        "else:\n"
        "    sys.exit(1)\n",
    )
    return home


def apply_crust_scripts(
    home: Path,
    os_type: str,
    *,
    token: str = "",
    install: str = "",
    hostname: str = "crust-fixture",
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
    chezmoi = shutil.which("chezmoi")
    assert chezmoi is not None, "Missing integration prerequisite: chezmoi"
    source = home / "source"
    paths = [
        Path("run_after_generate-secrets.sh.tmpl"),
        Path("run_after_install-crust.sh.tmpl"),
        Path("dot_config/zsh/secrets.zsh.tmpl"),
        Path("dot_config/zsh/resolve-export-names.zsh"),
    ]
    paths.extend(
        p.relative_to(REPO) for p in REPO.glob("run_*_remove-pre-mise-crust.sh.tmpl")
    )
    # The Linux package script manages system packages. Exercise macOS with fake brew.
    if os_type == "darwin":
        paths.extend(
            Path(name)
            for name in (
                "run_onchange_install-packages.sh.tmpl",
                "dot_Brewfile.tmpl",
                "dot_config/mise/config.toml.tmpl",
            )
        )
    for path in paths:
        (source / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / path, source / path)
    config = home / "chezmoi.toml"
    config.write_text(f'[data]\nosType = "{os_type}"\nprofile = "personal"\n')
    calls = home / "calls.jsonl"
    calls.unlink(missing_ok=True)
    jq = shutil.which("jq")
    assert jq is not None, "Missing integration prerequisite: jq"
    if not (home / "bin/jq").exists():
        (home / "bin/jq").symlink_to(jq)
    env = {
        "HOME": str(home),
        "PATH": f"{home / 'bin'}:/usr/bin:/bin",
        "LC_ALL": "C",
        "CRUST_TEST_INSTALL": install,
    }
    if token:
        env["GITHUB_TOKEN"] = token
    result = subprocess.run(
        [
            chezmoi,
            "--config",
            str(config),
            "--source",
            str(source),
            "--destination",
            str(home),
            "--cache",
            str(home / "chezmoi-cache"),
            "--persistent-state",
            str(home / "state.db"),
            "--override-data",
            json.dumps({"chezmoi": {"hostname": hostname}}),
            "apply",
            "--force",
        ],
        env=env,
        cwd=home,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    recorded = (
        [json.loads(line) for line in calls.read_text().splitlines()]
        if calls.exists()
        else []
    )
    return result, recorded


@pytest.mark.parametrize("os_type", ["darwin", "linux"])
def test_first_apply_installs_crust_with_newly_generated_token(
    crust_home: Path, os_type: str
) -> None:
    unrelated_secret = "fixture-unrelated-credential"
    fields = {"GITHUB_TOKEN": FAKE_TOKEN, "CRUST_TEST_UNRELATED_SECRET": unrelated_secret}
    (crust_home / "fake-op-field-list.json").write_text(
        json.dumps({
            "fields": [
                {"label": label, "value": value} for label, value in fields.items()
            ],
        })
    )
    if os_type == "linux":
        # Stand in for mise installed by the earlier package script, outside the caller's PATH.
        local_bin = crust_home / ".local/bin"
        local_bin.mkdir(parents=True)
        (crust_home / "bin/mise").rename(local_bin / "mise")

    result, calls = apply_crust_scripts(crust_home, os_type, install="success")

    assert result.returncode == 0, result.stderr
    assert (crust_home / ".config/secrets/env.zsh").is_file()
    assert (crust_home / "mise-install/bin/crust").is_file(), result.stdout
    argv = [call["argv"] for call in calls]
    if os_type == "darwin":
        assert argv[0] == [
            "brew", "bundle", "install", f"--file={crust_home / '.Brewfile'}",
        ]
        assert argv[1] == ["mise", "install", "--yes"]
        assert calls[1]["disabled"] == CRUST_TOOL
    assert [call["argv"] for call in calls if call["token"]] == [
        ["mise", "upgrade", "--yes", CRUST_TOOL],
    ]
    assert not any(call["other_secret"] for call in calls)
    transcript = result.stdout + result.stderr + json.dumps(argv)
    assert all(value not in transcript for value in fields.values())


def test_apply_uses_inherited_token_for_crust(crust_home: Path) -> None:
    result, calls = apply_crust_scripts(
        crust_home, "darwin", token=FAKE_TOKEN, install="success"
    )
    assert result.returncode == 0, result.stderr
    mise_install = [c for c in calls if c["argv"] == ["mise", "install", "--yes"]]
    assert [c["disabled"] for c in mise_install] == [None]
    assert (crust_home / "mise-install/bin/crust").is_file()


def seed_legacy_crust(home: Path) -> tuple[Path, Path]:
    old_binary = home / ".local/bin/crust"
    old_binary.parent.mkdir(parents=True)
    old_binary.write_text("#!/bin/sh\nexit 0\n")
    old_binary.chmod(0o700)
    stamp = home / ".local/share/crust/release-tag"
    stamp.parent.mkdir(parents=True)
    stamp.write_text("5.0.1\n")
    return old_binary, stamp


@pytest.mark.parametrize("os_type", ["linux", "darwin"])
def test_apply_preserves_legacy_crust_without_token_then_retries_cleanup(
    crust_home: Path, os_type: str
) -> None:
    old_binary, stamp = seed_legacy_crust(crust_home)
    result, calls = apply_crust_scripts(crust_home, os_type)
    assert result.returncode == 0, result.stderr
    assert "GITHUB_TOKEN is not set" in result.stdout
    assert old_binary.is_file()
    assert stamp.is_file()
    assert not any(
        c["argv"][:2] in (["mise", "upgrade"], ["brew", "uninstall"]) for c in calls
    )

    result, calls = apply_crust_scripts(
        crust_home, os_type, token=FAKE_TOKEN, install="success"
    )
    assert result.returncode == 0, result.stderr
    assert (crust_home / "mise-install/bin/crust").is_file()
    assert not old_binary.exists()
    assert not stamp.parent.exists()
    brew_calls = [c for c in calls if c["argv"][0] == "brew"]
    if os_type == "darwin":
        assert [(c["argv"], c["no_autoremove"]) for c in brew_calls] == [
            (["brew", "list", "--formula", "suxxes/tap/crust"], None),
            (["brew", "uninstall", "--force", "suxxes/tap/crust"], "1"),
        ]
    else:
        assert brew_calls == []


def test_failed_upgrade_preserves_legacy_crust(crust_home: Path) -> None:
    old_binary, stamp = seed_legacy_crust(crust_home)
    result, _ = apply_crust_scripts(crust_home, "linux", token=FAKE_TOKEN, install="fail")
    assert result.returncode != 0
    assert "Fake mise download failed" in result.stderr
    assert old_binary.is_file()
    assert stamp.is_file()


@pytest.mark.parametrize("replacement", ["missing", "non-executable"])
def test_upgrade_without_usable_binary_preserves_legacy_crust(
    crust_home: Path, replacement: str
) -> None:
    old_binary, stamp = seed_legacy_crust(crust_home)
    if replacement == "non-executable":
        path = crust_home / "mise-install/bin/crust"
        path.parent.mkdir(parents=True)
        path.write_text("not an executable file")
    result, _ = apply_crust_scripts(crust_home, "linux", token=FAKE_TOKEN)
    assert result.returncode == 0, result.stderr
    assert old_binary.is_file()
    assert stamp.is_file()


def test_excluded_host_leaves_legacy_crust_untouched(crust_home: Path) -> None:
    old_binary, stamp = seed_legacy_crust(crust_home)
    result, calls = apply_crust_scripts(
        crust_home, "darwin", token=FAKE_TOKEN, hostname="usakura"
    )
    assert result.returncode == 0, result.stderr
    assert old_binary.is_file()
    assert stamp.is_file()
    assert {c["argv"][0] for c in calls} == {"op"}
