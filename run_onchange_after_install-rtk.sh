#!/bin/bash
# Configures global rtk integrations for the Claude and Codex CLIs.

set -e

# The Linux package hook installs mise in ~/.local/bin without changing this hook's PATH.
export PATH="$PATH:$HOME/.local/bin"
eval "$(mise activate bash --shims)"

if command -v rtk &>/dev/null; then
    echo "==> Initializing rtk global integrations"
    rtk init --global --codex
    rtk init --global --agent claude --auto-patch --trust-filters
fi
