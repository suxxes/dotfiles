function timeout --description 'Run command with time limit'
    # Check if timeout command already exists
    if command -q timeout
        command timeout $argv
        return $status
    end

    # Parse arguments
    set -l duration ""
    set -l signal "TERM"
    set -l kill_after ""
    set -l preserve_status false
    set -l command_args

    set -l i 1
    while test $i -le (count $argv)
        set -l arg $argv[$i]

        switch $arg
            case '-s' '--signal'
                set i (math $i + 1)
                if test $i -le (count $argv)
                    set signal $argv[$i]
                end
            case '-k' '--kill-after'
                set i (math $i + 1)
                if test $i -le (count $argv)
                    set kill_after $argv[$i]
                end
            case '--preserve-status'
                set preserve_status true
            case '-h' '--help'
                echo "Usage: timeout [OPTION] DURATION COMMAND [ARG]..."
                echo "Run COMMAND with time limit of DURATION."
                echo ""
                echo "DURATION is a floating point number with optional suffix:"
                echo "  's' for seconds (default), 'm' for minutes, 'h' for hours"
                echo ""
                echo "Options:"
                echo "  -s, --signal=SIGNAL    specify signal to send on timeout (default: TERM)"
                echo "  -k, --kill-after=DUR   send KILL signal after DUR if command still running"
                echo "  --preserve-status      exit with status of COMMAND even on timeout"
                echo "  -h, --help            display this help and exit"
                return 0
            case '-*'
                echo "timeout: invalid option -- '$arg'" >&2
                echo "Try 'timeout --help' for more information." >&2
                return 125
            case '*'
                if test -z "$duration"
                    set duration $arg
                else
                    set command_args $argv[$i..-1]
                    break
                end
        end
        set i (math $i + 1)
    end

    # Validate arguments
    if test -z "$duration"
        echo "timeout: missing operand" >&2
        echo "Try 'timeout --help' for more information." >&2
        return 125
    end

    if test (count $command_args) -eq 0
        echo "timeout: missing command" >&2
        return 125
    end

    # Parse duration (convert to seconds)
    set -l timeout_seconds
    set -l duration_value (string replace -r '[smh]$' '' $duration)
    set -l duration_unit (string match -r '[smh]$' $duration)

    if test -z "$duration_unit"
        set timeout_seconds $duration_value
    else
        switch $duration_unit
            case 's'
                set timeout_seconds $duration_value
            case 'm'
                set timeout_seconds (math "$duration_value * 60")
            case 'h'
                set timeout_seconds (math "$duration_value * 3600")
        end
    end

    # Validate timeout value
    if not string match -qr '^[0-9.]+$' $timeout_seconds
        echo "timeout: invalid time interval '$duration'" >&2
        return 125
    end

    # Parse kill-after duration if provided
    set -l kill_seconds ""
    if test -n "$kill_after"
        set -l kill_value (string replace -r '[smh]$' '' $kill_after)
        set -l kill_unit (string match -r '[smh]$' $kill_after)

        if test -z "$kill_unit"
            set kill_seconds $kill_value
        else
            switch $kill_unit
                case 's'
                    set kill_seconds $kill_value
                case 'm'
                    set kill_seconds (math "$kill_value * 60")
                case 'h'
                    set kill_seconds (math "$kill_value * 3600")
            end
        end
    end

    # Create a temporary file for the PID
    set -l pid_file (mktemp /tmp/timeout.XXXXXX)

    # Run command in background and save PID
    fish -c "echo \$fish_pid > $pid_file; exec $command_args" &
    set -l cmd_pid $last_pid

    # Wait for PID file to be written
    sleep 0.1
    if test -f $pid_file
        set cmd_pid (cat $pid_file)
        rm -f $pid_file
    end

    # Start timeout monitor
    fish -c "
        sleep $timeout_seconds
        if kill -0 $cmd_pid 2>/dev/null
            kill -$signal $cmd_pid 2>/dev/null
            if test -n '$kill_seconds'
                sleep $kill_seconds
                if kill -0 $cmd_pid 2>/dev/null
                    kill -KILL $cmd_pid 2>/dev/null
                end
            end
        end
    " &
    set -l timeout_pid $last_pid

    # Wait for command to finish
    wait $cmd_pid
    set -l exit_status $status

    # Kill timeout monitor if still running
    kill $timeout_pid 2>/dev/null
    wait $timeout_pid 2>/dev/null

    # Return appropriate exit status
    if test $exit_status -eq 124 -o $exit_status -eq 137
        # Command was terminated by timeout
        if test $preserve_status = true
            return $exit_status
        else
            return 124
        end
    else
        return $exit_status
    end
end
