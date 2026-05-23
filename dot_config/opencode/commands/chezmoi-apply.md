---
description: Dry-run and apply Chezmoi dotfile changes
agent: build
---

Prepare to apply Chezmoi dotfile changes.

First run `chezmoi apply --dry-run --verbose` and summarize exactly what would change. If the user already asked to apply changes, run `chezmoi apply` after the dry-run succeeds. Otherwise, stop after the dry-run summary and ask for confirmation.
