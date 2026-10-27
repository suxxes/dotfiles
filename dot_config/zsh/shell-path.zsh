# Only existing absolute directories are prepended; preserve inherited tool paths.
typeset -U path PATH
for zsh_shell_path in /opt/homebrew/sbin /opt/homebrew/bin /opt/homebrew/opt/libpq/bin \
    "$HOME/.local/share/mise/shims" "$HOME/.local/bin"; do
    [[ -d $zsh_shell_path ]] && path=("$zsh_shell_path" "${path[@]}")
done
unset zsh_shell_path
export PATH
