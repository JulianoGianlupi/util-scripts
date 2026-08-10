#!/usr/bin/env bash
# zotero_to_index.sh
# Converts a BetterBibTeX JSON export into a compact index JSON for Claude Code.
#
# Output schema (one object per paper, nulls omitted):
#   {
#     "citekey":   "authorTitleYear2024",   -- BBT citation key (great for @cite lookups)
#     "title":     "Full paper title",
#     "authors":   "Smith, Jones, …",       -- last names only, truncated at 5 + "et al."
#     "year":      "2024",
#     "doi":       "10.xxxx/...",
#     "doi_url":   "https://doi.org/10.xxxx/...",
#     "pmid":      "12345678",
#     "abstract":  "...",
#     "pdf":       "/abs/path/to/file.pdf"
#   }
#
# Usage:
#   zotero_to_index.sh <input_library.json> <output_index.json>
#
# Requirements: jq >= 1.6

set -euo pipefail

INPUT="${1:-$HOME/Zotero/library.json}"
OUTPUT="${2:-$HOME/Zotero/library_index.json}"
TMPFILE="$(mktemp /tmp/zotero_index_XXXXXX.json)"

# todo: add --arg flags if you want to pass the paths at runtime instead

cleanup() { rm -f "$TMPFILE"; }
trap cleanup EXIT

if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: Input file not found: $INPUT" >&2
  exit 1
fi

echo "[$(date -u +%FT%TZ)] Converting $INPUT → $OUTPUT" >&2

jq --arg INPUT "$INPUT" '
  # Only process real library items (not orphan attachments at top level).
  # Real items have a "key" field and an itemType that is not "attachment" or "note".
  [ .items[]
    | select(
        .key != null
        and .itemType != null
        and .itemType != "attachment"
        and .itemType != "note"
        and .itemType != "annotation"
      )
    | {
        # --- identity ---
        citekey: (.citationKey // null),
        title:   (.title // null),

        # --- authors: last names, max 5 then "et al." ---
        authors: (
          if (.creators // []) | length == 0 then null
          else
            (.creators // [])
            | map(select(.creatorType == "author"))
            | if length == 0 then
                # fall back to any creator if no explicit "author" role
                (. | map(.lastName // .name // "") | map(select(. != "")))
              else
                map(.lastName // .name // "") | map(select(. != ""))
              end
            | if length > 5 then
                (.[0:5] | join(", ")) + " et al."
              else
                join(", ")
              end
            | if . == "" then null else . end
          end
        ),

        # --- year extracted from date field (YYYY-...) ---
        year: (
          (.date // "") | capture("^(?<y>[0-9]{4})") | .y // null
        ),

        # --- identifiers ---
        doi:     (.DOI // null),
        doi_url: (if .DOI then "https://doi.org/\(.DOI)" else null end),
        pmid:    (.PMID // null),

        # --- abstract: collapse all whitespace/control chars to single space ---
        abstract: (
          if .abstractNote and (.abstractNote | length) > 0 then
            .abstractNote | gsub("[\\n\\r\\t|]"; " ") | gsub("  +"; " ") | ltrimstr(" ") | rtrimstr(" ")
          else null
          end
        ),

        # --- PDF: first attachment whose path ends in .pdf (case-insensitive) ---
        pdf: (
          (.attachments // [])
          | map(select(
              .path != null
              and (.path | ascii_downcase | endswith(".pdf"))
            ))
          | if length > 0 then .[0].path else null end
        )
      }

    # Drop entries with no useful identifying info at all
    | select(.title != null or .doi != null or .citekey != null)

    # Remove null fields to keep the output lean
    | with_entries(select(.value != null))
  ]
' "$INPUT" > "$TMPFILE"

# Atomic replace so Claude Code never reads a half-written file
mv "$TMPFILE" "$OUTPUT"

COUNT=$(jq length "$OUTPUT")
echo "[$(date -u +%FT%TZ)] Done. $COUNT items written to $OUTPUT" >&2
