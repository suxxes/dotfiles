"""Run the rendered crust install scripts against spy tools in disposable homes."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CRUST_TOOL = "github:suxxes/crust"


def write_spy_tool(bin_dir: Path, name: str, output: str = "") -> None:
    """Record argv and the env switches under test for each call, then print output."""
    spy = bin_dir / name
    spy.write_text(
        f"#!{sys.executable} -I\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "with Path(os.environ['CRUST_TEST_CALLS']).open('a') as log:\n"
        f"    log.write(json.dumps({{'argv': [{name!r}, *sys.argv[1:]],"
        " 'disabled': os.environ.get('MISE_DISABLE_TOOLS'),"
        " 'no_autoremove': os.environ.get('HOMEBREW_NO_AUTOREMOVE')}) + '\\n')\n"
        f"print({output!r}, end='')\n"
    )
    spy.chmod(0o700)


def run_rendered_script(
    home: Path, script: str, os_type: str, extra_env: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
    chezmoi = shutil.which("chezmoi")
    assert chezmoi is not None, "Missing integration prerequisite: chezmoi"
    config = home / "chezmoi.toml"
    config.write_text(f'[data]\nosType = "{os_type}"\nprofile = "personal"\n')
    rendered = subprocess.run(
        [
            chezmoi,
            "--config",
            str(config),
            "--source",
            str(REPO),
            "--destination",
            str(home),
            "--cache",
            str(home / "chezmoi-cache"),
            "--persistent-state",
            str(home / "state.db"),
            "execute-template",
        ],
        input=(REPO / script).read_text(),
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        cwd=home,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout
    calls = home / "calls.jsonl"
    result = subprocess.run(
        ["/bin/bash"],
        input=rendered,
        env={
            "HOME": str(home),
            "PATH": f"{home / 'bin'}:/usr/bin:/bin",
            "LC_ALL": "C",
            "CRUST_TEST_CALLS": str(calls),
            **extra_env,
        },
        cwd=home,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    recorded = (
        [json.loads(line) for line in calls.read_text().splitlines()]
        if calls.exists()
        else []
    )
    return result, recorded


@pytest.fixture
def crust_home(tmp_path: Path) -> Path:
    home = tmp_path / "crust-install-home"
    (home / "bin").mkdir(parents=True)
    write_spy_tool(home / "bin", "mise")
    write_spy_tool(home / "bin", "curl")
    return home


@pytest.mark.parametrize("os_type", ["linux", "darwin"])
def test_crust_upgrades_through_mise_with_token(crust_home: Path, os_type: str) -> None:
    result, calls = run_rendered_script(
        crust_home,
        "run_after_install-crust.sh.tmpl",
        os_type,
        {"GITHUB_TOKEN": "crust-test-token"},
    )
    assert result.returncode == 0, result.stderr
    assert [call["argv"] for call in calls] == [
        ["mise", "activate", "bash", "--shims"],
        ["mise", "upgrade", "--yes", CRUST_TOOL],
    ]


def test_crust_upgrade_skips_without_token(crust_home: Path) -> None:
    result, calls = run_rendered_script(
        crust_home, "run_after_install-crust.sh.tmpl", "linux", {}
    )
    assert result.returncode == 0, result.stderr
    assert "GITHUB_TOKEN is not set" in result.stdout
    assert calls == []


@pytest.mark.parametrize(
    ("token_env", "expected_disabled"),
    [({}, CRUST_TOOL), ({"GITHUB_TOKEN": "crust-test-token"}, None)],
)
def test_package_install_skips_private_crust_only_without_token(
    crust_home: Path, token_env: dict[str, str], expected_disabled: str | None
) -> None:
    write_spy_tool(crust_home / "bin", "brew")
    result, calls = run_rendered_script(
        crust_home, "run_onchange_install-packages.sh.tmpl", "darwin", token_env
    )
    assert result.returncode == 0, result.stderr
    mise_install = [c for c in calls if c["argv"] == ["mise", "install", "--yes"]]
    assert [c["disabled"] for c in mise_install] == [expected_disabled]


@pytest.mark.parametrize("os_type", ["linux", "darwin"])
def test_cleanup_removes_pre_mise_crust_copies(crust_home: Path, os_type: str) -> None:
    write_spy_tool(crust_home / "bin", "brew")
    old_binary = crust_home / ".local/bin/crust"
    old_binary.parent.mkdir(parents=True)
    old_binary.write_text("old crust build")
    stamp = crust_home / ".local/share/crust/release-tag"
    stamp.parent.mkdir(parents=True)
    stamp.write_text("5.0.1\n")
    result, calls = run_rendered_script(
        crust_home, "run_once_after_remove-pre-mise-crust.sh.tmpl", os_type, {}
    )
    assert result.returncode == 0, result.stderr
    assert not old_binary.exists()
    assert not stamp.parent.exists()
    brew_calls = [c for c in calls if c["argv"][0] == "brew"]
    if os_type == "darwin":
        # Every installed version goes, and autoremove must not take unrelated formulae.
        assert [(c["argv"], c["no_autoremove"]) for c in brew_calls] == [
            (["brew", "list", "--formula", "suxxes/tap/crust"], None),
            (["brew", "uninstall", "--force", "suxxes/tap/crust"], "1"),
        ]
    else:
        assert brew_calls == []
