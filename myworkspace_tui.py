#!/usr/bin/env python3
#
# /// script
# requires-python = ">=3.9"
# dependencies = ["rich>=13.0.0"]
# ///

import os
import subprocess
import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from enum import Enum
from typing import Optional, List, Dict, Tuple

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.columns import Columns
from rich import box
from rich.align import Align


class SyncStatus(Enum):
    SYNC = "sync"
    OUT_OF_SYNC = "out-of-sync"


class WorkingDirStatus(Enum):
    CLEAN = "clean"
    UNTRACKED = "untracked"
    DIRTY = "dirty"


# Ordered status combinations with their priority emojis
STATUS_PRIORITY_ORDER = OrderedDict([
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.DIRTY), "❗"),
    ((SyncStatus.SYNC, WorkingDirStatus.DIRTY), "⚠️"),
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.CLEAN), "⚠️"),
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.UNTRACKED), "⚠️"),
    ((SyncStatus.SYNC, WorkingDirStatus.UNTRACKED), "✅"),
    ((SyncStatus.SYNC, WorkingDirStatus.CLEAN), "✅"),
])


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
        self.detailed_status: str = ""
        self.ahead_behind: Tuple[int, int] = (0, 0)

    def analyze_status(self) -> None:
        with cdctx(self.name):
            if not Path('.git').exists():
                raise ValueError(f'{self.name} is not a git repository')

            self._check_sync_status()
            self._check_working_dir_status()
            self._get_detailed_status()

    def _check_sync_status(self) -> None:
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                self.sync_status = SyncStatus.SYNC
                return

            result = subprocess.run(
                ['git', 'rev-list', '--left-right', '--count', 'HEAD...@{u}'],
                capture_output=True,
                text=True,
                check=True
            )

            ahead, behind = map(int, result.stdout.strip().split())
            self.ahead_behind = (ahead, behind)
            
            if ahead == 0 and behind == 0:
                self.sync_status = SyncStatus.SYNC
            else:
                self.sync_status = SyncStatus.OUT_OF_SYNC

        except subprocess.CalledProcessError:
            self.sync_status = SyncStatus.OUT_OF_SYNC

    def _check_working_dir_status(self) -> None:
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                check=True
            )

            status_lines = result.stdout.strip().split('\n') if result.stdout.strip() else []

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

    def _get_detailed_status(self) -> None:
        try:
            result = subprocess.run(
                ['git', 'status', '--short', '--branch'],
                capture_output=True,
                text=True,
                check=True
            )
            self.detailed_status = result.stdout.strip()
        except subprocess.CalledProcessError:
            self.detailed_status = "Error getting git status"

    async def git_pull(self) -> str:
        try:
            with cdctx(self.name):
                result = subprocess.run(
                    ['git', 'pull'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                await asyncio.sleep(0.1)  # Small delay for UI responsiveness
                return result.stdout + result.stderr
        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr}"

    async def git_push(self) -> str:
        try:
            with cdctx(self.name):
                result = subprocess.run(
                    ['git', 'push'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                await asyncio.sleep(0.1)
                return result.stdout + result.stderr
        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr}"

    async def git_fetch(self) -> str:
        try:
            with cdctx(self.name):
                result = subprocess.run(
                    ['git', 'fetch'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                await asyncio.sleep(0.1)
                return result.stdout + result.stderr
        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr}"


class RegularDir:
    def __init__(self, name: str):
        self.name = name


class MyWorkspaceTUI:
    def __init__(self):
        self.console = Console()
        self.current_dir = os.getcwd()
        self.git_dirs: List[GitDir] = []
        self.regular_dirs: List[RegularDir] = []
        self.selected_group = 0
        self.selected_item = 0
        self.current_view = "main"  # "main" or "detail"
        self.selected_dir: Optional[GitDir] = None
        self.groups: Dict[Tuple, List[GitDir]] = {}
        self.group_list = []
        self.operation_result = ""

    def scan_directories(self):
        self.git_dirs = []
        self.regular_dirs = []

        try:
            for item in os.listdir('.'):
                if item.strip() and Path(item).is_dir():
                    if Path(item, '.git').exists():
                        git_dir = GitDir(item)
                        git_dir.analyze_status()
                        self.git_dirs.append(git_dir)
                    else:
                        self.regular_dirs.append(RegularDir(item))
        except OSError:
            pass

        # Group git dirs by status
        self.groups = {}
        for git_dir in self.git_dirs:
            key = (git_dir.sync_status, git_dir.working_dir_status)
            if key not in self.groups:
                self.groups[key] = []
            self.groups[key].append(git_dir)

        # Create ordered group list
        self.group_list = []
        for (sync_status, working_status), emoji in STATUS_PRIORITY_ORDER.items():
            key = (sync_status, working_status)
            if key in self.groups:
                self.group_list.append((key, emoji, self.groups[key]))

        if self.regular_dirs:
            self.group_list.append((None, "📁", self.regular_dirs))

    def get_main_view(self) -> Panel:
        if not self.group_list:
            return Panel("No directories found", title="MyWorkspace TUI")

        table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
        table.add_column("Status", style="bold")
        table.add_column("Directories")

        for i, (key, emoji, dirs) in enumerate(self.group_list):
            if key:
                sync_status, working_status = key
                status_text = f"{emoji} {sync_status.value.title()} + {working_status.value.title()} ({len(dirs)})"
                
                if sync_status == SyncStatus.SYNC:
                    sync_color = "green"
                else:
                    sync_color = "red"
                    
                if working_status == WorkingDirStatus.CLEAN:
                    working_color = "cyan"
                elif working_status == WorkingDirStatus.UNTRACKED:
                    working_color = "blue"
                else:
                    working_color = "magenta"
            else:
                status_text = f"{emoji} Non-Git Directories ({len(dirs)})"
                sync_color = working_color = "white"

            # Highlight selected group
            if i == self.selected_group:
                status_text = f"[reverse]{status_text}[/reverse]"

            # Create directory list
            dir_names = []
            for j, dir_obj in enumerate(dirs):
                name = dir_obj.name
                if i == self.selected_group and j == self.selected_item:
                    name = f"[reverse]{name}[/reverse]"
                dir_names.append(name)

            dir_text = "  ".join(dir_names)
            table.add_row(status_text, dir_text)

        help_text = "\n[dim]Navigate: ↑/↓ (groups), ←/→ (items), Enter (details), q (quit), r (refresh)[/dim]"
        
        from rich.console import Group
        return Panel(
            Group(table, Text(help_text)),
            title=f"MyWorkspace TUI - {self.current_dir}",
            border_style="blue"
        )

    def get_detail_view(self) -> Panel:
        if not self.selected_dir:
            return Panel("No directory selected", title="Directory Details")

        # Git status
        status_table = Table(box=box.ROUNDED, title="Git Status")
        status_table.add_column("Property", style="bold")
        status_table.add_column("Value")

        status_table.add_row("Directory", self.selected_dir.name)
        status_table.add_row("Sync Status", self.selected_dir.sync_status.value if self.selected_dir.sync_status else "unknown")
        status_table.add_row("Working Dir", self.selected_dir.working_dir_status.value if self.selected_dir.working_dir_status else "unknown")
        
        if self.selected_dir.ahead_behind != (0, 0):
            ahead, behind = self.selected_dir.ahead_behind
            status_table.add_row("Ahead/Behind", f"{ahead}/{behind}")

        # Git operations
        ops_table = Table(box=box.ROUNDED, title="Git Operations")
        ops_table.add_column("Key", style="bold")
        ops_table.add_column("Operation")
        
        ops_table.add_row("p", "Pull")
        ops_table.add_row("P", "Push") 
        ops_table.add_row("f", "Fetch")

        # Detailed status
        status_panel = Panel(
            self.selected_dir.detailed_status or "No detailed status available",
            title="Detailed Status",
            border_style="green"
        )

        # Operation result
        result_panel = ""
        if self.operation_result:
            result_panel = Panel(
                self.operation_result,
                title="Operation Result",
                border_style="yellow"
            )

        help_text = "\n[dim]Operations: p (pull), P (push), f (fetch), Esc (back), r (refresh)[/dim]"

        from rich.console import Group
        content = Columns([status_table, ops_table])
        
        if result_panel:
            main_content = Group(content, status_panel, result_panel, Text(help_text))
        else:
            main_content = Group(content, status_panel, Text(help_text))

        return Panel(
            main_content,
            title=f"Directory Details - {self.selected_dir.name}",
            border_style="blue"
        )

    async def handle_git_operation(self, operation: str):
        if not self.selected_dir:
            return

        self.operation_result = f"Running git {operation}..."
        
        if operation == "pull":
            result = await self.selected_dir.git_pull()
        elif operation == "push":
            result = await self.selected_dir.git_push()
        elif operation == "fetch":
            result = await self.selected_dir.git_fetch()
        else:
            result = f"Unknown operation: {operation}"

        self.operation_result = result
        # Refresh directory status after operation
        self.selected_dir.analyze_status()

    def handle_input(self, key: str) -> bool:
        if key == 'q':
            return False
        elif key == 'r':
            self.scan_directories()
            self.operation_result = ""
        elif self.current_view == "main":
            return self.handle_main_input(key)
        elif self.current_view == "detail":
            return self.handle_detail_input(key)
        return True

    def handle_main_input(self, key: str) -> bool:
        if key == 'up':
            self.selected_group = max(0, self.selected_group - 1)
            self.selected_item = 0
        elif key == 'down':
            self.selected_group = min(len(self.group_list) - 1, self.selected_group + 1)
            self.selected_item = 0
        elif key == 'left' and self.group_list:
            current_group = self.group_list[self.selected_group][2]
            self.selected_item = max(0, self.selected_item - 1)
        elif key == 'right' and self.group_list:
            current_group = self.group_list[self.selected_group][2]
            self.selected_item = min(len(current_group) - 1, self.selected_item + 1)
        elif key == 'enter' and self.group_list:
            current_group = self.group_list[self.selected_group][2]
            if self.selected_item < len(current_group):
                selected_item = current_group[self.selected_item]
                if isinstance(selected_item, GitDir):
                    self.selected_dir = selected_item
                    self.current_view = "detail"
                    self.operation_result = ""
        return True

    def handle_detail_input(self, key: str) -> bool:
        if key == 'escape':
            self.current_view = "main"
            self.operation_result = ""
        elif key == 'p':
            asyncio.create_task(self.handle_git_operation("pull"))
        elif key == 'P':
            asyncio.create_task(self.handle_git_operation("push"))
        elif key == 'f':
            asyncio.create_task(self.handle_git_operation("fetch"))
        return True

    def get_current_view(self) -> Panel:
        if self.current_view == "main":
            return self.get_main_view()
        else:
            return self.get_detail_view()

    async def run(self):
        self.scan_directories()

        # Simple interactive mode using input prompts
        while True:
            self.console.clear()
            self.console.print(self.get_current_view())
            
            if self.current_view == "main":
                self.console.print("\n[dim]Commands: j/k (up/down groups), h/l (left/right items), enter (details), r (refresh), q (quit)[/dim]")
            else:
                self.console.print("\n[dim]Commands: p (pull), P (push), f (fetch), b (back), r (refresh), q (quit)[/dim]")
            
            try:
                cmd = input("\nCommand: ").strip().lower()
                
                if cmd == 'q':
                    break
                elif cmd == 'r':
                    self.scan_directories()
                    self.operation_result = ""
                elif self.current_view == "main":
                    if not self.handle_main_command(cmd):
                        self.console.print("[red]Invalid command[/red]")
                        await asyncio.sleep(1)
                elif self.current_view == "detail":
                    if not await self.handle_detail_command(cmd):
                        self.console.print("[red]Invalid command[/red]")
                        await asyncio.sleep(1)
                        
            except (KeyboardInterrupt, EOFError):
                break

    def handle_main_command(self, cmd: str) -> bool:
        if cmd == 'j' or cmd == 'down':
            self.selected_group = min(len(self.group_list) - 1, self.selected_group + 1)
            self.selected_item = 0
        elif cmd == 'k' or cmd == 'up':
            self.selected_group = max(0, self.selected_group - 1)
            self.selected_item = 0
        elif cmd == 'h' or cmd == 'left':
            if self.group_list:
                self.selected_item = max(0, self.selected_item - 1)
        elif cmd == 'l' or cmd == 'right':
            if self.group_list:
                current_group = self.group_list[self.selected_group][2]
                self.selected_item = min(len(current_group) - 1, self.selected_item + 1)
        elif cmd == 'enter' or cmd == '':
            if self.group_list:
                current_group = self.group_list[self.selected_group][2]
                if self.selected_item < len(current_group):
                    selected_item = current_group[self.selected_item]
                    if isinstance(selected_item, GitDir):
                        self.selected_dir = selected_item
                        self.current_view = "detail"
                        self.operation_result = ""
        else:
            return False
        return True

    async def handle_detail_command(self, cmd: str) -> bool:
        if cmd == 'b' or cmd == 'back':
            self.current_view = "main"
            self.operation_result = ""
        elif cmd == 'p':
            await self.handle_git_operation("pull")
        elif cmd == 'P':
            await self.handle_git_operation("push")
        elif cmd == 'f':
            await self.handle_git_operation("fetch")
        else:
            return False
        return True


async def main():
    app = MyWorkspaceTUI()
    await app.run()


if __name__ == '__main__':
    asyncio.run(main())