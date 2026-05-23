# Global OpenCode Rules

- Prefer concise, concrete engineering responses.
- Read project-local instructions before editing files.
- Do not expose secrets, credentials, tokens, or generated secret files.
- For Chezmoi-managed dotfiles, edit source files in the Chezmoi source directory, then verify with `chezmoi diff` or `chezmoi apply --dry-run --verbose`.
- Do not apply dotfile changes to the home directory unless the user explicitly asks.
