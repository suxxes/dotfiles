<!-- Updated: 2026-07-19 16:37:28 UTC -->

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

- **macOS**: `chezmoi init` prompts once via `.chezmoi.toml.tmpl` and stores the answer. Re-prompt with `chezmoi init` again if you want to change it.
- **Linux / LXC**: create a file at `/.profile` (yes, at the filesystem root) containing the single word `work` or `personal`. Missing or empty → `default`. Chezmoi doesn't read this file directly; the install scripts do, so the file has to exist on the host before you run apply.

Consumers today: the Brewfile (`{{ if eq .profile "work" }}` gates Railway/Render/Supabase; `personal` gates Blender/Godot/Tuist/Discord/Ivory), and `run_after_generate-secrets.sh.tmpl` (chooses which 1Password vault the Tailscale auth key comes from).

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

### Claude Code through CLIProxyAPI

On personal-profile macOS machines, the Brewfile installs CLIProxyAPI and `run_after_setup-cliproxyapi.sh.tmpl` completes machine-local setup. Work-profile Macs and Linux machines skip installation, setup, and `claudex` command. Personal setup creates a unique API key, restricts listener to `127.0.0.1`, starts Homebrew service, and launches Codex OAuth when no credential exists.

API key lives at `~/.config/cliproxyapi/api-key`. Codex OAuth credentials live under `~/.cli-proxy-api/`. Both paths use private permissions and remain outside dotfiles repository. New Mac therefore requires one browser approval during first `chezmoi apply`; later applies are non-interactive.

After setup, run `claudex` to start Claude Code with `gpt-5.6-sol` through local proxy. Wrapper strips Anthropic credentials from Claude Code subprocess environments.

## Troubleshooting

```bash
chezmoi data | grep -E "(osType|machineType)"  # Check machine detection
chezmoi apply --dry-run --verbose              # Dry run
chezmoi execute-template '{{ .machineType }}'  # Debug templates
op read "op://Secrets/API Keys/GITHUB_TOKEN"   # Test 1Password access
```
