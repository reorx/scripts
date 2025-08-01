#!/usr/bin/env python3

import os
import subprocess
import shutil
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Union, Tuple
from enum import Enum


# ANSI color codes for text colors and formatting
class Colors:
    RED = '\033[31m'
    GREEN = '\033[32m'
    ORANGE = '\033[33m'
    BLUE = '\033[34m'
    CYAN = '\033[36m'
    PURPLE = '\033[35m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'


class Options:
    items_per_line = 3
    tab = 1


class SyncStatus(Enum):
    SYNC = "sync"
    OUT_OF_SYNC = "out-of-sync"


class WorkingDirStatus(Enum):
    CLEAN = "clean"
    UNTRACKED = "untracked"
    DIRTY = "dirty"


# Ordered status combinations with their priority emojis
STATUS_PRIORITY_ORDER = OrderedDict([
    # Highest priority (most dangerous) first
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.DIRTY), "❗"),      # Most dangerous
    ((SyncStatus.SYNC, WorkingDirStatus.DIRTY), "⚠️"),             # Medium priority
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.CLEAN), "⚠️"),      # Medium priority
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.UNTRACKED), "⚠️"),  # Medium priority
    ((SyncStatus.SYNC, WorkingDirStatus.UNTRACKED), "✅"),         # Safe
    ((SyncStatus.SYNC, WorkingDirStatus.CLEAN), "✅"),             # Safest
])


def get_node_type(name: str) -> str:
    path = Path(name)
    if path.is_dir():
        return 'dir'
    elif path.is_file():
        return 'file'
    else:
        raise TypeError(f'Unknown file type: {name}, {path.stat()}')


@contextmanager
def cdctx(path: str):
    old_cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


class GitDir:
    def __init__(self, name: str):
        self.name = name
        self.sync_status: Optional[SyncStatus] = None
        self.working_dir_status: Optional[WorkingDirStatus] = None

    def analyze_status(self) -> None:
        with cdctx(self.name):
            if not Path('.git').exists():
                raise ValueError(f'{self.name} is not a git repository')
            
            self._check_sync_status()
            self._check_working_dir_status()

    def _check_sync_status(self) -> None:
        try:
            # Check if we have a tracking remote
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                # No tracking remote, consider it sync
                self.sync_status = SyncStatus.SYNC
                return
            
            # Check if local is ahead or behind remote
            result = subprocess.run(
                ['git', 'rev-list', '--left-right', '--count', 'HEAD...@{u}'],
                capture_output=True,
                text=True,
                check=True
            )
            
            ahead, behind = map(int, result.stdout.strip().split())
            if ahead == 0 and behind == 0:
                self.sync_status = SyncStatus.SYNC
            else:
                self.sync_status = SyncStatus.OUT_OF_SYNC
                
        except subprocess.CalledProcessError:
            # If any git command fails, consider it out of sync
            self.sync_status = SyncStatus.OUT_OF_SYNC

    def _check_working_dir_status(self) -> None:
        try:
            # Check for uncommitted changes and conflicts
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                check=True
            )
            
            status_lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            # Check for merge/rebase in progress
            if (Path('.git/MERGE_HEAD').exists() or 
                Path('.git/rebase-merge').exists() or 
                Path('.git/rebase-apply').exists()):
                self.working_dir_status = WorkingDirStatus.DIRTY
                return
            
            if not status_lines:
                self.working_dir_status = WorkingDirStatus.CLEAN
                return
            
            has_uncommitted = False
            has_untracked = False
            
            for line in status_lines:
                if line.startswith('??'):
                    has_untracked = True
                else:
                    has_uncommitted = True
            
            if has_uncommitted:
                self.working_dir_status = WorkingDirStatus.DIRTY
            elif has_untracked:
                self.working_dir_status = WorkingDirStatus.UNTRACKED
            else:
                self.working_dir_status = WorkingDirStatus.CLEAN
                
        except subprocess.CalledProcessError:
            self.working_dir_status = WorkingDirStatus.DIRTY

    def __str__(self) -> str:
        sync = self.sync_status.value if self.sync_status else 'unknown'
        working = self.working_dir_status.value if self.working_dir_status else 'unknown'
        return f'<GitDir {self.name}, {sync}, {working}>'


class RegularDir:
    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return f'<RegularDir {self.name}>'


def list_dirs() -> Tuple[List[GitDir], List[RegularDir]]:
    git_dirs = []
    regular_dirs = []
    
    try:
        for item in os.listdir('.'):
            if item.strip() and Path(item).is_dir():
                if Path(item, '.git').exists():
                    git_dir = GitDir(item)
                    git_dir.analyze_status()
                    git_dirs.append(git_dir)
                else:
                    regular_dirs.append(RegularDir(item))
    except OSError:
        pass
    
    return git_dirs, regular_dirs


def echo(s: str, indent: Optional[int] = None, prefix: Optional[str] = None) -> None:
    if prefix:
        s = prefix + s
    if indent:
        s = ' ' * indent + s
    print(s)


def get_status_colors(sync_status: SyncStatus, working_status: WorkingDirStatus) -> Tuple[str, str]:
    """Get text colors with underline for sync and working dir status."""
    # Sync status colors
    if sync_status == SyncStatus.SYNC:
        sync_color = f"{Colors.UNDERLINE}{Colors.GREEN}"
    else:  # OUT_OF_SYNC
        sync_color = f"{Colors.UNDERLINE}{Colors.RED}"
    
    # Working dir status colors
    if working_status == WorkingDirStatus.CLEAN:
        working_color = f"{Colors.UNDERLINE}{Colors.CYAN}"
    elif working_status == WorkingDirStatus.UNTRACKED:
        working_color = f"{Colors.UNDERLINE}{Colors.BLUE}"
    else:  # DIRTY
        working_color = f"{Colors.UNDERLINE}{Colors.PURPLE}"
    
    return sync_color, working_color


def get_priority_emoji(sync_status: Optional[SyncStatus], working_status: Optional[WorkingDirStatus]) -> str:
    """Get priority emoji based on sync and working dir status combination."""
    if sync_status is None or working_status is None:
        return "📁"  # For regular directories
    
    # Look up emoji from the OrderedDict
    key = (sync_status, working_status)
    return STATUS_PRIORITY_ORDER.get(key, "❓")  # Default fallback


def echo_dirs(dirs: List[Union[GitDir, RegularDir]], indent: Optional[int] = None, prefix: str = '│') -> None:
    if not dirs:
        return
    
    # Get terminal width and calculate available space
    terminal_width = shutil.get_terminal_size().columns
    indent_space = indent or 0
    prefix_space = len(prefix) + 1  # +1 for space after prefix
    available_width = terminal_width - indent_space - prefix_space
    
    # Find the longest directory name
    max_name_len = max(len(dir_obj.name) for dir_obj in dirs)
    
    # Calculate how many columns we can fit
    padding = 2
    column_width = max_name_len + padding
    num_columns = max(1, available_width // column_width)
    
    # Group directories into lines
    lines = []
    line_buf = []
    
    for dir_obj in dirs:
        line_buf.append(dir_obj.name)
        
        if len(line_buf) >= num_columns:
            lines.append(line_buf)
            line_buf = []
    
    if line_buf:
        lines.append(line_buf)
    
    # Display the lines
    for line in lines:
        # Create format string for this line
        line_parts = []
        for i, name in enumerate(line):
            if i == len(line) - 1:  # Last item in line, no padding needed
                line_parts.append(name)
            else:
                line_parts.append(name.ljust(column_width))
        
        line_str = ''.join(line_parts)
        echo(line_str, indent, prefix + ' ')


def main() -> None:
    options = Options()
    echo(f'cwd: {os.getcwd()}')
    echo('Scanning..\n')
    
    git_dirs, regular_dirs = list_dirs()
    
    # Group git dirs by sync and working dir status
    groups: Dict[Tuple[SyncStatus, WorkingDirStatus], List[GitDir]] = {}
    
    for git_dir in git_dirs:
        key = (git_dir.sync_status, git_dir.working_dir_status)
        if key not in groups:
            groups[key] = []
        groups[key].append(git_dir)
    
    tab = options.tab
    
    # Show git directories grouped by status using OrderedDict
    for (sync_status, working_status), emoji in STATUS_PRIORITY_ORDER.items():
        key = (sync_status, working_status)
        if key in groups:
            dirs = groups[key]
            sync_color, working_color = get_status_colors(sync_status, working_status)
            
            # Create colored and underlined status names
            sync_text = f'{sync_color}{sync_status.value.title()}{Colors.RESET}'
            working_text = f'{working_color}{working_status.value.title()}{Colors.RESET}'
            
            echo(f'{emoji} {sync_text} + {working_text} ({len(dirs)}):')
            echo_dirs(dirs, tab)
            echo('')
    
    # Show regular directories at the bottom as special group
    if regular_dirs:
        emoji = get_priority_emoji(None, None)
        echo(f'{emoji} Non-Git Directories ({len(regular_dirs)}):')
        echo_dirs(regular_dirs, tab)
        echo('')


if __name__ == '__main__':
    main()
