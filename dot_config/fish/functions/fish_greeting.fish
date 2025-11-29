function fish_greeting
    # Clear screen
    tput clear

    tput cup (tput lines) 0
end

bind \cl 'fish_greeting; commandline -f repaint'
