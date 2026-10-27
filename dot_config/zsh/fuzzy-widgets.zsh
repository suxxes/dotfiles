# Keep the former fzf display and preview defaults.
export FZF_DEFAULT_OPTS='--height 40%'
export FZF_TMUX_HEIGHT='40%'
FZF_PREVIEW_FILE_CMD='head -n 10'
FZF_PREVIEW_DIR_CMD=ls

# Native zsh tokenization gives the current token and untouched buffer boundaries.
function zsh-fuzzy-context() {
    local -a reply
    local REPLY REPLY2
    split-shell-arguments
    local index=$REPLY token='' prefix='' suffix=''
    if ((index % 2 && index > 1)) && [[ -z $reply[index] ]]; then
        ((index--))
    fi
    if ((index % 2)); then
        prefix=$LBUFFER
        suffix=$RBUFFER
    else
        token=${(Q)reply[index]}
        prefix="${(j::)reply[1,index-1]}"
        suffix="${(j::)reply[index+1,-1]}"
    fi
    token=${token/#\~\//$HOME/}
    [[ $token == '~' ]] && token=$HOME
    local dir=$token query
    [[ -n $dir ]] || dir=.
    while [[ ! -d $dir ]]; do
        dir=${dir:h}
    done
    if [[ $dir == . && $token != .* ]]; then
        query=$token
    else
        query=${token#$dir}
        query=${query#/}
    fi
    context=("$dir" "$query" "$prefix" "$suffix")
}

# File selection returns NUL-delimited paths without evaluating typed shell text.
function zsh-fuzzy-select-files() {
    local selected
    selected="$(command find -L "$context[1]" -mindepth 1 -path "$context[1]*/.*" -prune -o \
        \( -type f -o -type d -o -type l \) -print0 2> /dev/null |
        command fzf --read0 --print0 --multi --query "$context[2]")" || return $?
    selections=("${(@0)selected}")
    selections=("${(@)selections:#}")
}

# Ctrl-T replaces the current path token, preserving the rest of the command.
function zsh-fuzzy-insert-files() {
    local -a context selections
    zsh-fuzzy-context
    zsh-fuzzy-select-files || return 0
    (($#selections)) || return 0
    LBUFFER="$context[3]${(j: :)${(q)selections}} "
    RBUFFER=$context[4]
    zle reset-prompt
}

# Directory selection differs only in which hidden subtree is pruned.
function zsh-fuzzy-change-directory() {
    local -a context
    zsh-fuzzy-context
    local selected
    selected="$(command find -L "$context[1]" -mindepth 1 -path "$context[1]$1" -prune -o -type d -print0 2> /dev/null |
        command fzf --read0 --print0 --no-multi --query "$context[2]")" || return 0
    selected=${selected%$'\0'}
    [[ -n $selected ]] || return 0
    builtin cd -- "$selected" || return $?
    LBUFFER=$context[3]
    RBUFFER=$context[4]
    zle reset-prompt
}

# Alt-c excludes hidden directories, matching the original fish picker.
function zsh-fuzzy-directory() { zsh-fuzzy-change-directory '*/.*'; }

# Alt-C includes hidden directories but excludes Git metadata.
function zsh-fuzzy-hidden-directory() { zsh-fuzzy-change-directory '*/.git*'; }

# Opening files executes a quoted command line, so selections stay single arguments.
function zsh-fuzzy-open-selection() {
    local -a opener=("$@") context selections
    zsh-fuzzy-context
    zsh-fuzzy-select-files || return 0
    (($#selections)) || return 0
    BUFFER="${(j: :)${(q)opener}} ${(j: :)${(q)selections}}"
    zle accept-line
}

# Ctrl-G opens selected files with the platform application launcher.
function zsh-fuzzy-open-files() {
    if [[ $OSTYPE == darwin* ]]; then
        zsh-fuzzy-open-selection open
    else
        zsh-fuzzy-open-selection xdg-open
    fi
}

# Ctrl-O opens selected files in the configured editor, preserving editor arguments.
function zsh-fuzzy-edit-files() { zsh-fuzzy-open-selection ${(z)EDITOR}; }

zle -N zsh-fuzzy-insert-files
zle -N zsh-fuzzy-directory
zle -N zsh-fuzzy-hidden-directory
zle -N zsh-fuzzy-open-files
zle -N zsh-fuzzy-edit-files
bindkey '^T' zsh-fuzzy-insert-files
bindkey '^R' fzf-history-widget
bindkey '^[c' zsh-fuzzy-directory
bindkey '^[C' zsh-fuzzy-hidden-directory
bindkey '^G' zsh-fuzzy-open-files
bindkey '^O' zsh-fuzzy-edit-files
