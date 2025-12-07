#!/bin/bash
# Installs Catppuccin theme for bat
# Hash: Catppuccin Mocha theme from https://github.com/catppuccin/bat

set -e

# Install Catppuccin theme for bat
if command -v bat &> /dev/null; then
    echo "==> Installing Catppuccin theme for bat"
    mkdir -p "$(bat --config-dir)/themes"
    if [ ! -f "$(bat --config-dir)/themes/Catppuccin Mocha.tmTheme" ]; then
        curl -fsSL https://github.com/catppuccin/bat/raw/main/themes/Catppuccin%20Mocha.tmTheme \
            -o "$(bat --config-dir)/themes/Catppuccin Mocha.tmTheme"
        bat cache --build
    fi
fi
