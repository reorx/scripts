#!/usr/bin/env bash
set -Eeu -o pipefail

# Look through the local filesystem and exclude development dependencies
# from Apple Time Machine backups.
#
# Since these files can be restored easily via their respective installation
# tools, there's no reason to waste time/bandwidth on backing them up.
#
# To retrieve a full list of excluded files, you may run:
#
#   sudo mdfind "com_apple_backup_excludeItem = 'com.apple.backupd'"
#
# For a full explanation, please see https://apple.stackexchange.com/a/25833/206772
#
# @version 0.3.0
# @author  Steve Grunwell
# @license MIT

readonly ASIMOV_ROOT=~/Code

# Paths to unconditionally skip over. This prevents Asimov from modifying the
# Time Machine exclusions for these paths (and decendents). It has an important
# side-effect of speeding up the search.
readonly ASIMOV_SKIP_PATHS=(
    ~/Code/go
)

# A list of "directory"/"sentinel" pairs.
#
# Directories will only be excluded if the dependency ("sentinel") file exists.
#
# For example, 'node_modules package.json' means "exclude node_modules/ from the
# Time Machine backups if there is a package.json file next to it."
readonly ASIMOV_VENDOR_DIR_SENTINELS=(
    '.tox tox.ini'                     # Tox (Python)
    '.vagrant Vagrantfile'             # Vagrant
    '.venv requirements.txt'           # virtualenv (Python)
    '.venv pyproject.toml'             # virtualenv (Python)
    'venv setup.py'                   # Python
    'venv manage.py'                   # Python django
    'venv requirements.txt'            # virtualenv (Python)
    'node_modules package.json'        # npm, Yarn (NodeJS)
    'build package.json'        # npm, Yarn (NodeJS)
    'dist package.json'        # npm, Yarn (NodeJS)
    'public config.yaml'        # hugo
    'target Cargo.toml'                # Cargo (Rust)
    'vendor go.mod'                    # Go Modules (Golang)
)

# Exclude the given paths from Time Machine backups.
# Reads the newline-separated list of paths from stdin.
exclude_file() {
    local path
    while IFS=$'\n' read -r path; do
        if tmutil isexcluded "${path}" | grep -Fq '[Excluded]'; then
            echo "- ${path} is already excluded, skipping."
            continue
        fi

        tmutil addexclusion "${path}"

        sizeondisk=$(du -hs "${path}" | cut -f1)
        echo "- ${path} has been excluded from Time Machine backups (${sizeondisk})."
    done
}

# Iterate over the skip directories to construct the `find` expression.
declare -a find_parameters_skip=()
for d in "${ASIMOV_SKIP_PATHS[@]}"; do
    find_parameters_skip+=( -not \( -path "${d}" -prune \) )
done

# Iterate over the directory/sentinel pairs to construct the `find` expression.
declare -a find_parameters_vendor=()
for i in "${ASIMOV_VENDOR_DIR_SENTINELS[@]}"; do
    read -ra parts <<< "${i}"

    # Add this folder to the `find` list, allowing a single `find` command to find all
    _exclude_name="${parts[0]}"
    _sibling_sentinel_name="${parts[1]}"

    # Given a directory path, determine if the corresponding file (relative
    # to that directory) is available.
    #
    # For example, when looking at a /vendor directory, we may choose to
    # ensure a composer.json file is available.
    find_parameters_vendor+=( -or \( \
        -type d \
        -name "${_exclude_name}" \
        -execdir test -e "${_sibling_sentinel_name}" \; \
        -prune \
        -print \
    \) )
done

printf '\n\033[0;36mFinding dependency directories with corresponding definition files…\033[0m\n'

find "${ASIMOV_ROOT}" \( "${find_parameters_skip[@]}" \) \( -false "${find_parameters_vendor[@]}" \) \
    | exclude_file \
    ;
