#!/usr/bin/env python3

import json
import sys
import os
import subprocess
import argparse
import logging
from pathlib import Path


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Send macOS notification for Claude Code hooks')
    parser.add_argument('-m', '--message', help='Notification message', default='please pass a message')
    parser.add_argument('-s', '--sound', help='Sound name (from /System/Library/Sounds)', default='')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--icon', help='Custom icon path (overrides default)')
    args = parser.parse_args()

    # Configure logging
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
    logger = logging.getLogger(__name__)

    # Read JSON input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        logger.error(f'Error parsing JSON input: {e}')
        sys.exit(1)

    # Debug: print parsed hook input
    logger.debug(f'Parsed hook input:\n{json.dumps(hook_input, indent=2)}')

    # Get project name from environment variable
    project_dir = os.environ.get('CLAUDE_PROJECT_DIR', '')
    project_name = os.path.basename(project_dir) if project_dir else 'Unknown Project'

    # Debug: print CLAUDE_PROJECT_DIR
    logger.debug(f'CLAUDE_PROJECT_DIR: {project_dir}')

    # Get the icon path
    if args.icon:
        icon_path = Path(args.icon)
    else:
        script_dir = Path(__file__).parent
        icon_path = script_dir / 'assets/icons/claude.icns'

    # Debug: print icon path and its stat
    logger.debug(f'Icon path: {icon_path}')
    if icon_path.exists():
        stat = icon_path.stat()
        logger.debug(f'Icon file stat: size={stat.st_size} bytes, mode={oct(stat.st_mode)}, modified={stat.st_mtime}')
    else:
        logger.debug(f'Icon file does not exist at {icon_path}')

    # Prepare notification title and message
    hook_event_name = hook_input.get('hook_event_name', 'Unknown Event')
    title = f'{project_name}: {hook_event_name}'

    # Use provided message or construct default
    message = args.message

    # Build terminal-notifier command
    cmd = ['terminal-notifier', '-title', title, '-message', message, '-appIcon', str(icon_path)]

    # Add sound if not default
    if args.sound:
        cmd.extend(['-sound', args.sound])

    # Debug: print the whole terminal-notifier command
    logger.debug(f'Terminal-notifier command: {" ".join(cmd)}')

    # Send notification
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f'Error sending notification: {e}')
        sys.exit(1)
    except FileNotFoundError:
        logger.error('terminal-notifier not found. Please install it: brew install terminal-notifier')
        sys.exit(1)


if __name__ == '__main__':
    main()
