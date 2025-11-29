<!-- Updated: 2025-11-29 11:47:32 UTC -->

# Dotfiles

Cross-machine dotfiles and secrets management using chezmoi with 1Password integration.

- **Macbooks**: Interactive `op` CLI with biometric unlock
- **Linux/LXC**: 1Password Service Account (headless)

## Setup

### macOS

```bash
brew install chezmoi fish tmux 1password-cli git
op account add --address my.1password.com
op signin
chezmoi init --apply https://github.com/suxxes/dotfiles
echo /opt/homebrew/bin/fish | sudo tee -a /etc/shells
chsh -s /opt/homebrew/bin/fish
```

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

## Usage

```bash
chezmoi edit ~/.config/fish/config.fish                     # Edit config
chezmoi apply                                               # Apply locally
chezmoi cd && git add . && git commit -m "msg" && git push  # Push changes
chezmoi update                                              # Pull on other machines
```

### Adding secrets

1. Add to 1Password `Secrets` vault
2. Update `dot_config/fish/conf.d/50-secrets.fish.tmpl`
3. Push and run `chezmoi update` on all machines

## Troubleshooting

```bash
chezmoi data | grep -E "(osType|machineType)"  # Check machine detection
chezmoi apply --dry-run --verbose              # Dry run
chezmoi execute-template '{{ .machineType }}'  # Debug templates
op read "op://Secrets/API Keys/GITHUB_TOKEN"   # Test 1Password access
```
