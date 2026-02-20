"""
Add author headers to source files based on git blame analysis.

This generic script analyzes source files using git blame to determine the primary
author (contributor of most substantive lines) and adds standardized comment headers.
"""

import argparse
import configparser
from datetime import datetime
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class AuthorInfo:
    """Represents author information for headers."""
    name: str
    email: Optional[str] = None
    note: Optional[str] = None

    def __str__(self) -> str:
        if self.email:
            return f"{self.name} <{self.email}>"
        return self.name


@dataclass
class FileAnalysis:
    """Results of analyzing a single file."""
    filepath: str
    authors: list[AuthorInfo]  # All significant authors
    line_count: int
    author_contributions: dict[str, int]  # email -> line count
    existing_header: bool
    error: Optional[str] = None


def find_git_root(start_path: str) -> Optional[str]:
    """
    Find git root by looking for .git directory.

    Args:
        start_path: Starting directory path

    Returns:
        Path to git root or None if not found
    """
    current = os.path.abspath(start_path)
    while current != os.path.dirname(current):  # Not at filesystem root
        if os.path.exists(os.path.join(current, '.git')):
            return current
        current = os.path.dirname(current)
    return None


def get_submodule_paths(repo_root: str) -> set[Path]:
    """
    Detect git submodules in the repository.

    Parses .gitmodules file to find all submodule paths.

    Args:
        repo_root: Root directory of the git repository

    Returns:
        Set of Path objects pointing to submodule directories
    """
    gitmodules_path = os.path.join(repo_root, '.gitmodules')

    # Return empty set if no submodules file exists
    if not os.path.exists(gitmodules_path):
        return set()

    submodule_paths: set[Path] = set()

    try:
        config = configparser.ConfigParser()
        config.read(gitmodules_path, encoding='utf-8')

        for section in config.sections():
            if section.startswith('submodule'):
                try:
                    relative_path = config.get(section, 'path')
                    # Convert to absolute Path object
                    absolute_path = Path(repo_root) / relative_path
                    submodule_paths.add(absolute_path.resolve())
                except (configparser.NoOptionError, ValueError):
                    # Skip malformed submodule entries
                    continue

    except Exception as e:
        # If .gitmodules is malformed, log warning and continue without filtering
        print(f"Warning: Could not parse .gitmodules: {e}", file=sys.stderr)
        return set()

    return submodule_paths


def load_yaml_config(yaml_path: str) -> tuple[dict[str, AuthorInfo], set[str]]:
    """
    Load a single YAML config file.

    Args:
        yaml_path: Path to authors.yaml file

    Returns:
        Tuple of (author_templates dict, bot_emails set)
    """
    if not os.path.exists(yaml_path):
        return {}, set()

    with open(yaml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

    # Parse authors
    templates = {}
    for email, info in config.get('authors', {}).items():
        templates[email] = AuthorInfo(
            name=info.get('name',
                          email.split('@')[0]), email=info.get('email'), note=info.get('note')
        )

    # Parse bots
    bots = set(config.get('bots', []))

    return templates, bots


def load_author_templates(script_dir: str, repo_root: str) -> tuple[dict[str, AuthorInfo], set[str]]:
    """
    Load author templates from YAML files.

    Loads both:
    1. Global config: script_dir/authors.yaml (user's personal config)
    2. Project config: repo_root/authors.yaml (project-specific overrides)

    Project config takes precedence over global config.

    Args:
        script_dir: Directory containing the script
        repo_root: Root of the git repository being processed

    Returns:
        Tuple of (merged author_templates dict, merged bot_emails set)
    """
    # Load global config (next to script)
    global_templates, global_bots = load_yaml_config(os.path.join(script_dir, "authors.yaml"))

    # Load project config (repo root)
    project_templates, project_bots = load_yaml_config(os.path.join(repo_root, "authors.yaml"))

    # Merge: project overrides global
    merged_templates = {**global_templates, **project_templates}
    merged_bots = global_bots | project_bots

    return merged_templates, merged_bots


def get_author_name_from_git(email: str, repo_root: str) -> str:
    """
    Extract author name from git log for given email.

    Args:
        email: Author email
        repo_root: Repository root directory

    Returns:
        Author name or email username as fallback
    """
    try:
        cmd = ["git", "log", "--author", email, "--format=%an", "-1"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', check=True, cwd=repo_root)
        name = result.stdout.strip()
        return name if name else email.split('@')[0]
    except:
        return email.split('@')[0]


def parse_git_blame(filepath: str, bot_emails: set[str]) -> tuple[dict[str, int], dict[str, int]]:
    """
    Parse git blame output to count substantive lines per author.

    Uses --line-porcelain format for robust parsing.
    Excludes: blank lines, comment-only lines, bot accounts.

    Args:
        filepath: Absolute path to file
        bot_emails: Set of bot email addresses to exclude

    Returns:
        Tuple of:
        - Dictionary mapping author email -> count of substantive lines
        - Dictionary mapping author email -> most recent commit timestamp (unix)

    Raises:
        subprocess.CalledProcessError: If git blame fails
    """
    # Run git blame with line-porcelain format
    cmd = ["git", "blame", "--line-porcelain", filepath]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding='utf-8', check=True, cwd=os.path.dirname(filepath)
    )

    author_lines: dict[str, int] = {}
    author_timestamps: dict[str, int] = {}
    current_author: Optional[str] = None
    current_timestamp: Optional[int] = None

    for line in result.stdout.splitlines():
        # Parse author email from porcelain format
        if line.startswith("author-mail <"):
            email = line[len("author-mail <"):-1]  # Remove < and >
            current_author = email

        elif line.startswith("author-time "):
            current_timestamp = int(line[len("author-time "):])

        elif line.startswith("\t"):
            # This is the actual code line
            code_line = line[1:]  # Remove leading tab

            # Skip if author is a bot
            if current_author in bot_emails:
                continue

            # Count only substantive lines (non-blank, non-comment-only)
            stripped = code_line.strip()
            if stripped and not stripped.startswith("#"):
                author_lines[current_author] = author_lines.get(current_author, 0) + 1
                # Track most recent timestamp per author
                if current_timestamp is not None:
                    if current_author not in author_timestamps or current_timestamp > author_timestamps[current_author]:
                        author_timestamps[current_author] = current_timestamp

    return author_lines, author_timestamps


def determine_authors(
    author_lines: dict[str, int],
    author_timestamps: dict[str, int],
    templates: dict[str, AuthorInfo],
    repo_root: str,
    author_filter: Optional[str] = None,
    strict_authors: bool = False
) -> tuple[list[AuthorInfo], bool]:
    """
    Select authors based on line contributions with filtering modes.

    Filtering modes:
    - Soft mode (strict_authors=False): Return ALL authors if ANY author matches filter.
      Used to add headers to files you contributed to while keeping all authors listed.
    - Hard mode (strict_authors=True): Only process files where matching author(s) have
      >50% of lines, and only return authors matching the filter.

    Logic:
    1. Sort authors by line count (descending)
    2. For each author, look up in template dictionary by email
    3. Substitute {year} in note with most recent commit year
    4. Apply filtering based on mode

    Args:
        author_lines: Email -> line count mapping from git blame
        author_timestamps: Email -> most recent commit timestamp (unix)
        templates: Email -> AuthorInfo mapping for normalization
        repo_root: Repository root for git queries
        author_filter: Optional substring to filter author names (case-insensitive)
        strict_authors: If True, use hard mode filtering (>50% + only matching authors)

    Returns:
        Tuple of:
        - List of AuthorInfo for authors to include in header
        - Boolean indicating if file should be processed (based on filter criteria)
    """
    if not author_lines:
        return [], False

    # Sort authors by line count descending
    sorted_emails = sorted(author_lines.keys(), key=lambda x: author_lines[x], reverse=True)
    total_lines = sum(author_lines.values())

    # Build full author list with AuthorInfo objects
    all_authors: list[AuthorInfo] = []
    matching_authors: list[AuthorInfo] = []
    matching_lines = 0

    for email in sorted_emails:
        # Get year from most recent commit timestamp
        year_str = ""
        if email in author_timestamps:
            year_str = str(datetime.fromtimestamp(author_timestamps[email]).year)

        # Look up in templates for normalized info
        if email in templates:
            template = templates[email]
            # Substitute {year} in note if present
            note = template.note
            if note and "{year}" in note and year_str:
                note = note.replace("{year}", year_str)
            author_info = AuthorInfo(name=template.name, email=template.email, note=note)
        else:
            # Fallback: create AuthorInfo from git data
            name = get_author_name_from_git(email, repo_root)
            author_info = AuthorInfo(name=name, email=email, note=None)

        all_authors.append(author_info)

        # Track which authors match the filter
        if author_filter and author_filter.lower() in author_info.name.lower():
            matching_authors.append(author_info)
            matching_lines += author_lines[email]

    # No filter: return all authors, process file
    if not author_filter:
        return all_authors, True

    # No matching authors found: don't process file
    if not matching_authors:
        return [], False

    if strict_authors:
        # Hard mode: only process if matching authors have >50% of lines
        # Only return matching authors
        if total_lines > 0 and (matching_lines / total_lines) > 0.5:
            return matching_authors, True
        else:
            return [], False
    else:
        # Soft mode: return ALL authors since at least one matches
        return all_authors, True


def generate_header(filepath: str, authors: list[AuthorInfo]) -> str:
    """
    Generate comment header for the file with all authors.

    Format:
        # File: filename.jl
        # Author: Name <email>
        # Note: optional note
        # Author: Name2 <email2>
        # Note: optional note2
        <blank line>

    Args:
        filepath: Path to file (used to extract filename)
        authors: List of AuthorInfo with name, email, optional note

    Returns:
        Multi-line string with header and trailing newline
    """
    filename = os.path.basename(filepath)
    lines = []

    for author in authors:
        lines.append(f"# Author: {author}")
        if author.note:
            lines.append(f"# {author.note}")

    # Add blank line after header
    lines.append("")

    return "\n".join(lines) + "\n"


def insert_header(filepath: str, header: str, dry_run: bool = True) -> bool:
    """
    Insert header at the very top of the file.

    Strategy:
    1. Read entire file content
    2. Prepend header to beginning
    3. Write back (if not dry_run)

    Args:
        filepath: Absolute path to file
        header: Generated header string
        dry_run: If True, don't actually modify file

    Returns:
        True if successful (or would be successful in dry_run)

    Raises:
        IOError: If file read/write fails
    """
    # Read existing content
    with open(filepath, 'r', encoding='utf-8') as f:
        original_content = f.read()

    # Create new content with header at top
    new_content = header + original_content

    # Write if not dry_run
    if not dry_run:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)

    return True


def analyze_file(
    filepath: str,
    templates: dict[str, AuthorInfo],
    bot_emails: set[str],
    repo_root: str,
    author_filter: Optional[str] = None,
    strict_authors: bool = False
) -> Optional[FileAnalysis]:
    """
    Analyze a single source file for authorship.

    Steps:
    1. Check if header already exists
    2. Run git blame to get author contributions
    3. Determine authors based on filter mode
    4. Create FileAnalysis result (or None if file should be skipped)

    Args:
        filepath: Absolute path to source file
        templates: Author template dictionary
        bot_emails: Set of bot email addresses to exclude
        repo_root: Repository root directory
        author_filter: Optional substring to filter author names
        strict_authors: If True, use hard mode filtering (>50% + only matching authors)

    Returns:
        FileAnalysis with results, or None if file should be skipped based on filter
    """
    try:
        # Check for existing header
        with open(filepath, 'r', encoding='utf-8') as f:
            first_lines = [f.readline() for _ in range(3)]

        existing_header = any(
            line.strip().startswith("# File:") or line.strip().startswith("# Author:") for line in first_lines
        )

        if existing_header:
            return FileAnalysis(
                filepath=filepath, authors=[], line_count=0, author_contributions={}, existing_header=True
            )

        # Get git blame data
        author_lines, author_timestamps = parse_git_blame(filepath, bot_emails)

        # Determine authors based on filter mode
        authors, should_process = determine_authors(
            author_lines, author_timestamps, templates, repo_root, author_filter, strict_authors
        )

        # Skip file if filter criteria not met
        if not should_process:
            return None

        return FileAnalysis(
            filepath=filepath,
            authors=authors,
            line_count=sum(author_lines.values()),
            author_contributions=author_lines,
            existing_header=False,
            error=None
        )

    except Exception as e:
        return FileAnalysis(
            filepath=filepath, authors=[], line_count=0, author_contributions={}, existing_header=False, error=str(e)
        )


def process_files(
    directory: str,
    extensions: list[str],
    script_dir: str,
    dry_run: bool = True,
    author_filter: Optional[str] = None,
    strict_authors: bool = False
) -> tuple[list[FileAnalysis], list[FileAnalysis], int]:
    """
    Process all source files with specified extensions in directory.

    Args:
        directory: Directory path to search
        extensions: List of file extensions to process (without dots)
        script_dir: Directory containing the script
        dry_run: Whether to actually modify files
        author_filter: Optional substring to filter author names
        strict_authors: If True, use hard mode filtering (>50% + only matching authors)

    Returns:
        Tuple of (successful_analyses, failed_analyses, skipped_by_filter_count)
    """
    successful: list[FileAnalysis] = []
    failed: list[FileAnalysis] = []
    skipped_by_filter = 0

    # Find git root
    repo_root = find_git_root(directory)
    if not repo_root:
        print(f"Warning: Not a git repository: {directory}", file=sys.stderr)
        repo_root = directory  # Fallback to directory itself

    # Load author templates from YAML
    templates, bot_emails = load_author_templates(script_dir, repo_root)

    # Get submodule paths to skip
    submodule_paths = get_submodule_paths(repo_root)

    # Discover all source files matching extensions (skip submodules)
    all_files: list[str] = []
    dir_path = Path(directory)
    if dir_path.exists() and dir_path.is_dir():
        for ext in extensions:
            pattern = f"*.{ext}"
            for p in dir_path.rglob(pattern):
                # Skip files within submodule directories
                p_resolved = p.resolve()
                if not any(submodule in p_resolved.parents for submodule in submodule_paths):
                    all_files.append(str(p))

    # Analyze each file
    for filepath in sorted(all_files):
        analysis = analyze_file(filepath, templates, bot_emails, repo_root, author_filter, strict_authors)

        # None means file was skipped due to filter criteria
        if analysis is None:
            skipped_by_filter += 1
            continue

        if analysis.error or (not analysis.authors and not analysis.existing_header):
            failed.append(analysis)
        else:
            successful.append(analysis)

    # Apply headers if not dry_run
    if not dry_run:
        for analysis in successful:
            if not analysis.existing_header and analysis.authors:
                header = generate_header(analysis.filepath, analysis.authors)
                insert_header(analysis.filepath, header, dry_run=False)

    return successful, failed, skipped_by_filter


def preview_changes(analyses: list[FileAnalysis], verbose: bool = False) -> None:
    """
    Display diff-style preview of headers to be added.

    Args:
        analyses: List of successful FileAnalysis results
        verbose: Show detailed per-file information
    """
    for analysis in analyses:
        if analysis.existing_header:
            if verbose:
                print(f"\nSKIP: {analysis.filepath}")
                print("      (already has header)")
            continue

        # Skip if no authors (defensive check)
        if not analysis.authors:
            continue

        print(f"\n{'='*70}")
        print(f"File: {analysis.filepath}")
        print(f"Authors: {len(analysis.authors)} ({analysis.line_count} substantive lines)")
        for author in analysis.authors:
            email = author.email or "unknown"
            lines = analysis.author_contributions.get(email, 0)
            print(f"  - {author.name} ({lines} lines)")

        # Show header preview
        header = generate_header(analysis.filepath, analysis.authors)
        print("\nHeader to add:")
        for line in header.splitlines():
            print(f"  + {line}" if line else "  +")

        # Show first few lines of file
        if verbose:
            try:
                with open(analysis.filepath, 'r', encoding='utf-8') as f:
                    first_lines = [f.readline().rstrip() for _ in range(3)]
                print("\nExisting content preview:")
                for line in first_lines:
                    print(f"    {line}")
            except Exception:
                pass


def count_extensions(analyses: list[FileAnalysis]) -> dict[str, int]:
    """Count file extensions in analysis list."""
    extension_counts: dict[str, int] = {}
    for analysis in analyses:
        ext = os.path.splitext(analysis.filepath)[1].lstrip('.')
        extension_counts[ext] = extension_counts.get(ext, 0) + 1
    return extension_counts


def print_with_breakdown(label: str, analyses: list[FileAnalysis]) -> None:
    """Print count with file type breakdown."""
    print(f"{label}: {len(analyses)}")
    if analyses:
        ext_counts = count_extensions(analyses)
        for ext in sorted(ext_counts.keys(), key=lambda x: (-ext_counts[x], x)):
            print(f"- {ext}: {ext_counts[ext]}")


def main() -> int:
    """
    Main entry point with argument parsing.

    Returns:
        Exit code: 0 success, 1 failure
    """
    parser = argparse.ArgumentParser(description="Add author headers to source files based on git blame")
    parser.add_argument(
        'directory', nargs='?', default='.', help='Directory to traverse for source files (default: current directory)'
    )
    parser.add_argument(
        '--extensions',
        type=str,
        nargs='+',
        default=['py', 'jl', 'java', 'cpp', 'c'],
        help='File extensions to process without dots (default: py jl java cpp c)'
    )
    parser.add_argument("--apply", action="store_true", help="Actually modify files (default is dry-run preview)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed per-file analysis")
    parser.add_argument(
        "--authors",
        type=str,
        help=
        "Filter by author name (case-insensitive). Soft mode: process files where author has ANY contribution, include ALL authors in header"
    )
    parser.add_argument(
        "--strict-authors",
        action="store_true",
        dest="strict_authors",
        help=
        "Hard mode: only process files where matching author(s) have >50%% contribution, only include matching authors in header"
    )

    args = parser.parse_args()

    # Validate directory exists
    directory = os.path.abspath(args.directory)
    if not os.path.isdir(directory):
        print(f"Error: Directory not found: {directory}", file=sys.stderr)
        return 1

    # Get script directory for YAML loading
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Run analysis
    print(f"{'='*70}")
    print(f"Mode: {'APPLY CHANGES' if args.apply else 'DRY RUN (preview only)'}")
    print(f"Directory: {directory}")
    print(f"Extensions: {', '.join(args.extensions)}")
    if args.authors:
        filter_mode = "strict (>50% contribution, matching authors only)" if args.strict_authors else "soft (any contribution, all authors)"
        print(f"Author filter: {args.authors} ({filter_mode})")
    print(f"{'='*70}\n")

    successful, failed, skipped_by_filter = process_files(
        directory,
        args.extensions,
        script_dir,
        dry_run=not args.apply,
        author_filter=args.authors,
        strict_authors=args.strict_authors
    )

    # Display results
    preview_changes(successful, verbose=args.verbose)

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")

    # Files analyzed
    all_analyses = successful + failed
    print_with_breakdown("Files analyzed", all_analyses)

    # Headers to add
    to_add = [a for a in successful if not a.existing_header]
    print_with_breakdown("Headers to add", to_add)

    # Already has header
    has_header = [a for a in successful if a.existing_header]
    print_with_breakdown("Already has header", has_header)

    # Skipped by author filter
    if skipped_by_filter > 0:
        print(f"Skipped by author filter: {skipped_by_filter}")

    # Failed/skipped
    print_with_breakdown("Failed/skipped", failed)

    if failed and args.verbose:
        print("\nFailed files:")
        for analysis in failed:
            print(f"  {analysis.filepath}: {analysis.error}")

    if not args.apply:
        print("\n" + "=" * 70)
        print("This was a DRY RUN. Use --apply to actually modify files.")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("Changes applied successfully!")
        print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
