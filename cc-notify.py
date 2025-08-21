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
    parser.add_argument(
        '-t', '--type', help='Notification type (alert or banner)', default='alert', choices=['alert', 'banner']
    )
    parser.add_argument('--use-notifier', action='store_true', help='Use Notifier app instead of osascript')
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

    # Prepare notification title and message
    hook_event_name = hook_input.get('hook_event_name', 'Unknown Event')
    title = f'{project_name}: {hook_event_name}'

    # Use provided message or construct default
    message = args.message

    # Send notification
    if args.use_notifier:
        # Use Notifier app
        notifier_path = '/Applications/Utilities/Notifier.app/Contents/MacOS/Notifier'
        cmd = [notifier_path, '--type', args.type, '--title', title, '--message', message]

        # Add sound if specified
        if args.sound:
            cmd.extend(['--sound', args.sound])

        # Debug: print the whole Notifier command
        logger.debug(f'Notifier command: {" ".join(cmd)}')

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            logger.error(f'Error sending notification: {e}')
            logger.error(f'stderr: {e.stderr}')
            sys.exit(1)
        except FileNotFoundError:
            logger.error(f'Notifier not found at {notifier_path}. Please install Notifier.app')
            sys.exit(1)
    else:
        # Use osascript
        # Escape quotes in strings for AppleScript
        escaped_message = message.replace('"', '\\"')
        escaped_title = title.replace('"', '\\"')

        # Build osascript command
        script = f'display notification "{escaped_message}" with title "{escaped_title}"'

        # Add sound if specified
        if args.sound:
            script += f' sound name "{args.sound}"'

        cmd = ['osascript', '-e', script]

        # Debug: print the whole osascript command
        logger.debug(f'osascript command: {" ".join(cmd)}')

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            logger.error(f'Error sending notification: {e}')
            logger.error(f'stderr: {e.stderr}')
            sys.exit(1)


if __name__ == '__main__':
    main()
