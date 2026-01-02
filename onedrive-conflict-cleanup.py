#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
OneDrive Conflict Files Cleanup Script

Detects and cleans up OneDrive sync conflict files in a folder.
Conflict files have pattern: {original_basename}-{device_name}[-{number}].{ext}

Usage:
    uv run onedrive-conflict-cleanup.py /path/to/folder -d "Device1" -d "Device2"
    uv run onedrive-conflict-cleanup.py /path/to/folder -d "Maiev" -d "Xiao's Mac mini" --delete
    uv run onedrive-conflict-cleanup.py /path/to/folder -d "Maiev" -v  # verbose output
"""

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# List of known device name patterns (can be extended via CLI)
DEFAULT_DEVICE_PATTERNS: list[str] = []


@dataclass
class ConflictFile:
    path: Path
    original: Path
    device_name: str
    size: int
    mtime: float
    original_size: int
    original_mtime: float

    @property
    def is_json(self) -> bool:
        return self.path.suffix.lower() == ".json"

    @property
    def is_safe_to_delete(self) -> bool:
        # JSON files are always safe to delete (config/state files)
        if self.is_json:
            return True
        # Only size matters - if conflict is smaller or equal, it's safe to delete
        return self.size <= self.original_size

    @property
    def reason_unsafe(self) -> str:
        if self.size > self.original_size:
            return "larger"
        return ""


def format_size(size: int) -> str:
    """Format file size in human-readable form."""
    if size < 1024:
        return f"{size} bytes"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}k"
    else:
        return f"{size / (1024 * 1024):.1f}M"


def format_time(mtime: float) -> str:
    """Format mtime as date string."""
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def find_original(filepath: Path, device_patterns: list[str]) -> tuple[Path, str] | None:
    """
    Check if this file is a conflict file.
    Returns (original_path, device_name) if this is a conflict file, None otherwise.

    OneDrive conflict pattern: {name}-{device_name}.ext or {name}-{device_name}-{n}.ext
    Only matches if the suffix matches one of the known device patterns.
    """
    stem = filepath.stem
    ext = filepath.suffix
    if not ext:  # skip extensionless files
        return None

    for device in device_patterns:
        # Escape special regex chars in device name
        escaped_device = re.escape(device)

        # Pattern 1: name-device-number (e.g., "file-Xiao's Mac mini-2")
        pattern1 = rf"^(.+)-({escaped_device})-(\d+)$"
        match = re.match(pattern1, stem)
        if match:
            base = match.group(1)
            original = filepath.parent / f"{base}{ext}"
            if original.exists() and original != filepath:
                return (original, device)

        # Pattern 2: name-device (e.g., "file-Xiao's Mac mini")
        pattern2 = rf"^(.+)-({escaped_device})$"
        match = re.match(pattern2, stem)
        if match:
            base = match.group(1)
            original = filepath.parent / f"{base}{ext}"
            if original.exists() and original != filepath:
                return (original, device)

    return None


def scan_folder(folder: Path, device_patterns: list[str]) -> list[ConflictFile]:
    """Recursively scan folder for conflict files."""
    conflicts = []

    for root, _dirs, files in os.walk(folder):
        root_path = Path(root)
        for filename in files:
            filepath = root_path / filename
            result = find_original(filepath, device_patterns)
            if result:
                original, device_name = result
                stat = filepath.stat()
                orig_stat = original.stat()
                conflicts.append(
                    ConflictFile(
                        path=filepath,
                        original=original,
                        device_name=device_name,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        original_size=orig_stat.st_size,
                        original_mtime=orig_stat.st_mtime,
                    )
                )

    return conflicts


def print_conflict(conflict: ConflictFile, verbose: bool, dry_run: bool) -> None:
    """Print info about a conflict file."""
    tag = "[SAFE]" if conflict.is_safe_to_delete else "[REVIEW]"

    if verbose:
        print(f"{tag} {conflict.path}")
        print(f"  -> Original: {conflict.original}")
        size_note = ""
        if conflict.size > conflict.original_size:
            size_note = " <- LARGER"
        print(
            f"  -> Size: {format_size(conflict.size)} (original: {format_size(conflict.original_size)}){size_note}"
        )
        mtime_note = ""
        if conflict.mtime > conflict.original_mtime:
            mtime_note = " <- NEWER"
        print(
            f"  -> Modified: {format_time(conflict.mtime)} (original: {format_time(conflict.original_mtime)}){mtime_note}"
        )
        if conflict.is_safe_to_delete:
            action = "WOULD DELETE" if dry_run else "DELETE"
        else:
            action = "SKIP (needs manual review)"
        print(f"  -> Action: {action}")
        print()
    else:
        # Compact one-line output
        if conflict.is_safe_to_delete:
            action = "WOULD DELETE" if dry_run else "DELETE"
            print(f"{tag} {conflict.path} -> {action}")
        else:
            print(f"{tag} {conflict.path} -> SKIP ({conflict.reason_unsafe})")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up OneDrive sync conflict files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/folder -d "Maiev" -d "Xiao's Mac mini"
  %(prog)s /path/to/folder -d "Maiev" --delete
  %(prog)s /path/to/folder -d "Device Name" -v
        """,
    )
    parser.add_argument("folder", type=Path, help="Folder to scan for conflict files")
    parser.add_argument(
        "-d",
        "--device",
        action="append",
        dest="devices",
        metavar="NAME",
        help="Device name pattern to match (can be specified multiple times)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete safe conflict files (default: dry-run)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed info per file"
    )
    args = parser.parse_args()

    # Validate device patterns
    device_patterns = args.devices or DEFAULT_DEVICE_PATTERNS
    if not device_patterns:
        parser.error("At least one device pattern is required. Use -d/--device to specify.")

    dry_run = not args.delete
    folder = args.folder.resolve()

    if not folder.exists():
        print(f"Error: Folder does not exist: {folder}")
        return 1

    if not folder.is_dir():
        print(f"Error: Not a directory: {folder}")
        return 1

    print(f"Scanning: {folder}")
    print(f"Device patterns: {', '.join(device_patterns)}")
    if dry_run:
        print("Mode: DRY-RUN (use --delete to actually delete files)")
    else:
        print("Mode: DELETE")
    print()

    conflicts = scan_folder(folder, device_patterns)

    if not conflicts:
        print("No conflict files found.")
        return 0

    # Collect stats
    device_names: set[str] = set()
    safe_count = 0
    review_count = 0
    deleted_count = 0
    review_files: list[Path] = []

    for conflict in conflicts:
        device_names.add(conflict.device_name)
        print_conflict(conflict, args.verbose, dry_run)

        if conflict.is_safe_to_delete:
            safe_count += 1
            if not dry_run:
                try:
                    # Use macOS trash command to move to Trash instead of permanent delete
                    subprocess.run(
                        ["trash", str(conflict.path)],
                        check=True,
                        capture_output=True,
                    )
                    deleted_count += 1
                except subprocess.CalledProcessError as e:
                    print(f"  Error trashing: {e.stderr.decode() if e.stderr else e}")
                except FileNotFoundError:
                    print("  Error: 'trash' command not found. Install with: brew install trash")
        else:
            review_count += 1
            review_files.append(conflict.path)

    # Print summary
    print("=" * 50)
    print("Summary")
    print("=" * 50)
    print(f"Detected device names: {', '.join(sorted(device_names))}")
    print(f"Safe to delete: {safe_count} files")
    if dry_run:
        print("Trashed: 0 (dry-run mode)")
    else:
        print(f"Trashed: {deleted_count} files")
    print(f"Needs review: {review_count} files")
    if review_files:
        for f in review_files:
            print(f"  - {f}")

    return 0


if __name__ == "__main__":
    exit(main())
