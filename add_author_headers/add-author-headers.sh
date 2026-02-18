#!/usr/bin/env bash
# Wrapper script for add_author_headers.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/add_author_headers.py"

# Check if Python script exists
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    echo "Error: $PYTHON_SCRIPT not found" >&2
    exit 1
fi

# Execute Python script with all arguments
python "$PYTHON_SCRIPT" "$@"
