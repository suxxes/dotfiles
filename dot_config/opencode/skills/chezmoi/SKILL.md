---
name: chezmoi
description: Work with this Chezmoi-managed dotfiles repository safely across machines.
---

# Chezmoi Dotfiles

Use this skill when editing or reviewing files managed by Chezmoi.

- Edit source files in the Chezmoi source directory, not generated files under `$HOME`.
- Run `chezmoi diff` or `chezmoi apply --dry-run --verbose` before applying changes.
- Treat SSH, 1Password, AWS, Tailscale, and generated secret files as sensitive.
- Do not run `chezmoi apply` unless the user explicitly asks to apply changes.
- If templates depend on machine data, inspect `chezmoi data` before assuming a value.
