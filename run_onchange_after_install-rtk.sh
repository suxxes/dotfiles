#!/bin/bash
# Configures global rtk integrations for the Claude and Codex CLIs.

set -e

# mise owns the binary; put its shims on PATH for a fresh host whose shell never activated mise.
eval "$(mise activate bash --shims)"

if command -v rtk &> /dev/null; then
    echo "==> Initializing rtk global integrations"
    rtk init --global --codex
    rtk init --global --agent claude --auto-patch --trust-filters
fi
