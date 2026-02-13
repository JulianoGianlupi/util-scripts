#!/usr/bin/env bash
#
# git-lfs-migrate-safe: Safety wrapper for git lfs migrate
#
# Restricts migration to files already tracked in .gitattributes
# Usage: glms <subcommand> [options]
#


# Global variables
SUBCOMMAND=""
USER_INCLUDES=()
FILTERED_ARGS=()
SKIP_CONFIRMATION=false

# ============================================================================
# ARGUMENT PARSING
# ============================================================================

parse_arguments() {
    local skip_next=false

    for arg in "$@"; do
        if [ "$skip_next" = true ]; then
            USER_INCLUDES+=("$arg")
            skip_next=false
            continue
        fi

        case "$arg" in
            info|import|export)
                if [ -z "$SUBCOMMAND" ]; then
                    SUBCOMMAND="$arg"
                else
                    # Treat as branch/ref if subcommand already set
                    FILTERED_ARGS+=("$arg")
                fi
                ;;
            --include|-I)
                skip_next=true
                ;;
            -y|--yes)
                SKIP_CONFIRMATION=true
                # Don't pass to git lfs migrate
                ;;
            *)
                FILTERED_ARGS+=("$arg")
                ;;
        esac
    done

    if [ -z "$SUBCOMMAND" ]; then
        echo "ERROR: No subcommand specified (info/import/export)"
        echo ""
        echo "Usage: glms <subcommand> [options]"
        echo ""
        echo "Subcommands:"
        echo "  info      Show what would be migrated"
        echo "  import    Convert git objects to LFS"
        echo "  export    Convert LFS objects back to git"
        echo ""
        exit 1
    fi
}

# ============================================================================
# GITATTRIBUTES PARSING
# ============================================================================

extract_lfs_patterns() {
    local gitattributes_file
    gitattributes_file="$(git rev-parse --show-toplevel)/.gitattributes"

    if [ ! -f "$gitattributes_file" ]; then
        echo "ERROR: .gitattributes not found"
        echo ""
        echo "Cannot safely restrict migration without existing LFS tracking."
        echo "Please either:"
        echo "  1. Use 'git lfs track <pattern>' to track files first, OR"
        echo "  2. Use 'git lfs migrate' directly (without safety wrapper)"
        exit 1
    fi

    # Extract patterns with filter=lfs
    local patterns=()
    while IFS= read -r line; do
        # Skip comments and empty lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue

        # Check if line contains filter=lfs
        if echo "$line" | grep -q "filter=lfs"; then
            # Extract the pattern (first token before whitespace)
            pattern=$(echo "$line" | awk '{print $1}')
            patterns+=("$pattern")
        fi
    done < "$gitattributes_file"

    if [ ${#patterns[@]} -eq 0 ]; then
        echo "ERROR: No LFS patterns found in .gitattributes"
        echo ""
        echo "No files are tracked with filter=lfs."
        echo "Please either:"
        echo "  1. Use 'git lfs track <pattern>' to track files first, OR"
        echo "  2. Use 'git lfs migrate' directly (without safety wrapper)"
        exit 1
    fi

    # Return as newline-separated string for easy iteration
    printf '%s\n' "${patterns[@]}"
}

# ============================================================================
# USER CONFIRMATION
# ============================================================================

display_restrictions_and_confirm() {
    local gitattributes_patterns="$1"

    echo "==================================================================="
    echo "SAFETY RESTRICTION: git-lfs-migrate-safe"
    echo "==================================================================="
    echo ""
    echo "LFS patterns from .gitattributes:"
    echo "$gitattributes_patterns" | sed 's/^/  - /'
    echo ""

    if [ ${#USER_INCLUDES[@]} -gt 0 ]; then
        echo "User-provided patterns:"
        printf '  - %s\n' "${USER_INCLUDES[@]}"
        echo ""
    fi

    echo "Migration will be RESTRICTED to these combined patterns."
    echo ""
    echo "Subcommand: $SUBCOMMAND"
    if [ ${#FILTERED_ARGS[@]} -gt 0 ]; then
        echo "Additional args: ${FILTERED_ARGS[*]}"
    fi
    echo ""

    # Skip confirmation if -y/--yes provided
    if [ "$SKIP_CONFIRMATION" = true ]; then
        echo "Auto-confirming (--yes flag provided)"
        echo ""
        return 0
    fi

    # Ask for confirmation
    while true; do
        echo "Continue with restricted migration? (y/n)"
        read -r input
        echo ""

        case "$input" in
            y|Y|yes|Yes|YES)
                return 0
                ;;
            n|N|no|No|NO)
                echo "Migration aborted by user."
                exit 0
                ;;
            *)
                echo "Invalid option. Type 'y' for Yes or 'n' for No."
                echo ""
                ;;
        esac
    done
}

# ============================================================================
# MIGRATION EXECUTION
# ============================================================================

execute_restricted_migrate() {
    local gitattributes_patterns="$1"

    # Build --include arguments from .gitattributes patterns
    local include_args=()
    while IFS= read -r pattern; do
        [ -n "$pattern" ] && include_args+=("--include" "$pattern")
    done <<< "$gitattributes_patterns"

    # Add user-provided patterns
    for pattern in "${USER_INCLUDES[@]}"; do
        include_args+=("--include" "$pattern")
    done

    # Display command for transparency
    echo "Executing: git lfs migrate $SUBCOMMAND ${include_args[*]} ${FILTERED_ARGS[*]}"
    echo ""

    # Execute git lfs migrate
    git lfs migrate "$SUBCOMMAND" "${include_args[@]}" "${FILTERED_ARGS[@]}"
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    echo "git-lfs-migrate-safe: Safety wrapper for git lfs migrate"
    echo ""

    # Parse arguments
    parse_arguments "$@"

    # Extract LFS patterns from .gitattributes
    local lfs_patterns
    lfs_patterns=$(extract_lfs_patterns)

    # Display and confirm
    display_restrictions_and_confirm "$lfs_patterns"

    # Execute with restrictions
    execute_restricted_migrate "$lfs_patterns"

    echo ""
    echo "Migration completed successfully!"
}

main "$@"
