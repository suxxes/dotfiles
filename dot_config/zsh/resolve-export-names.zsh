#!/bin/zsh -df
# Resolve export names without values; USERNAME maps to CREDENTIAL_USERNAME, while writable exported scalars remain valid.
emulate -L zsh
zmodload zsh/parameter || exit

if (( ${argv[(Ie)USERNAME]} && ${argv[(Ie)CREDENTIAL_USERNAME]} )); then
    print -ru2 -- "Shell secret export ambiguous names: USERNAME CREDENTIAL_USERNAME"
    exit 1
fi

resolved_names=()
for export_name in "$@"; do
    if [[ ! $export_name =~ '^[A-Za-z_][A-Za-z0-9_]*$' ]]; then
        print -ru2 -- "Shell secret export invalid variable name: $export_name"
        exit 1
    fi
    if [[ $export_name == USERNAME ]]; then
        export_name=CREDENTIAL_USERNAME
    fi
    parameter_attributes=${parameters[$export_name]-}
    if [[ $parameter_attributes == *readonly* ||
          ($parameter_attributes == *special* && $parameter_attributes != scalar*export*) ]]; then
        print -ru2 -- "Shell secret export conflicts with zsh parameter: $export_name"
        exit 1
    fi
    resolved_names+=("$export_name")
done

if (( ${#resolved_names} )); then
    print -rl -- "${resolved_names[@]}"
fi
