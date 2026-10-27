"""Exercise managed zsh startup in disposable homes without live credentials."""

import errno
import json
import os
import pty
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ZSH = shutil.which("zsh")


@dataclass
class ZshStartupSandbox:
    """Render only shell-owned files and run zsh with an allowlisted environment."""

    home: Path
    env: dict[str, str]
    calls: Path

    def run(
        self, command: str, *, interactive: bool = False, login: bool = False
    ) -> subprocess.CompletedProcess[str]:
        args = [str(ZSH)]
        if interactive:
            args.append("-i")
        if login:
            args.append("-l")
        if interactive:
            master, slave = pty.openpty()
            with os.fdopen(master, "rb"), os.fdopen(slave, "rb") as terminal:
                return subprocess.run(
                    args + ["-c", command],
                    cwd=self.home,
                    check=False,
                    env=self.env,
                    stdin=terminal,
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
        return subprocess.run(
            args + ["-c", command],
            cwd=self.home,
            check=False,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=15,
        )

    def type_in_terminal(self, keys: bytes) -> str:
        """Drive a real line editor; ten-second idle exit bounds the child lifetime."""
        config = self.home / ".zshrc"
        hook = (
            "\nautoload -Uz add-zle-hook-widget\n"
            "function zsh-test-line-ready() { print -rn -- $'\\e]777;zsh-test-ready\\a'; }\n"
            "add-zle-hook-widget line-init zsh-test-line-ready\n"
        )
        config.write_text(
            config.read_text().removesuffix("return 0\n") + hook + "return 0\n"
        )
        terminal, slave = pty.openpty()
        with os.fdopen(slave, "rb") as child_terminal:
            process = subprocess.Popen(
                [str(ZSH), "-i"],
                stdin=child_terminal,
                stdout=child_terminal,
                stderr=child_terminal,
                cwd=self.home,
                env={**self.env, "TMOUT": "10"},
                start_new_session=True,
            )
        pid = process.pid
        output = bytearray()
        deadline = time.monotonic() + 15
        try:
            for payload, marker in (
                (keys, b"\x1b]777;zsh-test-ready\x07"),
                (b"exit\n", b"\r\n__ZSH_DONE__\r\n"),
            ):
                while marker not in output:
                    remaining = deadline - time.monotonic()
                    assert remaining > 0, repr(bytes(output))
                    ready, _, _ = select.select([terminal], [], [], remaining)
                    assert ready, repr(bytes(output))
                    try:
                        block = os.read(terminal, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        raise AssertionError(repr(bytes(output))) from error
                    assert block, repr(bytes(output))
                    output.extend(block)
                os.write(terminal, payload)
            return output.decode(errors="replace")
        finally:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            os.close(terminal)

    def spy(self, name: str, status: int = 0, output: str = "") -> None:
        executable = self.home / ".local/bin" / name
        executable.write_text(
            f"#!{sys.executable} -I\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['ZSH_TEST_CALLS']).open('a') as log:\n"
            f"    log.write(json.dumps([{name!r}, *sys.argv[1:]]) + '\\n')\n"
            f"print({output!r}, end='')\n"
            f"sys.exit({status})\n"
        )
        executable.chmod(0o700)

    def recorded_calls(self) -> list[list[str]]:
        return (
            [json.loads(line) for line in self.calls.read_text().splitlines()]
            if self.calls.exists()
            else []
        )


@pytest.fixture
def zsh_startup(tmp_path: Path) -> ZshStartupSandbox:
    assert ZSH is not None, "Missing integration prerequisite: zsh"
    home = tmp_path / "zsh-startup-home"
    home.mkdir(mode=0o700)
    (home / "bin").mkdir()
    (home / ".local/bin").mkdir(parents=True)
    for tool in ("mise", "starship"):
        installed_tool = shutil.which(tool)
        assert installed_tool is not None, f"Missing integration prerequisite: {tool}"
        (home / "bin" / tool).symlink_to(installed_tool)
    config = home / "chezmoi.toml"
    os_type = "darwin" if sys.platform == "darwin" else "linux"
    config.write_text(f'[data]\nosType = "{os_type}"\nprofile = "personal"\n')
    chezmoi = shutil.which("chezmoi")
    assert chezmoi is not None, "Missing integration prerequisite: chezmoi"
    env = {
        "HOME": str(home),
        "ZDOTDIR": str(home),
        "PATH": f"{home}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "TERM": "xterm-256color",
        "LC_ALL": "C",
        "ZSH_TEST_CALLS": str(home / "calls.jsonl"),
    }
    sources = [
        (REPO / name, home / ("." + name.removeprefix("dot_")))
        for name in ("dot_zshenv", "dot_zprofile", "dot_zshrc")
    ]
    sources += [
        (p, home / ".config/zsh" / p.name.removesuffix(".tmpl"))
        for p in (REPO / "dot_config/zsh").glob("*")
        if p.is_file()
    ]
    sources.append((REPO / "dot_config/starship.toml", home / ".config/starship.toml"))
    for source, destination in sources:
        if not source.exists():
            continue  # The red phase must fail on behavior, not a missing-file exception.
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text()
        if source.suffix == ".tmpl":
            text = subprocess.run(
                [
                    chezmoi,
                    "--config",
                    str(config),
                    "--source",
                    str(home),
                    "--destination",
                    str(home),
                    "--cache",
                    str(home / "chezmoi-cache"),
                    "--persistent-state",
                    str(home / "state.db"),
                    "execute-template",
                    "--left-delimiter",
                    "# {{",
                    "--right-delimiter",
                    "}}",
                ],
                input=text,
                env=env,
                cwd=home,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            ).stdout
        destination.write_text(text)
    plugin_root = Path.home() / ".config/zsh/plugins"
    for plugin in (
        "zsh-autosuggestions",
        "zsh-syntax-highlighting",
        "zsh-history-substring-search",
    ):
        installed = plugin_root / plugin
        assert installed.is_dir(), f"Missing integration prerequisite: {installed}"
        shutil.copytree(installed, home / ".config/zsh/plugins" / plugin)
    return ZshStartupSandbox(home, env, home / "calls.jsonl")


def test_noninteractive_ssh_environment_is_silent_and_preserves_local_state(
    zsh_startup: ZshStartupSandbox,
) -> None:
    local = zsh_startup.home / ".config/zsh/local-env.zsh"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(
        'export CRUST_LOG_LEVEL=debug\npath=("$HOME/local-runtime/bin" $path)\n'
    )
    result = zsh_startup.run(
        'print -r -- "$EDITOR|$LANG|$XDG_STATE_HOME|$CRUST_LOG_LEVEL"; print -rl -- "${path[@]}"'
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[0] == f"nano|en_US.UTF-8|{zsh_startup.home}/.local/state|debug"
    assert str(zsh_startup.home / "local-runtime/bin") in lines[1:]


def test_secret_exports_are_available_without_startup_output(
    zsh_startup: ZshStartupSandbox,
) -> None:
    secret_dir = zsh_startup.home / ".config/secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    (secret_dir / "env.zsh").write_text("export GITHUB_TOKEN=zsh-synthetic-only\n")
    result = zsh_startup.run(
        '[[ "$GITHUB_TOKEN" = zsh-synthetic-only && "$HOMEBREW_GITHUB_API_TOKEN" = "$GITHUB_TOKEN" ]]'
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_secret_source_failure_aborts_command_without_leaking(
    zsh_startup: ZshStartupSandbox,
) -> None:
    secret_dir = zsh_startup.home / ".config/secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    (secret_dir / "env.zsh").write_text(
        "export GITHUB_TOKEN=zsh-synthetic-only\nreturn 17\n"
    )
    result = zsh_startup.run("print command-must-not-run")
    assert result.returncode == 17
    assert result.stdout == result.stderr == ""


def test_git_worktree_wrapper_preserves_boundaries_and_exit_status(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("git", status=19)
    result = zsh_startup.run(
        "git worktree add '../space dir' '' '--literal=one two'; print -r -- $?",
        interactive=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "19\n"
    assert zsh_startup.recorded_calls() == [
        ["git", "cow-worktree", "add", "../space dir", "", "--literal=one two"]
    ]


def test_git_other_subcommands_and_aliases_forward_arguments(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("git")
    zsh_startup.spy("docker")
    result = zsh_startup.run(
        "g -C 'space dir' status; dc config --quiet; alias ll", interactive=True
    )
    assert result.returncode == 0, result.stderr
    assert "ll='ls -la'" in result.stdout
    assert zsh_startup.recorded_calls() == [
        ["git", "-C", "space dir", "status"],
        ["docker", "compose", "config", "--quiet"],
    ]


def test_interactive_integrations_and_all_six_fuzzy_bindings(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("mise", output="export ZSH_TEST_MISE_ACTIVATED=1\n")
    result = zsh_startup.run(
        "print -r -- $ZSH_TEST_MISE_ACTIVATED; "
        "(( $+functions[_zsh_autosuggest_start] && $+functions[_zsh_highlight] && $+functions[_main_complete] )); print $?; "
        "bindkey '^T'; bindkey '^R'; bindkey '^[c'; bindkey '^[C'; bindkey '^G'; bindkey '^O'; bindkey '^L'; "
        "print -r -- $HISTFILE $SAVEHIST; [[ -o SHARE_HISTORY && -o EXTENDED_HISTORY && -o HIST_IGNORE_SPACE ]]; print $?",
        interactive=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[:2] == ["1", "0"]
    assert [line.split()[-1] for line in lines[2:9]] == [
        "zsh-fuzzy-insert-files",
        "fzf-history-widget",
        "zsh-fuzzy-directory",
        "zsh-fuzzy-hidden-directory",
        "zsh-fuzzy-open-files",
        "zsh-fuzzy-edit-files",
        "zsh-clear-screen",
    ]
    assert str(zsh_startup.home / ".zsh_history") in lines[9]
    assert lines[10] == "0"
    assert ["mise", "activate", "zsh"] in zsh_startup.recorded_calls()


def test_mise_activation_failure_is_not_silently_ignored(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("mise", status=23)
    result = zsh_startup.run("print command-must-not-run", interactive=True)
    assert result.returncode == 23
    assert "command-must-not-run" not in result.stdout
    assert "zsh mise activation failed" in result.stderr


def test_timeout_delegates_to_platform_tool_with_exact_arguments(
    zsh_startup: ZshStartupSandbox,
) -> None:
    tool = "gtimeout" if sys.platform == "darwin" else "timeout"
    zsh_startup.spy(tool, status=124)
    result = zsh_startup.run(
        "timeout -k 2s 1m printf '%s' 'two words'; print $?", interactive=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "124\n"
    assert [
        tool,
        "-k",
        "2s",
        "1m",
        "printf",
        "%s",
        "two words",
    ] in zsh_startup.recorded_calls()


def test_prompt_keeps_runtime_versions_outside_projects_and_private_failure_info(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("node", output="v24.1.2\n")
    zsh_startup.spy(
        "ruby", output="ruby 3.3.8p0 (2025-01-01 revision abc) [arm64-darwin]\n"
    )
    zsh_startup.spy("python", output="Python 3.13.7\n")
    result = zsh_startup.run(
        "unset HISTFILE; zsh-prompt-context; starship prompt --status=1 --jobs=2",
        interactive=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    for expected in ("24.1.2", "3.3.8", "3.13.7", "private", "!", "%", "~"):
        assert expected in result.stdout


def test_login_shell_keeps_local_environment_and_is_silent(
    zsh_startup: ZshStartupSandbox,
) -> None:
    local = zsh_startup.home / ".config/zsh/local-env.zsh"
    local.write_text('path=("$HOME/host-runtime/bin" $path)\n')
    result = zsh_startup.run(
        "(( ${path[(Ie)$HOME/host-runtime/bin]} )) && [[ $EDITOR == nano ]]", login=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_native_token_context_preserves_quoted_paths_and_suffix(
    zsh_startup: ZshStartupSandbox,
) -> None:
    (zsh_startup.home / "folder with spaces").mkdir()
    result = zsh_startup.run(
        "BUFFER=\"echo 'folder with spaces/ite' tail\"; CURSOR=28; "
        "LBUFFER=${BUFFER[1,CURSOR]}; RBUFFER=${BUFFER[CURSOR+1,-1]}; "
        'typeset -a context; zsh-fuzzy-context; printf "<%s>\\n" "${context[@]}"',
        interactive=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "<folder with spaces>",
        "<ite>",
        "<echo >",
        "< tail>",
    ]


def test_terminal_file_picker_replaces_token_and_cancel_preserves_buffer(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("mise", output="export ZSH_TEST_MISE_ACTIVATED=1\n")
    selected = zsh_startup.home / "folder with spaces" / "item one"
    selected.parent.mkdir()
    selected.touch()
    zsh_startup.spy("fzf", output=str(selected) + "\0")
    output = zsh_startup.type_in_terminal(
        b"printf '<%s>\\n' fol\x14\nprint -r -- __ZSH_DONE__\n"
    )
    assert f"<{selected}>" in output
    fzf_call = next(call for call in zsh_startup.recorded_calls() if call[0] == "fzf")
    assert fzf_call[-2:] == ["--query", "fol"]
    zsh_startup.calls.unlink()
    zsh_startup.spy("fzf", status=130)
    output = zsh_startup.type_in_terminal(
        b"printf '<%s>\\n' unchanged\x14\nprint -r -- __ZSH_DONE__\n"
    )
    assert "<unchanged>" in output


@pytest.mark.parametrize(
    "key,opener",
    [(b"\x07", "open" if sys.platform == "darwin" else "xdg-open"), (b"\x0f", "nano")],
)
def test_terminal_file_openers_preserve_selection_arguments(
    zsh_startup: ZshStartupSandbox, key: bytes, opener: str
) -> None:
    zsh_startup.spy("mise", output="export ZSH_TEST_MISE_ACTIVATED=1\n")
    selected = zsh_startup.home / "selected file"
    selected.touch()
    zsh_startup.spy("fzf", output=str(selected) + "\0")
    zsh_startup.spy(opener)
    zsh_startup.type_in_terminal(key + b"print -r -- __ZSH_DONE__\n")
    assert [opener, str(selected)] in zsh_startup.recorded_calls()


def test_terminal_directory_picker_includes_hidden_only_for_alt_shift_c(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("mise", output="export ZSH_TEST_MISE_ACTIVATED=1\n")
    hidden = zsh_startup.home / ".hidden-folder"
    visible = zsh_startup.home / "visible-folder"
    hidden.mkdir()
    visible.mkdir()
    fzf = zsh_startup.home / ".local/bin/fzf"
    fzf.write_text(
        f"#!{sys.executable} -I\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "entries = sys.stdin.buffer.read().decode().split('\\0')\n"
        "with Path(os.environ['ZSH_TEST_CALLS']).open('a') as log:\n"
        "    log.write(json.dumps(['candidates', *entries]) + '\\n')\n"
        "print('./visible-folder', end='\\0')\n"
    )
    fzf.chmod(0o700)
    zsh_startup.type_in_terminal(b"\x1bcprint -r -- __ZSH_DONE__\n")
    normal = next(
        call for call in zsh_startup.recorded_calls() if call[0] == "candidates"
    )
    assert "./visible-folder" in normal
    assert "./.hidden-folder" not in normal
    zsh_startup.calls.unlink()
    zsh_startup.type_in_terminal(b"\x1bCprint -r -- __ZSH_DONE__\n")
    hidden_candidates = next(
        call for call in zsh_startup.recorded_calls() if call[0] == "candidates"
    )
    assert "./.hidden-folder" in hidden_candidates


def test_ssh_commands_keep_git_and_alias_routing(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("git")
    zsh_startup.spy("docker")
    result = zsh_startup.run("git worktree add 'ssh path'; dc config --quiet")
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""
    assert zsh_startup.recorded_calls() == [
        ["git", "cow-worktree", "add", "ssh path"],
        ["docker", "compose", "config", "--quiet"],
    ]


def test_hq_lambda_claude_routes_only_herdr_without_active_crust(
    zsh_startup: ZshStartupSandbox,
) -> None:
    zsh_startup.spy("claude")
    zsh_startup.spy("crust")
    result = zsh_startup.run(
        'HOST=HQ-Lambda; source "$XDG_CONFIG_HOME/zsh/shell-functions.zsh"; '
        "export HERDR_ENV=; claude 'two words'; export CRUST_ACTIVE=; claude --continue; "
        "unset HERDR_ENV CRUST_ACTIVE; claude --version"
    )
    assert result.returncode == 0, result.stderr
    assert zsh_startup.recorded_calls() == [
        ["crust", "two words"],
        ["claude", "--continue"],
        ["claude", "--version"],
    ]


def test_arrow_history_uses_substring_search_with_muted_highlights(
    zsh_startup: ZshStartupSandbox,
) -> None:
    result = zsh_startup.run(
        "bindkey '^[[A'; bindkey '^[[B'; "
        'print -r -- "$HISTORY_SUBSTRING_SEARCH_HIGHLIGHT_FOUND"',
        interactive=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        '"^[[A" history-substring-search-up',
        '"^[[B" history-substring-search-down',
        "fg=#cdd6f4,bg=#45475a",
    ]


@pytest.mark.parametrize("absolute", [False, True])
def test_terminal_picker_searches_inside_explicit_hidden_roots(
    zsh_startup: ZshStartupSandbox, absolute: bool
) -> None:
    zsh_startup.spy("mise", output="export ZSH_TEST_MISE_ACTIVATED=1\n")
    hidden = zsh_startup.home / ".selected-root"
    hidden.mkdir()
    (hidden / "visible-file").touch()
    fzf = zsh_startup.home / ".local/bin/fzf"
    fzf.write_text(
        f"#!{sys.executable} -I\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "entries = [p for p in sys.stdin.buffer.read().decode().split('\\0') if p]\n"
        "with Path(os.environ['ZSH_TEST_CALLS']).open('a') as log:\n"
        "    log.write(json.dumps(['candidates', *entries]) + '\\n')\n"
        "if not entries: sys.exit(130)\n"
        "print(entries[0], end='\\0')\n"
    )
    fzf.chmod(0o700)
    token = str(hidden) if absolute else ".selected-root"
    output = zsh_startup.type_in_terminal(
        f"printf '<%s>\\n' {shlex.quote(token)}/vis".encode()
        + b"\x14\nprint -r -- __ZSH_DONE__\n"
    )
    assert f"<{token}/visible-file>" in output
    candidates = next(
        call for call in zsh_startup.recorded_calls() if call[0] == "candidates"
    )
    assert f"{token}/visible-file" in candidates


def test_noninteractive_macos_exports_homebrew_environment(
    zsh_startup: ZshStartupSandbox,
) -> None:
    if sys.platform != "darwin":
        pytest.skip("Homebrew environment is macOS-only")
    result = zsh_startup.run(
        "[[ $HOMEBREW_PREFIX == /opt/homebrew && $HOMEBREW_CELLAR == /opt/homebrew/Cellar "
        "&& $HOMEBREW_REPOSITORY == /opt/homebrew && $INFOPATH == /opt/homebrew/share/info:* ]]"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize(
    "interactive,login", [(False, False), (False, True), (True, False), (True, True)]
)
def test_mise_runtime_wins_over_imported_paths_without_dropping_local_tools(
    zsh_startup: ZshStartupSandbox, interactive: bool, login: bool
) -> None:
    config = zsh_startup.home / ".config/mise/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[tools]\nnode = "24.0.0"\n')
    managed_bin = zsh_startup.home / ".local/share/mise/installs/node/24.0.0/bin"
    imported_bin = zsh_startup.home / "homebrew/bin"
    custom_bin = zsh_startup.home / "custom/bin"
    for directory in (managed_bin, imported_bin, custom_bin):
        directory.mkdir(parents=True)
    for executable, output in (
        (managed_bin / "node", "v24.0.0"),
        (imported_bin / "node", "v26.0.0"),
        (custom_bin / "local-tool", "local-tool-preserved"),
    ):
        executable.write_text(f'#!/bin/sh\nprintf "%s\\n" {shlex.quote(output)}\n')
        executable.chmod(0o700)
    (zsh_startup.home / ".config/zsh/local-env.zsh").write_text(
        'path=("$HOME/homebrew/bin" "$HOME/custom/bin" $path)\n'
    )
    result = zsh_startup.run(
        'node --version; local-tool; command -v node; print -r -- "${(j:|:)path}"',
        interactive=interactive,
        login=login,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[:3] == ["v24.0.0", "local-tool-preserved", str(managed_bin / "node")]
    paths = lines[3].split("|")
    assert paths.index(str(imported_bin)) < paths.index(str(custom_bin))
    assert str(zsh_startup.home / ".local/bin") in paths
