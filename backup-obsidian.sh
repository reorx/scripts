#!/bin/bash
#
# backup-obsidian.sh - Backup Obsidian vault to a ZIP archive
#
# This script creates a timestamped ZIP backup of an Obsidian vault,
# excluding version control files, cache, and temporary data.
#
# Usage:
#   ./backup-obsidian.sh
#
# Environment variables (configure these before running):
#   OBSIDIAN_VAULT_PATH     - Path to the Obsidian vault directory (required)
#   OBSIDIAN_BACKUP_DIR     - Primary backup destination directory (required)
#   OBSIDIAN_BACKUP_ALT_DIR - Secondary backup destination (optional, skipped if not set)
#

set -e  # Exit immediately if a command fails

# =============================================================================
# Help
# =============================================================================

show_help() {
    cat <<'EOF'
Usage: backup-obsidian.sh

Backup an Obsidian vault to a timestamped ZIP archive.

Environment Variables:
  OBSIDIAN_VAULT_PATH     Path to the Obsidian vault directory (required)
                          The vault's basename is used in the backup filename
  OBSIDIAN_BACKUP_DIR     Primary backup destination directory (required)
                          Backup is saved as "VaultName.zip" (overwrites previous)
  OBSIDIAN_BACKUP_ALT_DIR Secondary backup destination (optional)
                          If set, timestamped copy is also placed here
                          e.g., "MyVault-20240115120000.zip"

Example:
  export OBSIDIAN_VAULT_PATH="$HOME/Documents/MyVault"
  export OBSIDIAN_BACKUP_DIR="$HOME/OneDrive/Backups/Obsidian"
  ./backup-obsidian.sh
EOF
}

# Show error message followed by help, then exit
die_with_help() {
    echo "Error: $1" >&2
    echo "" >&2
    show_help >&2
    exit 1
}

# Handle -h/--help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    show_help
    exit 0
fi

# =============================================================================
# Configuration
# =============================================================================

# Path to the Obsidian vault to be backed up
OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-}"

# Primary destination directory for the backup
OBSIDIAN_BACKUP_DIR="${OBSIDIAN_BACKUP_DIR:-}"

# Optional secondary backup destination (e.g., another cloud service)
OBSIDIAN_BACKUP_ALT_DIR="${OBSIDIAN_BACKUP_ALT_DIR:-}"

# =============================================================================
# Validation
# =============================================================================

# Ensure required environment variables are set
[[ -z "$OBSIDIAN_VAULT_PATH" ]] && die_with_help "OBSIDIAN_VAULT_PATH is not set"
[[ -z "$OBSIDIAN_BACKUP_DIR" ]] && die_with_help "OBSIDIAN_BACKUP_DIR is not set"

# Verify the vault directory exists
[[ ! -d "$OBSIDIAN_VAULT_PATH" ]] && die_with_help "Vault directory does not exist: $OBSIDIAN_VAULT_PATH"

# Verify the primary backup directory exists
[[ ! -d "$OBSIDIAN_BACKUP_DIR" ]] && die_with_help "Backup directory does not exist: $OBSIDIAN_BACKUP_DIR"

# =============================================================================
# Backup Process
# =============================================================================

# Derive vault name from the path's basename
vault_name="$(basename "$OBSIDIAN_VAULT_PATH")"

# Timestamped filename (created by zip, used for alt backup)
filename="${vault_name}-$(date +%Y%m%d%H%M%S).zip"

# Base filename (for primary backup destination, overwrites previous)
filename_base="${vault_name}.zip"

# Change to vault directory so zip paths are relative
cd "$OBSIDIAN_VAULT_PATH"

echo "Creating backup of vault: $OBSIDIAN_VAULT_PATH"
echo "Backup filename: $filename"

# Create the ZIP archive with exclusions:
#   -r        : Recurse into directories
#   -v        : Verbose output
#   -x        : Exclude patterns
#
# Exclusions:
#   *.git*              : Git version control files and directories
#   .obsidian/cache/*   : Obsidian cache (regenerated automatically)
#   .obsidian/workspace.json       : Current workspace state (session-specific)
#   .obsidian/workspace-mobile.json: Mobile workspace state (session-specific)
#   .trash/*            : Obsidian's trash folder
zip "$filename" . -r -v \
    -x '*.git*' \
    -x '.obsidian/cache' \
    -x '.obsidian/workspace-*'

# Verify the zip file was created and is valid
if [[ ! -f "$filename" ]]; then
    echo "Error: Failed to create backup file" >&2
    exit 1
fi

# Test the integrity of the zip file
if ! zip -T "$filename" > /dev/null; then
    echo "Error: Backup file is corrupted" >&2
    rm -f "$filename"
    exit 1
fi

echo "Backup created successfully, verified integrity"

# =============================================================================
# Copy to Destinations
# =============================================================================

# Copy timestamped version to secondary backup location if configured and exists
if [[ -n "$OBSIDIAN_BACKUP_ALT_DIR" && -d "$OBSIDIAN_BACKUP_ALT_DIR" ]]; then
    echo "Copying timestamped backup to: $OBSIDIAN_BACKUP_ALT_DIR/$filename"
    cp "$filename" "$OBSIDIAN_BACKUP_ALT_DIR/"
fi

# Move to primary backup location with base name (overwrites existing)
echo "Moving to primary backup: $OBSIDIAN_BACKUP_DIR/$filename_base"
mv "$filename" "$OBSIDIAN_BACKUP_DIR/$filename_base"

# =============================================================================
# Summary
# =============================================================================

echo ""
echo "Backup complete:"
ls -lh "$OBSIDIAN_BACKUP_DIR/$filename_base"
