#!/bin/bash
# Configures global rtk integrations for the Claude and Codex CLIs.

set -e

if command -v rtk &> /dev/null; then
    echo "==> Initializing rtk global integrations"
    rtk init -g --codex
    rtk init -g --claude
fi
