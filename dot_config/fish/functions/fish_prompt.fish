source ~/.local/share/omf/themes/bobthefish/functions/fish_prompt.fish

functions -c __bobthefish_glyphs __bobthefish_glyphs_original

function __bobthefish_glyphs -S
    if not set -q MC_SID
        __bobthefish_glyphs_original
    end

    set -x right_black_arrow_glyph ""
    set -x right_arrow_glyph       ""
end

function __bobthefish_prompt_node -S -d 'Display current Node information'
	[ "$theme_display_node" = 'no' ]
    and return

	set -l node_version

	if command -q node
        set -l current_node (echo -ns (string split "v" -- (node --version))[2])
        or return

        set node_version $current_node
    end

    [ -z "$node_version" ]
    and return

    __bobthefish_start_segment $color_node
    echo -ns $node_glyph $node_version ' '
    set_color normal
end

function __bobthefish_prompt_rubies -S -d 'Display current Ruby information'
    [ "$theme_display_ruby" = 'no' ]
    and return

    set -l ruby_version

    if command -q ruby
	    set -l current_ruby (echo -ns (string split " " -- (ruby --version))[2])
	    or return

	    set ruby_version $current_ruby
    end

    [ -z "$ruby_version" ]
    and return

    __bobthefish_start_segment $color_rvm
    echo -ns $ruby_glyph $ruby_version ' '
    set_color normal
end

function __bobthefish_prompt_virtualfish -S -d 'Display current Python information'
    [ "$theme_display_virtualenv" = 'no' ]
    and return

    set -l python_version

	if command -q python
		set -l current_python (echo -ns (string split " " -- (python --version))[2])
		or return

		set python_version $current_python
	end

	[ -z "$python_version" ]
	and return

    __bobthefish_start_segment $color_virtualfish
    echo -ns $virtualenv_glyph $python_version ' '
    set_color normal
end
