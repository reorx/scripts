#!/usr/bin/env -S uv run --script
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
from textual.containers import Container, Horizontal, Vertical
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


class GitOperationComplete(Message):
    def __init__(self, operation: str, result: str) -> None:
        self.operation = operation
        self.result = result
        super().__init__()


class DirectorySelected(Message):
    def __init__(self, git_dir: 'GitDir') -> None:
        self.git_dir = git_dir
        super().__init__()


class BackToMain(Message):
    pass


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


class GroupWidget(Static):
    """Widget representing a status group"""
    
    def __init__(self, status_key: tuple, emoji: str, dirs: List, *args, **kwargs):
        self.status_key = status_key
        self.emoji = emoji
        self.dirs = dirs
        super().__init__(*args, **kwargs)
        self.can_focus = True

    def compose(self) -> ComposeResult:
        if self.status_key:
            sync_status, working_status = self.status_key
            title = f"{self.emoji} {sync_status.value.title()} + {working_status.value.title()} ({len(self.dirs)})"
        else:
            title = f"{self.emoji} Non-Git Directories ({len(self.dirs)})"
        
        yield Label(title, classes="group-title")


class DirectoryWidget(Button):
    """Widget representing a directory"""
    
    def __init__(self, dir_obj, *args, **kwargs):
        self.dir_obj = dir_obj
        super().__init__(dir_obj.name, *args, **kwargs)


class MainView(Container):
    """Main view showing all groups and directories"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.groups = []

    def compose(self) -> ComposeResult:
        yield Vertical(id="main-content")

    async def update_content(self, groups: List):
        """Update the main view content"""
        self.groups = groups
        main_content = self.query_one("#main-content", Vertical)
        await main_content.remove_children()
        
        for group_key, emoji, dirs in groups:
            # Add group widget
            group_widget = GroupWidget(group_key, emoji, dirs, classes="group-widget")
            await main_content.mount(group_widget)
            
            # Add directories for this group
            dir_container = Horizontal(classes="directory-container")
            for dir_obj in dirs:
                if isinstance(dir_obj, GitDir):
                    dir_widget = DirectoryWidget(dir_obj, classes="directory-button git-dir")
                else:
                    dir_widget = DirectoryWidget(dir_obj, classes="directory-button regular-dir")
                await dir_container.mount(dir_widget)
            await main_content.mount(dir_container)


class DetailView(Container):
    """Detail view for a selected directory"""
    
    selected_dir: reactive[Optional[GitDir]] = reactive(None)
    operation_result: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("", id="detail-title"),
            Horizontal(
                Vertical(
                    Label("Git Status", classes="section-title"),
                    Static("", id="git-status"),
                    classes="status-section"
                ),
                Vertical(
                    Label("Git Operations", classes="section-title"),
                    Button("Pull", id="pull", variant="primary"),
                    Button("Push", id="push", variant="success"),
                    Button("Fetch", id="fetch", variant="warning"),
                    classes="operations-section"
                ),
                classes="detail-columns"
            ),
            Label("Detailed Status", classes="section-title"),
            Static("", id="detailed-status"),
            Static("", id="operation-result"),
            Button("Back", id="back", variant="error"),
            classes="detail-content"
        )

    def watch_selected_dir(self, git_dir: Optional[GitDir]) -> None:
        """Update detail view when selected directory changes"""
        if git_dir:
            self.query_one("#detail-title", Label).update(f"Directory Details - {git_dir.name}")
            
            status_text = []
            status_text.append(f"Directory: {git_dir.name}")
            status_text.append(f"Sync Status: {git_dir.sync_status.value if git_dir.sync_status else 'unknown'}")
            status_text.append(f"Working Dir: {git_dir.working_dir_status.value if git_dir.working_dir_status else 'unknown'}")
            
            if git_dir.ahead_behind != (0, 0):
                ahead, behind = git_dir.ahead_behind
                status_text.append(f"Ahead/Behind: {ahead}/{behind}")
            
            self.query_one("#git-status", Static).update("\n".join(status_text))
            self.query_one("#detailed-status", Static).update(git_dir.detailed_status or "No detailed status available")

    def watch_operation_result(self, result: str) -> None:
        """Update operation result display"""
        result_widget = self.query_one("#operation-result", Static)
        if result:
            result_widget.update(f"Operation Result:\n{result}")
            result_widget.add_class("operation-result")
        else:
            result_widget.update("")
            result_widget.remove_class("operation-result")

    @on(Button.Pressed, "#pull")
    async def handle_pull(self) -> None:
        if self.selected_dir:
            self.operation_result = "Running git pull..."
            result = await self.selected_dir.git_operation("pull")
            self.operation_result = result
            self.selected_dir.analyze_status()

    @on(Button.Pressed, "#push")
    async def handle_push(self) -> None:
        if self.selected_dir:
            self.operation_result = "Running git push..."
            result = await self.selected_dir.git_operation("push")
            self.operation_result = result
            self.selected_dir.analyze_status()

    @on(Button.Pressed, "#fetch")
    async def handle_fetch(self) -> None:
        if self.selected_dir:
            self.operation_result = "Running git fetch..."
            result = await self.selected_dir.git_operation("fetch")
            self.operation_result = result
            self.selected_dir.analyze_status()

    @on(Button.Pressed, "#back")
    def handle_back(self) -> None:
        self.post_message(BackToMain())


class MyWorkspaceApp(App):
    """MyWorkspace TUI Application with Textual"""
    
    CSS = """
    .group-widget {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: solid $primary;
        background: $surface;
    }
    
    .group-widget:focus {
        border: solid $accent;
        background: $primary;
    }
    
    .group-title {
        text-style: bold;
        color: $text;
    }
    
    .directory-container {
        layout: horizontal;
        height: auto;
        margin: 0 2;
    }
    
    .directory-button {
        margin: 0 1;
        min-width: 12;
        height: 3;
    }
    
    .git-dir {
        border: solid $success;
    }
    
    .regular-dir {
        border: solid $warning;
    }
    
    .detail-content {
        padding: 1;
    }
    
    .detail-columns {
        height: auto;
    }
    
    .status-section, .operations-section {
        width: 50%;
        padding: 1;
        border: solid $primary;
        margin: 1;
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
    }
    
    #main-content {
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
        self.main_view: Optional[MainView] = None
        self.detail_view: Optional[DetailView] = None

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

        self.main_view = MainView()
        await container.mount(self.main_view)
        await self.main_view.update_content(self.groups)

    def show_detail_view(self, git_dir: GitDir):
        """Show the detail view for a selected directory"""
        self.current_view = "detail"
        container = self.query_one("#main-container")
        container.remove_children()

        self.detail_view = DetailView()
        container.mount(self.detail_view)
        self.detail_view.selected_dir = git_dir

    @on(Click, ".directory-button")
    def on_directory_click(self, event: Click) -> None:
        """Handle directory button clicks"""
        if hasattr(event.widget, 'dir_obj') and isinstance(event.widget.dir_obj, GitDir):
            self.show_detail_view(event.widget.dir_obj)

    @on(BackToMain)
    async def on_back_to_main(self) -> None:
        """Handle back to main message"""
        await self.show_main_view()

    async def action_back(self) -> None:
        """Handle backspace key"""
        if self.current_view == "detail":
            await self.show_main_view()

    async def action_refresh(self) -> None:
        """Refresh the directory scan"""
        self.scan_directories()
        if self.current_view == "main":
            await self.show_main_view()

    def action_select(self) -> None:
        """Handle enter key"""
        if self.current_view == "main":
            try:
                focused = self.focused
                if isinstance(focused, DirectoryWidget) and isinstance(focused.dir_obj, GitDir):
                    self.show_detail_view(focused.dir_obj)
            except (NoMatches, AttributeError):
                pass

    def action_move_down(self) -> None:
        """Move focus down"""
        self.screen.focus_next()

    def action_move_up(self) -> None:
        """Move focus previous"""
        self.screen.focus_previous()

    def action_move_left(self) -> None:
        """Move focus left (in grid layouts)"""
        # Implementation depends on specific layout needs
        pass

    def action_move_right(self) -> None:
        """Move focus right (in grid layouts)"""
        # Implementation depends on specific layout needs
        pass


def main():
    app = MyWorkspaceApp()
    app.run()


if __name__ == '__main__':
    main()
