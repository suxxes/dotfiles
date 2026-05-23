---
description: Review pending Chezmoi dotfile changes
agent: plan
---

Review the current Chezmoi dotfiles state.

Run `git status --short` and `chezmoi diff`, then summarize:

- managed source files that changed
- home-directory files that would change
- any risky secret, SSH, shell, or package-install changes
- the safest next command to run

Do not apply changes.
