<!-- Updated: 2026-10-27 13:45:43 UTC -->

# Dotfiles

Cross-machine dotfiles and secrets management using chezmoi with 1Password integration.

- **Macbooks**: Interactive `op` CLI with biometric unlock
- **Linux/LXC**: 1Password Service Account (headless)

## Setup

### macOS

```bash
# Homebrew (skip if already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Put brew on PATH for the current shell and future zsh sessions
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"

# Bootstrap dotfiles
brew install chezmoi tmux 1password-cli git
op account add --address my.1password.com
op signin
chezmoi init --apply https://github.com/suxxes/dotfiles
chsh -s /bin/zsh
```

Zsh loads shared environment settings, Homebrew, and mise in `.zshenv`. Login startup restores path priority; interactive startup loads completions and the prompt.

### Linux / LXD Host

```bash
sudo apt update && sudo apt install -y zsh git curl unzip

# 1Password CLI
curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
  sudo gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/amd64 stable main" | \
  sudo tee /etc/apt/sources.list.d/1password.list
sudo apt update && sudo apt install -y 1password-cli

# 1Password service-account token: persisted so every future zsh shell
# loads it, then exported for the scripts this bootstrap runs.
# op refuses to run if ~/.config/op is looser than 700.
mkdir -p ~/.config/op
chmod 700 ~/.config/op
printf '%s\n' 'ops_xxxxxxxxxxxxx' > ~/.config/op/service-account-token
chmod 600 ~/.config/op/service-account-token
export OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)"

# chezmoi; init asks for the profile (work / personal / default) once
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b ~/.local/bin
~/.local/bin/chezmoi init --apply https://github.com/suxxes/dotfiles

chsh -s /usr/bin/zsh
```

### Switch an existing fish account

Chezmoi installs pinned zsh plugins and checks their archive checksums. Mise installs the Starship prompt. The state step copies exported universal fish variables, user paths, and saved history into zsh files. It keeps the fish files and does not replace existing zsh secret exports. The import renames the credential export `USERNAME` to `CREDENTIAL_USERNAME`. Zsh reserves `USERNAME` for the shell identity. Other conflicting names stop the import before it writes the exports.

1. Apply the dotfiles with `chezmoi apply`.
2. Run `zsh -lic 'command -v claude && command -v node && git --version'`. Continue only if every command succeeds.
3. Set the login shell with `chsh -s /bin/zsh` on macOS or `chsh -s /usr/bin/zsh` on Linux. This step can require your account password.
4. Open a new terminal. Existing sessions keep their current shell.

Session-only variables do not persist across a new login. Move any required session-only settings into your local zsh configuration before closing that session.

After the last fish session closes, run `~/.local/bin/migrate-fish-history` again to import its saved commands. The importer keeps timestamps and multiline entries. It does not run stored commands or change their syntax. Fish-specific commands in history still require fish syntax when reused.

The migration leaves the fish executable and its files available for open sessions and explicit fish scripts. New shells use zsh. Do not remove fish while those sessions or scripts still need it.

### Shell checks

The checks require Python, uv, chezmoi, fish, zsh, jq, fzf, mise, Starship, and the pinned plugins under `~/.config/zsh/plugins`. Install the plugins with `chezmoi apply --exclude=scripts ~/.config/zsh/plugins`.

Run `uvx --with pytest pytest tests/integration` from the source directory. The first run requires network access to download the test runner. The checks use temporary homes and synthetic secrets. They do not read account credentials or change a login shell.

### Profiles (work / personal)

The chezmoi template data has a `profile` field that gates a few installs and templates (Brewfile blocks, secrets loader). Values: `work`, `personal`, or `default`.

`.chezmoi.toml.tmpl` resolves the profile the same way on every OS, in this order:

1. `~/.chezmoi-profile` — a file containing the single word `work` or `personal`. Present but empty → `default`.
2. `/.profile` at the filesystem root — the legacy marker, kept for the existing LXC fleet. Same semantics. On the next apply, `run_once_after_migrate-profile-marker.sh.tmpl` copies its value into `~/.chezmoi-profile`, after which the root file is inert.
3. A one-time prompt. The answer persists in the generated config, so only the first `chezmoi init` on a machine asks. Unattended init with no marker must pre-answer with `chezmoi init --promptString profile=work`; without a TTY the prompt fails instead of falling back.

Any value outside `work` / `personal` / `default` fails `chezmoi init`. Markers are read at init, not apply: edit one (or change the prompt answer via `--promptString`) and re-run `chezmoi init` for it to take effect. Machines set up before the prompt existed keep their profile — the prompt reuses the value already in the config.

Consumers today: the Brewfile (`{{ if eq .profile "work" }}` gates the work casks; `personal` gates Blender/CodexBar/Discord/Godot/Steam/Tuist), the mise config (`work` adds jira-cli), `.chezmoiignore` (CodexBar config is personal macOS only, claude-swap LaunchAgent is work macOS only), `run_onchange_after_setup-claude-swap.sh.tmpl` (work only, both platforms), and `run_after_generate-secrets.sh.tmpl` (chooses which 1Password vault the Tailscale auth key comes from).

Only `osType` and `profile` are exported as template data. Hostname is deliberately not: data is written once at `chezmoi init` and would go stale on rename, so templates read `.chezmoi.hostname` directly instead.

### claude-swap (work only)

[claude-swap](https://github.com/realiti4/claude-swap) switches Claude Code between accounts before a rate limit lands. `run_onchange_after_setup-claude-swap.sh.tmpl` installs it with `uv tool install claude-swap`, sets `autoswitch.strategy` to `consume-first`, and starts the auto-switcher as a background service. Work profile only, template-gated on both platforms.

- **macOS**: LaunchAgent `dev.suxxes.cswap-auto`, from `private_Library/private_LaunchAgents/dev.suxxes.cswap-auto.plist.tmpl`. Logs to `~/Library/Logs/cswap-auto.log`.
- **Linux**: systemd user unit `cswap-auto.service`, written by the script and kept alive across logouts with `loginctl enable-linger`. Logs go to the journal (`journalctl --user -u cswap-auto`).

On Linux the account store is shared, not container-local, and the LXD profile owns that mount. cswap keeps accounts in `~/.local/share/claude-swap`; the `development/work` profile writes `home-suxxes-.local-share-claude\x2dswap.mount`, binding it to `/mnt/shared-work/.claude-swap`, alongside the units it already writes for `~/.claude`, `~/.codex`, `~/.agents`, and `~/.pi`. The dotfiles do not create it. Every container runs its own auto-switcher; they coordinate through the shared cooldown and quarantine state and take the same credential locks, at the cost of one usage poller per container. macOS keeps its own store in the Keychain, separate from the volume.

`consume-first` keeps you on the account whose weekly window resets soonest, so perishable quota is spent before it expires. Change it with `cswap config set autoswitch.strategy best`; the script rewrites the value on every apply.

Cloud-init runs once, at first boot, so a profile change reaches new containers only. Add the mount unit to an existing container by hand, and give any other profile the same unit if its containers should share accounts.

Accounts are not part of the dotfiles. Log into Claude Code with each account and run `cswap add` once per account, or restore them from an export with `cswap import <file>.cswap`. Run `cswap list` to see usage and which account is active.

### chezmoi versions

macOS upgrades chezmoi through the Brewfile. Linux installs it once at bootstrap, so `run_onchange_install-packages.sh.tmpl` holds a `CHEZMOI_MIN_VERSION` floor and runs `chezmoi upgrade` on any host below it. Raise that floor to roll the fleet forward.

## Usage

```bash
chezmoi edit ~/.zshrc                     # Edit config
chezmoi apply --force                                       # Apply locally (overwrites drifted files; required so run_after_ scripts always reach the tailscale self-heal)
chezmoi cd && git add . && git commit -m "msg" && git push  # Push changes
chezmoi update                                              # Pull on other machines
```

### Adding secrets

1. Add to 1Password `Secrets` vault
2. Update `dot_config/zsh/secrets.zsh.tmpl`
3. Push and run `chezmoi update` on all machines

## Troubleshooting

```bash
chezmoi data | grep -E "(osType|profile)"      # Check machine detection
chezmoi apply --dry-run --verbose              # Dry run
chezmoi execute-template '{{ .profile }}'      # Debug templates
chezmoi status                                 # Pending changes and scripts
op read "op://Secrets/Github/GITHUB_TOKEN" | wc -c   # Test 1Password access without printing the token
```
