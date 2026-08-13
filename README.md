<!-- Updated: 2026-08-13 14:40:47 UTC -->

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
brew install chezmoi fish tmux 1password-cli git
op account add --address my.1password.com
op signin
chezmoi init --apply https://github.com/suxxes/dotfiles
echo /opt/homebrew/bin/fish | sudo tee -a /etc/shells
chsh -s /opt/homebrew/bin/fish
```

Once fish is your login shell, `dot_config/fish/conf.d/00-path.fish` re-runs `brew shellenv` on every shell start, so the `~/.zprofile` line is only relevant to any zsh session you keep open.

### Linux / LXD Host

```bash
sudo apt update && sudo apt install -y fish git curl unzip

# 1Password CLI
curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
  sudo gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/amd64 stable main" | \
  sudo tee /etc/apt/sources.list.d/1password.list
sudo apt update && sudo apt install -y 1password-cli

# chezmoi
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b ~/.local/bin
export OP_SERVICE_ACCOUNT_TOKEN="ops_xxxxxxxxxxxxx"
~/.local/bin/chezmoi init --apply https://github.com/suxxes/dotfiles

echo /usr/bin/fish | sudo tee -a /etc/shells
chsh -s /usr/bin/fish
```

### Profiles (work / personal)

The chezmoi template data has a `profile` field that gates a few installs and templates (Brewfile blocks, secrets loader). Values: `work`, `personal`, or `default`.

- **macOS**: derived from the hostname by `.chezmoi.toml.tmpl`, never prompted. `uRetina` → `personal`, `kRetina` → `work`, `sRetina` → `work`. Matching is case-insensitive and reads `LocalHostName`, so set that (and `ComputerName`) when naming a new Mac. An unrecognised Mac hostname fails `chezmoi init` with a message naming the host; add it to the map in `.chezmoi.toml.tmpl` rather than answering a prompt. Rename a machine and you must re-run `chezmoi init` for the new profile to take effect.
- **Linux / LXC**: create a file at `/.profile` (yes, at the filesystem root) containing the single word `work` or `personal`. Missing or empty → `default`. Chezmoi doesn't read this file directly; the install scripts do, so the file has to exist on the host before you run apply.

Consumers today: the Brewfile (`{{ if eq .profile "work" }}` gates the work CLIs and casks; `personal` gates Blender/CodexBar/Discord/Godot/Steam/Tuist), `.chezmoiignore` (CodexBar config is personal macOS only, claude-swap LaunchAgent is work macOS only), `run_onchange_after_setup-claude-swap.sh.tmpl` (work only, both platforms), and `run_after_generate-secrets.sh.tmpl` (chooses which 1Password vault the Tailscale auth key comes from).

Only `osType` and `profile` are exported as template data. Hostname is deliberately not: data is written once at `chezmoi init` and would go stale on rename, so templates read `.chezmoi.hostname` directly instead.

### claude-swap (work only)

[claude-swap](https://github.com/realiti4/claude-swap) switches Claude Code between accounts before a rate limit lands. `run_onchange_after_setup-claude-swap.sh.tmpl` installs it with `uv tool install claude-swap`, sets `autoswitch.strategy` to `consume-first`, and starts the auto-switcher as a background service. Work profile only: template-gated on macOS, gated on the runtime `/.profile` file on Linux.

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
chezmoi edit ~/.config/fish/config.fish                     # Edit config
chezmoi apply --force                                       # Apply locally (overwrites drifted files; required so run_after_ scripts always reach the tailscale self-heal)
chezmoi cd && git add . && git commit -m "msg" && git push  # Push changes
chezmoi update                                              # Pull on other machines
```

### Adding secrets

1. Add to 1Password `Secrets` vault
2. Update `dot_config/fish/conf.d/50-secrets.fish.tmpl`
3. Push and run `chezmoi update` on all machines

## Troubleshooting

```bash
chezmoi data | grep -E "(osType|profile)"      # Check machine detection
chezmoi apply --dry-run --verbose              # Dry run
chezmoi execute-template '{{ .profile }}'      # Debug templates
chezmoi status                                 # Pending changes and scripts
op read "op://Secrets/API Keys/GITHUB_TOKEN"   # Test 1Password access
```
