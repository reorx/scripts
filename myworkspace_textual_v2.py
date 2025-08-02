#!/usr/bin/env python3
#
# /// script
# requires-python = ">=3.9"
# dependencies = ["textual>=0.45.0"]
# ///

import os
import subprocess
import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from enum import Enum
from typing import Optional, List, Dict, Tuple

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Button, Label
from textual.message import Message
from textual.reactive import reactive
from textual.events import Click
from textual import on
from textual.css.query import NoMatches


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

    async def git_operation(self, operation: str) -> str:
        try:
            with cdctx(self.name):
                result = subprocess.run(
                    ['git', operation],
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


class DirectoryButton(Button):
    """Button representing a directory"""
    
    def __init__(self, dir_obj, *args, **kwargs):
        self.dir_obj = dir_obj
        super().__init__(dir_obj.name, *args, **kwargs)
        
        # Set style based on directory type
        if isinstance(dir_obj, GitDir):
            self.add_class("git-dir")
        else:
            self.add_class("regular-dir")


class MyWorkspaceApp(App):
    """MyWorkspace TUI Application with Textual"""
    
    CSS = """
    .git-dir {
        background: $success-darken-2;
        border: solid $success;
        margin: 0 1;
        min-width: 12;
        height: 3;
    }
    
    .regular-dir {
        background: $warning-darken-2;
        border: solid $warning;
        margin: 0 1;
        min-width: 12;
        height: 3;
    }
    
    .git-dir:focus {
        border: solid $accent;
        background: $success;
    }
    
    .regular-dir:focus {
        border: solid $accent;
        background: $warning;
    }
    
    .group-title {
        text-style: bold;
        color: $text;
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $primary;
    }
    
    .detail-view {
        padding: 1;
    }
    
    .detail-section {
        margin: 1 0;
        padding: 1;
        border: solid $primary;
    }
    
    .section-title {
        text-style: bold;
        color: $accent;
        margin: 0 0 1 0;
    }
    
    .operation-result {
        background: $surface;
        border: solid $warning;
        padding: 1;
        margin: 1 0;
        min-height: 3;
    }
    
    #main-scroll {
        padding: 1;
    }
    """

    BINDINGS = [
        ("j", "move_down", "Move Down"),
        ("k", "move_up", "Move Up"),
        ("h", "move_left", "Move Left"),
        ("l", "move_right", "Move Right"),
        ("enter", "select", "Select"),
        ("backspace", "back", "Back"),
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.current_dir = os.getcwd()
        self.git_dirs: List[GitDir] = []
        self.regular_dirs: List[RegularDir] = []
        self.groups: List = []
        self.current_view = "main"
        self.selected_dir: Optional[GitDir] = None
        self.operation_result = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(id="main-container")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the application"""
        self.title = f"MyWorkspace TUI - {self.current_dir}"
        self.scan_directories()
        await self.show_main_view()

    def scan_directories(self):
        """Scan current directory for git repositories and regular directories"""
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
        groups_dict = {}
        for git_dir in self.git_dirs:
            key = (git_dir.sync_status, git_dir.working_dir_status)
            if key not in groups_dict:
                groups_dict[key] = []
            groups_dict[key].append(git_dir)

        # Create ordered group list
        self.groups = []
        for (sync_status, working_status), emoji in STATUS_PRIORITY_ORDER.items():
            key = (sync_status, working_status)
            if key in groups_dict:
                self.groups.append((key, emoji, groups_dict[key]))

        if self.regular_dirs:
            self.groups.append((None, "📁", self.regular_dirs))

    async def show_main_view(self):
        """Show the main view"""
        self.current_view = "main"
        container = self.query_one("#main-container")
        await container.remove_children()

        scroll_view = ScrollableContainer(id="main-scroll")
        await container.mount(scroll_view)

        for group_key, emoji, dirs in self.groups:
            # Add group title
            if group_key:
                sync_status, working_status = group_key
                title_text = f"{emoji} {sync_status.value.title()} + {working_status.value.title()} ({len(dirs)})"
            else:
                title_text = f"{emoji} Non-Git Directories ({len(dirs)})"
            
            group_title = Label(title_text, classes="group-title")
            await scroll_view.mount(group_title)
            
            # Add directory buttons in horizontal layout
            dir_container = Horizontal()
            await scroll_view.mount(dir_container)
            
            for dir_obj in dirs:
                dir_button = DirectoryButton(dir_obj)
                await dir_container.mount(dir_button)

    async def show_detail_view(self, git_dir: GitDir):
        """Show the detail view for a selected directory"""
        self.current_view = "detail"
        self.selected_dir = git_dir
        container = self.query_one("#main-container")
        await container.remove_children()

        detail_view = Vertical(classes="detail-view")
        await container.mount(detail_view)

        # Title
        title = Label(f"Directory Details - {git_dir.name}", classes="section-title")
        await detail_view.mount(title)

        # Git status section
        status_section = Vertical(classes="detail-section")
        await detail_view.mount(status_section)
        
        await status_section.mount(Label("Git Status", classes="section-title"))
        
        status_text = []
        status_text.append(f"Directory: {git_dir.name}")
        status_text.append(f"Sync Status: {git_dir.sync_status.value if git_dir.sync_status else 'unknown'}")
        status_text.append(f"Working Dir: {git_dir.working_dir_status.value if git_dir.working_dir_status else 'unknown'}")
        
        if git_dir.ahead_behind != (0, 0):
            ahead, behind = git_dir.ahead_behind
            status_text.append(f"Ahead/Behind: {ahead}/{behind}")
        
        await status_section.mount(Static("\n".join(status_text)))

        # Git operations section
        ops_section = Horizontal()
        await detail_view.mount(ops_section)
        
        pull_btn = Button("Pull", id="pull", variant="primary")
        push_btn = Button("Push", id="push", variant="success")
        fetch_btn = Button("Fetch", id="fetch", variant="warning")
        
        await ops_section.mount(pull_btn)
        await ops_section.mount(push_btn)
        await ops_section.mount(fetch_btn)

        # Detailed status section
        await detail_view.mount(Label("Detailed Status", classes="section-title"))
        detailed_status = Static(git_dir.detailed_status or "No detailed status available")
        await detail_view.mount(detailed_status)

        # Operation result section
        if self.operation_result:
            result_section = Static(f"Operation Result:\n{self.operation_result}", classes="operation-result")
            await detail_view.mount(result_section)

        # Back button
        back_btn = Button("Back", id="back", variant="error")
        await detail_view.mount(back_btn)

    @on(Click, ".git-dir")
    async def on_git_directory_click(self, event: Click) -> None:
        """Handle git directory button clicks"""
        if hasattr(event.widget, 'dir_obj') and isinstance(event.widget.dir_obj, GitDir):
            await self.show_detail_view(event.widget.dir_obj)

    @on(Button.Pressed, "#pull")
    async def handle_pull(self) -> None:
        if self.selected_dir:
            self.operation_result = "Running git pull..."
            await self.show_detail_view(self.selected_dir)  # Refresh view
            result = await self.selected_dir.git_operation("pull")
            self.operation_result = result
            self.selected_dir.analyze_status()
            await self.show_detail_view(self.selected_dir)  # Update view

    @on(Button.Pressed, "#push")
    async def handle_push(self) -> None:
        if self.selected_dir:
            self.operation_result = "Running git push..."
            await self.show_detail_view(self.selected_dir)
            result = await self.selected_dir.git_operation("push")
            self.operation_result = result
            self.selected_dir.analyze_status()
            await self.show_detail_view(self.selected_dir)

    @on(Button.Pressed, "#fetch")
    async def handle_fetch(self) -> None:
        if self.selected_dir:
            self.operation_result = "Running git fetch..."
            await self.show_detail_view(self.selected_dir)
            result = await self.selected_dir.git_operation("fetch")
            self.operation_result = result
            self.selected_dir.analyze_status()
            await self.show_detail_view(self.selected_dir)

    @on(Button.Pressed, "#back")
    async def handle_back(self) -> None:
        self.operation_result = ""
        await self.show_main_view()

    async def action_back(self) -> None:
        """Handle backspace key"""
        if self.current_view == "detail":
            self.operation_result = ""
            await self.show_main_view()

    async def action_refresh(self) -> None:
        """Refresh the directory scan"""
        self.scan_directories()
        if self.current_view == "main":
            await self.show_main_view()
        elif self.current_view == "detail" and self.selected_dir:
            self.selected_dir.analyze_status()
            await self.show_detail_view(self.selected_dir)

    async def action_select(self) -> None:
        """Handle enter key"""
        if self.current_view == "main":
            try:
                focused = self.focused
                if isinstance(focused, DirectoryButton) and isinstance(focused.dir_obj, GitDir):
                    await self.show_detail_view(focused.dir_obj)
            except (NoMatches, AttributeError):
                pass

    def action_move_down(self) -> None:
        """Move focus down"""
        self.screen.focus_next()

    def action_move_up(self) -> None:
        """Move focus previous"""
        self.screen.focus_previous()

    def action_move_left(self) -> None:
        """Move focus left"""
        # For horizontal layouts, this might need custom implementation
        pass

    def action_move_right(self) -> None:
        """Move focus right"""
        # For horizontal layouts, this might need custom implementation
        pass


def main():
    app = MyWorkspaceApp()
    app.run()


if __name__ == '__main__':
    main()