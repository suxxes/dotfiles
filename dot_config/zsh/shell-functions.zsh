# Copy-on-write worktree add keeps argument boundaries and Git's exit status.
function git() {
    if [[ $# -ge 2 && $1 == worktree && $2 == add ]]; then
        command git cow-worktree add "${@:3}"
    else
        command git "$@"
    fi
}

alias ll='ls -la'
alias g=git
alias dc='docker compose'

if [[ $OSTYPE == darwin* ]]; then
    # Homebrew coreutils provides the GNU timeout interface on macOS.
    function timeout() { command gtimeout "$@"; }
fi

if [[ ${HOST%%.*} == HQ-Lambda ]]; then
    # Herd routes Claude through crust only outside an existing crust session.
    function claude() {
        if ((${+HERDR_ENV} && ! ${+CRUST_ACTIVE})); then
            command crust "$@"
        else
            command claude "$@"
        fi
    }
fi

# Clear screen matches the former greeting and Ctrl-L, including bottom placement.
function zsh-clear-screen() {
    echoti clear
    echoti cup $((LINES - 1)) 0
    zle reset-prompt 2> /dev/null
}
