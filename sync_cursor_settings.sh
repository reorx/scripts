#!/bin/bash

# config
keybindings="$HOME/Library/Application Support/Cursor/User/keybindings.json"
settings="$HOME/Library/Application Support/Cursor/User/settings.json"
sync_root="$HOME/Library/CloudStorage/OneDrive-Personal/Backups/Cursor"

# functions
save_settings() {
  name=$(hostname)
  settings_dir="$sync_root/$name"
  mkdir -p "$settings_dir"

  echo "sync keybindings.."
  ls -l "$keybindings"
  cp "$keybindings" "$settings_dir"

  echo "sync settings.."
  ls -l "$settings"
  cp "$settings" "$settings_dir"

  echo "Settings saved to $settings_dir"
}

load_settings() {
  local source_name="$1"
  if [ -z "$source_name" ]; then
    echo "Error: Must specify a name to load settings from"
    ls -l "$sync_root"
    exit 1
  fi

  source_dir="$sync_root/$source_name"
  if [ ! -d "$source_dir" ]; then
    echo "Error: Settings directory for $source_name not found at $source_dir"
    exit 1
  fi

  echo "Loading keybindings from $source_name.."
  ls -l "$source_dir/keybindings.json"
  cp "$source_dir/keybindings.json" "$keybindings"

  echo "Loading settings from $source_name.."
  ls -l "$source_dir/settings.json"
  cp "$source_dir/settings.json" "$settings"

  echo "Settings loaded from $source_dir"
}

# main
case "$1" in
  save)
    save_settings
    ;;
  load)
    load_settings "$2"
    ;;
  *)
    echo "Usage: $0 {save|load <name>}"
    echo "  save: Copy settings from Application Support to sync dir"
    echo "  load <name>: Load settings of <name> from sync dir to Application Support"
    exit 1
    ;;
esac
