#!/bin/bash
# Configures global rtk integrations for the Claude and Codex CLIs.

set -e

if command -v rtk &> /dev/null; then
    echo "==> Initializing rtk global integrations"
    rtk init --global --codex
    rtk init --global --agent claude --auto-patch --trust-filters
fi
