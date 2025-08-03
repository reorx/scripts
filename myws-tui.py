#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.9"
# dependencies = ["textual>=0.45.0"]
# ///

import os
import subprocess
import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from enum import Enum
from typing import Optional, List, Dict, Tuple

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Button, Label, LoadingIndicator, Input, RichLog, DataTable
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


def analyze_git_directory(dir_name: str) -> Optional['GitDir']:
    """Worker function to analyze a git directory - safe for threading"""
    try:
        if not Path(dir_name, '.git').exists():
            return None
        
        # Use absolute path to avoid working directory conflicts in threads
        abs_path = os.path.abspath(dir_name)
        git_dir = GitDir(dir_name)
        
        # Perform all git operations with absolute paths in the worker thread
        with cdctx(abs_path):
            git_dir.analyze_status(use_cwd=True)
        
        return git_dir
    except Exception as e:
        # Log error but don't print to avoid TUI interference  
        return None


class GitDir:
    def __init__(self, name: str):
        self.name = name
        self.sync_status: Optional[SyncStatus] = None
        self.working_dir_status: Optional[WorkingDirStatus] = None
        self.detailed_status: str = ""
        self.ahead_behind: Tuple[int, int] = (0, 0)

    def analyze_status(self, use_cwd: bool = False) -> None:
        if use_cwd:
            # Already in correct directory, don't change directory
            if not Path('.git').exists():
                raise ValueError(f'{self.name} is not a git repository')
            self._check_sync_status()
            self._check_working_dir_status()
            self._get_detailed_status()
        else:
            # Change to directory (original behavior)
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
                ['git', '-c', 'color.ui=always', 'status', '--short', '--branch'],
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
    
    
    .operation-result {
        background: $surface;
        border: solid $warning;
        padding: 1;
        margin: 1 0;
        min-height: 3;
    }
    
    .compact-button {
        min-width: 8;
        height: 3;
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
    
    .shell-panel {
        border: solid $accent;
        margin: 1 0;
        padding: 1;
        height: 20;
    }
    
    .shell-output {
        height: 13;
        background: $surface;
        border: solid $secondary;
        margin: 0 0 1 0;
        padding: 1;
    }
    
    .shell-input {
        height: 3;
        border: solid $accent;
        background: $surface;
    }
    
    .shell-input:focus {
        border: solid $primary;
    }
    
    .status-table {
        height: 4;
        border: none;
        margin: 1 0;
    }
    
    .shell-button {
        background: purple;
        color: white;
    }
    
    .shell-button:hover {
        background: #8B008B;
    }
    
    .ops-buttons-left {
        align: left middle;
    }
    
    .ops-buttons-right {
        align: right middle;
    }
    
    .detailed-status-log {
        height: auto;
        min-height: 3;
        border: none;
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
        self.shell_output: List[str] = []
        self.shell_panel_visible = False

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
            # Get all directories
            all_dirs = [item for item in os.listdir('.') 
                       if item.strip() and Path(item).is_dir()]
            
            # Separate git and regular directories
            git_candidates = []
            for item in all_dirs:
                if Path(item, '.git').exists():
                    git_candidates.append(item)
                else:
                    self.regular_dirs.append(RegularDir(item))
            
            # Process git directories with ThreadPoolExecutor
            if git_candidates:
                # Calculate thread count: CPU cores / 2, max 4
                cpu_count = os.cpu_count() or 4
                thread_count = min(4, max(1, cpu_count // 2))
                #raise Exception(f'total git dirs: {len(git_candidates)}, thread count: {thread_count}')
                
                with ThreadPoolExecutor(max_workers=1) as executor:
                    results = list(executor.map(analyze_git_directory, git_candidates))
                    
                # Filter out None results and add to git_dirs
                self.git_dirs = [git_dir for git_dir in results if git_dir is not None]
                    
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
        title = Label(f"Directory Details", classes="section-title")
        await detail_view.mount(title)

        # Interactive Shell section (initially hidden)
        if self.shell_panel_visible:
            await self._mount_shell_panel(detail_view, git_dir)

        # Git status DataTable (no container panel)
        status_table = DataTable(show_header=False, zebra_stripes=True, classes="status-table")
        status_table.cursor_type = "none"
        await detail_view.mount(status_table)
        
        # Add columns (no headers will be shown)
        status_table.add_column("Property", width=15)
        status_table.add_column("Value", width=30)
        
        # Add rows with git status data
        status_table.add_row("Directory", git_dir.name)
        status_table.add_row("Sync Status", git_dir.sync_status.value if git_dir.sync_status else 'unknown')
        status_table.add_row("Working Dir", git_dir.working_dir_status.value if git_dir.working_dir_status else 'unknown')
        
        if git_dir.ahead_behind != (0, 0):
            ahead, behind = git_dir.ahead_behind
            status_table.add_row("Ahead/Behind", f"{ahead}/{behind}")

        # Git operations section with back button
        ops_section = Horizontal()
        await detail_view.mount(ops_section)
        
        # Left side buttons
        left_buttons = Horizontal(classes="ops-buttons-left")
        await ops_section.mount(left_buttons)
        
        pull_btn = Button("Pull", id="pull", variant="primary", classes="compact-button")
        push_btn = Button("Push", id="push", variant="success", classes="compact-button")
        fetch_btn = Button("Fetch", id="fetch", variant="warning", classes="compact-button")
        shell_btn = Button("Shell", id="toggle-shell", variant="error", classes="compact-button")
        
        await left_buttons.mount(pull_btn)
        await left_buttons.mount(push_btn)
        await left_buttons.mount(fetch_btn)
        await left_buttons.mount(shell_btn)
        
        # Right side button
        right_buttons = Horizontal(classes="ops-buttons-right")
        await ops_section.mount(right_buttons)
        
        back_btn = Button("Back", id="back", variant="default", classes="compact-button")
        await right_buttons.mount(back_btn)

        # Detailed status section with border
        detail_status_section = Vertical(classes="detail-section")
        detail_status_section.border_title = "Detailed Status"
        await detail_view.mount(detail_status_section)
        detailed_status = RichLog(classes="detailed-status-log")
        if git_dir.detailed_status:
            detailed_status.write(git_dir.detailed_status)
        else:
            detailed_status.write("No detailed status available")
        await detail_status_section.mount(detailed_status)

        # Operation result section
        if self.operation_result:
            result_section = Static(f"Operation Result:\n{self.operation_result}", classes="operation-result")
            await detail_view.mount(result_section)

    async def _mount_shell_panel(self, detail_view: Vertical, git_dir: GitDir):
        """Mount the interactive shell panel"""
        shell_section = Vertical(classes="shell-panel", id="shell-panel")
        shell_section.border_title = "Interactive Shell"
        
        # Find the position after the operations section
        ops_section = detail_view.children[-3]  # Should be the operations section (3rd from end: ops, detailed status, back button)
        detail_view.mount(shell_section, after=ops_section)
        
        # Shell input
        shell_input = Input(placeholder="Enter command...", id="shell-input", classes="shell-input")
        await shell_section.mount(shell_input)
        
        # Shell output display
        shell_output = RichLog(id="shell-output", classes="shell-output")
        shell_output.write(f"Shell initialized in: {git_dir.name}")
        shell_output.write(f"Working directory: {os.path.abspath(git_dir.name)}")
        
        # Display previous shell output if any
        for line in self.shell_output:
            shell_output.write(line)
            
        await shell_section.mount(shell_output)
        
        # Set focus to shell input
        shell_input.focus()

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

    @on(Button.Pressed, "#toggle-shell")
    async def handle_toggle_shell(self) -> None:
        """Toggle shell panel visibility"""
        if self.selected_dir:
            self.shell_panel_visible = not self.shell_panel_visible
            
            if self.shell_panel_visible:
                # Show shell panel
                detail_view = self.query_one(".detail-view")
                await self._mount_shell_panel(detail_view, self.selected_dir)
            else:
                # Hide shell panel
                try:
                    shell_panel = self.query_one("#shell-panel")
                    await shell_panel.remove()
                except:
                    pass  # Panel might not exist

    @on(Button.Pressed, "#back")
    async def handle_back(self) -> None:
        self.operation_result = ""
        self.shell_output = []  # Clear shell output when going back
        self.shell_panel_visible = False  # Reset shell panel state
        await self.show_main_view()

    @on(Input.Submitted, "#shell-input")
    async def handle_shell_command(self, message: Input.Submitted) -> None:
        """Handle shell command submission"""
        if self.selected_dir and message.value.strip():
            command = message.value.strip()
            
            # Clear the input
            shell_input = self.query_one("#shell-input", Input)
            shell_input.value = ""
            
            # Update shell output display
            shell_output = self.query_one("#shell-output", RichLog)
            shell_output.write(f"$ {command}")
            
            # Execute command using worker
            self.execute_shell_command(command, shell_output)

    @work
    async def execute_shell_command(self, command: str, shell_output: RichLog):
        """Execute shell command in the selected directory"""
        if not self.selected_dir:
            return
            
        try:
            with cdctx(self.selected_dir.name):
                # Execute the command
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30  # 30 second timeout
                )
                
                # Display output
                if result.stdout:
                    for line in result.stdout.strip().split('\n'):
                        shell_output.write(line)
                        self.shell_output.append(line)
                
                if result.stderr:
                    for line in result.stderr.strip().split('\n'):
                        shell_output.write(f"[red]ERROR: {line}[/red]")
                        self.shell_output.append(f"ERROR: {line}")
                
                if result.returncode != 0:
                    shell_output.write(f"[red]Command exited with code {result.returncode}[/red]")
                    self.shell_output.append(f"Command exited with code {result.returncode}")
                    
        except subprocess.TimeoutExpired:
            shell_output.write("[red]Command timed out after 30 seconds[/red]")
            self.shell_output.append("Command timed out after 30 seconds")
        except Exception as e:
            shell_output.write(f"[red]Error executing command: {str(e)}[/red]")
            self.shell_output.append(f"Error executing command: {str(e)}")

    async def action_back(self) -> None:
        """Handle backspace key"""
        if self.current_view == "detail":
            self.operation_result = ""
            self.shell_output = []  # Clear shell output when going back
            self.shell_panel_visible = False  # Reset shell panel state
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
