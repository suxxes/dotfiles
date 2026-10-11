#!/bin/bash
# Installs Claude Code plugins
# Hash: orchestrator@resin-ai from suxxes/resin.ai marketplace

set -e

# mise owns the binary; put its shims on PATH for a fresh host whose shell never activated mise.
eval "$(mise activate bash --shims)"

if command -v claude &> /dev/null; then
    echo "==> Configuring Claude Code plugins"

    # Add custom marketplace
    if ! claude plugin marketplace list 2>/dev/null | grep -q "resin.ai"; then
        echo "==> Adding suxxes/resin.ai marketplace"
        claude plugin marketplace add suxxes/resin.ai

        echo "==> Installing orchestrator@resin-ai plugin"
        claude plugin install orchestrator@resin-ai
    fi
fi
