# Routes "git worktree add" through git cow-worktree, which reflinks the
# checkout from an existing worktree. Every other git call passes through.
function git --wraps git --description 'git with copy-on-write worktree add'
    if test (count $argv) -ge 2; and test "$argv[1]" = worktree; and test "$argv[2]" = add
        command git cow-worktree add $argv[3..]
        return
    end
    command git $argv
end
