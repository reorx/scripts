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
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Button, Label, LoadingIndicator
from textual.message import Message
from textual.reactive import reactive
from textual.events import Click
from textual import on, work
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
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.DIRTY), "🔴"),
    ((SyncStatus.SYNC, WorkingDirStatus.DIRTY), "🟡"),
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.CLEAN), "🟡"),
    ((SyncStatus.OUT_OF_SYNC, WorkingDirStatus.UNTRACKED), "🟡"),
    ((SyncStatus.SYNC, WorkingDirStatus.UNTRACKED), "🟢"),
    ((SyncStatus.SYNC, WorkingDirStatus.CLEAN), "🟢"),
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


class DirectoryWidget(Static):
    """Focusable directory widget"""
    
    DEFAULT_CSS = """
    DirectoryWidget {
        background: #404040;
        margin: 0 1;
        padding: 0 1;
        min-width: 8;
        max-width: 20;
        width: auto;
        height: 1;
        text-align: center;
        display: block;
    }
    DirectoryWidget:focus {
        background: $accent;
        text-style: bold underline;
    }
    DirectoryWidget.git-dir {
        background: #404040;
    }
    DirectoryWidget.git-dir:focus {
        background: $accent;
        text-style: bold underline;
    }
    DirectoryWidget.regular-dir {
        background: #404040;
    }
    DirectoryWidget.regular-dir:focus {
        background: $accent;
        text-style: bold underline;
    }
    """
    
    def __init__(self, dir_obj, *args, **kwargs):
        self.dir_obj = dir_obj
        super().__init__(dir_obj.name, *args, **kwargs)
        self.can_focus = True
        
        if isinstance(dir_obj, GitDir):
            self.add_class("git-dir")
        else:
            self.add_class("regular-dir")


class MyWorkspaceApp(App):
    """MyWorkspace TUI Application with Textual"""
    
    CSS = """
    .group-title {
        text-style: bold;
        color: $text;
        margin: 1 0;
        background: $surface;
        height: auto;
        min-height: 1;
    }
    
    .group-title.selected {
        background: $primary;
        color: $text;
    }
    
    .directories-row {
        layout: horizontal;
        margin: 0 1 1 1;
        padding: 0;
        width: 100%;
        height: auto;
        min-height: 1;
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
    
    .compact-button {
        min-width: 8;
        margin: 0 1;
        padding: 0 1;
    }
    
    #main-scroll {
        padding: 1;
        height: 1fr;
        width: 100%;
    }
    
    #main-container {
        height: 1fr;
    }
    
    .loading-container {
        height: 1fr;
        width: 100%;
        align: center middle;
    }
    
    .loading-text {
        text-align: center;
        margin: 1 0;
        color: $accent;
    }
    
    /* Allow nested containers to size to content */
    Vertical {
        height: auto;
    }
    
    Horizontal {
        height: auto;
    }
    
    .dirs-container {
        height: auto;
    }
    """

    BINDINGS = [
        ("j", "next_group", "Next Group"),
        ("k", "prev_group", "Previous Group"),
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
        self.current_group_index = 0
        self.group_widgets: List[List[DirectoryWidget]] = []
        self.is_loading = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(id="main-container")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the application"""
        self.title = f"MyWorkspace TUI - {self.current_dir}"
        await self.show_loading("Scanning directories...")
        self.load_directories()

    @work
    async def load_directories(self):
        """Load directories in background"""
        await asyncio.sleep(0.1)  # Give UI time to update
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
            self.groups.append((None, "⚪", self.regular_dirs))

    async def show_loading(self, message: str = "Loading..."):
        """Show loading indicator with message"""
        self.is_loading = True
        container = self.query_one("#main-container")
        await container.remove_children()
        
        loading_container = Vertical(classes="loading-container")
        await container.mount(loading_container)
        
        loading_text = Label(message, classes="loading-text")
        loading_indicator = LoadingIndicator()
        
        await loading_container.mount(loading_text)
        await loading_container.mount(loading_indicator)

    async def show_main_view(self):
        """Show the main view"""
        self.current_view = "main"
        self.is_loading = False
        container = self.query_one("#main-container")
        await container.remove_children()

        scroll_view = ScrollableContainer(id="main-scroll")
        await container.mount(scroll_view)

        self.group_widgets = []

        for group_index, (group_key, emoji, dirs) in enumerate(self.groups):
            # Add group title
            if group_key:
                sync_status, working_status = group_key
                title_text = f"{emoji} {sync_status.value.title()} + {working_status.value.title()} ({len(dirs)})"
            else:
                title_text = f"{emoji} Non-Git Directories ({len(dirs)})"
            
            group_title = Label(title_text, classes="group-title")
            if group_index == self.current_group_index:
                group_title.add_class("selected")
            await scroll_view.mount(group_title)
            
            # Create rows of directories (wrap every 6 items)
            dirs_container = Vertical(classes="dirs-container")
            await scroll_view.mount(dirs_container)
            
            # Add directory widgets in rows
            group_dir_widgets = []
            dirs_per_row = 6
            for i in range(0, len(dirs), dirs_per_row):
                row_dirs = dirs[i:i + dirs_per_row]
                row_container = Horizontal(classes="directories-row")
                await dirs_container.mount(row_container)
                
                for dir_obj in row_dirs:
                    dir_widget = DirectoryWidget(dir_obj)
                    group_dir_widgets.append(dir_widget)
                    await row_container.mount(dir_widget)
            
            self.group_widgets.append(group_dir_widgets)

        # Focus on first directory of current group
        if self.groups and self.group_widgets:
            if self.group_widgets[self.current_group_index]:
                self.group_widgets[self.current_group_index][0].focus()

    async def show_detail_view(self, git_dir: GitDir):
        """Show the detail view for a selected directory"""
        self.current_view = "detail"
        self.selected_dir = git_dir
        container = self.query_one("#main-container")
        await container.remove_children()

        # Create scrollable container for detail view
        scroll_view = ScrollableContainer()
        await container.mount(scroll_view)
        
        detail_view = Vertical(classes="detail-view")
        await scroll_view.mount(detail_view)

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
        
        pull_btn = Button("Pull", id="pull", variant="primary", classes="compact-button")
        push_btn = Button("Push", id="push", variant="success", classes="compact-button")
        fetch_btn = Button("Fetch", id="fetch", variant="warning", classes="compact-button")
        
        await ops_section.mount(pull_btn)
        await ops_section.mount(push_btn)
        await ops_section.mount(fetch_btn)

        # Detailed status section with border
        detail_status_section = Vertical(classes="detail-section")
        await detail_view.mount(detail_status_section)
        await detail_status_section.mount(Label("Detailed Status", classes="section-title"))
        detailed_status = Static(git_dir.detailed_status or "No detailed status available")
        await detail_status_section.mount(detailed_status)

        # Operation result section
        if self.operation_result:
            result_section = Static(f"Operation Result:\n{self.operation_result}", classes="operation-result")
            await detail_view.mount(result_section)

        # Back button
        back_btn = Button("Back", id="back", variant="error", classes="compact-button")
        await detail_view.mount(back_btn)

    @on(Click, "DirectoryWidget")
    async def on_directory_click(self, event: Click) -> None:
        """Handle directory clicks"""
        if hasattr(event.widget, 'dir_obj') and isinstance(event.widget.dir_obj, GitDir):
            await self.show_detail_view(event.widget.dir_obj)

    @on(Button.Pressed, "#pull")
    async def handle_pull(self) -> None:
        if self.selected_dir:
            await self.show_loading(f"Running git pull in {self.selected_dir.name}...")
            self.perform_git_operation("pull")

    @work
    async def perform_git_operation(self, operation: str):
        """Perform git operation in background"""
        if self.selected_dir:
            result = await self.selected_dir.git_operation(operation)
            self.operation_result = result
            self.selected_dir.analyze_status()
            await self.show_detail_view(self.selected_dir)

    @on(Button.Pressed, "#push")
    async def handle_push(self) -> None:
        if self.selected_dir:
            await self.show_loading(f"Running git push in {self.selected_dir.name}...")
            self.perform_git_operation("push")

    @on(Button.Pressed, "#fetch")
    async def handle_fetch(self) -> None:
        if self.selected_dir:
            await self.show_loading(f"Running git fetch in {self.selected_dir.name}...")
            self.perform_git_operation("fetch")

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
        await self.show_loading("Refreshing directories...")
        self.refresh_directories()

    @work
    async def refresh_directories(self):
        """Refresh directories in background"""
        await asyncio.sleep(0.1)  # Give UI time to update
        self.scan_directories()
        if self.current_view == "main":
            await self.show_main_view()
        elif self.current_view == "detail" and self.selected_dir:
            self.selected_dir.analyze_status()
            await self.show_detail_view(self.selected_dir)

    async def action_select(self) -> None:
        """Handle enter key"""
        if self.current_view == "main":
            focused = self.focused
            if isinstance(focused, DirectoryWidget) and isinstance(focused.dir_obj, GitDir):
                await self.show_detail_view(focused.dir_obj)

    async def update_group_selection(self) -> None:
        """Update group title selection without rebuilding the entire UI"""
        try:
            # Find all group title labels and update their selection state
            group_titles = self.query(".group-title")
            for index, title in enumerate(group_titles):
                if index == self.current_group_index:
                    title.add_class("selected")
                else:
                    title.remove_class("selected")
            
            # Focus on first directory of current group
            if self.groups and self.group_widgets:
                if self.group_widgets[self.current_group_index]:
                    self.group_widgets[self.current_group_index][0].focus()
        except Exception:
            # Fallback to full refresh if update fails
            await self.show_main_view()

    async def action_next_group(self) -> None:
        """Move to next group and focus first directory"""
        if self.current_view == "main" and self.groups:
            self.current_group_index = (self.current_group_index + 1) % len(self.groups)
            await self.update_group_selection()

    async def action_prev_group(self) -> None:
        """Move to previous group and focus first directory"""
        if self.current_view == "main" and self.groups:
            self.current_group_index = (self.current_group_index - 1) % len(self.groups)
            await self.update_group_selection()


    def action_move_left(self) -> None:
        """Move focus left within current group"""
        if self.current_view == "main" and self.group_widgets:
            current_group = self.group_widgets[self.current_group_index]
            if current_group:
                focused = self.focused
                if isinstance(focused, DirectoryWidget) and focused in current_group:
                    current_index = current_group.index(focused)
                    if current_index > 0:
                        current_group[current_index - 1].focus()
                    else:
                        current_group[-1].focus()  # Wrap to end

    def action_move_right(self) -> None:
        """Move focus right within current group"""
        if self.current_view == "main" and self.group_widgets:
            current_group = self.group_widgets[self.current_group_index]
            if current_group:
                focused = self.focused
                if isinstance(focused, DirectoryWidget) and focused in current_group:
                    current_index = current_group.index(focused)
                    if current_index + 1 < len(current_group):
                        current_group[current_index + 1].focus()
                    else:
                        current_group[0].focus()  # Wrap to beginning


def main():
    app = MyWorkspaceApp()
    app.run()


if __name__ == '__main__':
    main()
