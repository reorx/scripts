---
name: macos-launchd-agents
description: Use when inspecting, disabling, unloading, re-enabling, or safely removing macOS app-installed launchd jobs, LaunchDaemons, LaunchAgents, plist startup items, login/background agents, or privileged helpers under /Library/PrivilegedHelperTools. Trigger when the user mentions launchctl, plist agents, app helpers, background items, "disable this agent", "unload daemon", or paths under /Library/LaunchDaemons, /Library/LaunchAgents, ~/Library/LaunchAgents, or /Library/PrivilegedHelperTools.
---

# macOS Launchd Agents

## Overview

Use this skill for macOS app-installed launchd jobs: LaunchDaemons, LaunchAgents, and privileged helper tools. Prefer launchd state changes over deleting files first; disabling and unloading are reversible and easier to verify.

## Quick Start

Use the helper script from this skill directory:

```bash
python3 scripts/launchd_agent.py search CleanMyMac
python3 scripts/launchd_agent.py inspect com.macpaw.CleanMyMac5.Agent
python3 scripts/launchd_agent.py disable /Library/LaunchDaemons/com.macpaw.CleanMyMac5.Agent.plist --confirm --admin-prompt
python3 scripts/launchd_agent.py verify com.macpaw.CleanMyMac5.Agent --domain system
```

If the script is not enough, run the equivalent launchctl commands directly and report exact results to the user.

## Workflow

1. Identify the target.
   - The user may provide a label, plist path, process name, or helper path.
   - Search these locations first: `/Library/LaunchDaemons`, `/Library/LaunchAgents`, `~/Library/LaunchAgents`, and `/Library/PrivilegedHelperTools`.
   - Read the plist with `plutil -p` or the helper script. Confirm `Label`, `Program`, `ProgramArguments`, `MachServices`, `KeepAlive`, and `RunAtLoad`.

2. Determine the launchd domain.
   - `/Library/LaunchDaemons/*.plist` normally uses `system`.
   - `~/Library/LaunchAgents/*.plist` normally uses `gui/$(id -u)`.
   - `/Library/LaunchAgents/*.plist` is a global agent definition usually loaded into a user GUI domain.
   - For uncertain cases, inspect `system/<label>`, `gui/$(id -u)/<label>`, and `user/$(id -u)/<label>`.

3. Inspect current state before changing it.

```bash
launchctl print system/<label>
launchctl print gui/$(id -u)/<label>
launchctl print-disabled system | rg '<label>|macpaw|vendor'
ps -axo pid=,args= | rg '[l]abel-or-program-name'
```

It is normal for `launchctl print` to fail with "Could not find service" after a job has been booted out.

4. Disable and unload.

For a system LaunchDaemon, use an administrator prompt because non-interactive `sudo` usually cannot ask for a password:

```bash
osascript -e 'do shell script "launchctl disable system/com.example.Agent; launchctl bootout system /Library/LaunchDaemons/com.example.Agent.plist || true" with administrator privileges'
```

For a user LaunchAgent:

```bash
launchctl disable gui/$(id -u)/com.example.Agent
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.example.Agent.plist" || true
```

5. Verify.

```bash
launchctl print-disabled system | rg 'com.example.Agent'
launchctl print system/com.example.Agent
ps -axo pid=,args= | rg '[c]om.example.Agent'
```

Expected disabled state:

```text
"com.example.Agent" => disabled
```

Expected unloaded state:

```text
Could not find service "com.example.Agent" in domain for system
```

## Safety Rules

- Do not delete plist files or privileged helper binaries unless the user explicitly asks for removal.
- If the user asks to "disable", leave files in place and only change launchd state.
- For removal, disable and boot out first, then report the exact plist and helper paths that would be removed. Prefer moving files to a dated quarantine directory over immediate deletion when the user has not demanded deletion.
- Do not attempt to disable or remove Apple system daemons protected by SIP. Explain the limitation instead.
- Quote all user-provided paths and labels. App helper names often contain dots and may appear in shell commands.
- Expect apps to reinstall their privileged helper the next time the app starts or updates. Mention this if the daemon returns after being disabled.
- When a privileged command needs a password in a non-interactive shell, use `osascript ... with administrator privileges` rather than hanging on `sudo`.

## Re-enable Pattern

```bash
sudo launchctl enable system/com.example.Agent
sudo launchctl bootstrap system /Library/LaunchDaemons/com.example.Agent.plist
```

Or with the helper script:

```bash
python3 scripts/launchd_agent.py enable /Library/LaunchDaemons/com.example.Agent.plist --confirm --admin-prompt
```

## Available Scripts

- `scripts/launchd_agent.py` - Search, inspect, disable, verify, and re-enable macOS launchd jobs. Disable and enable actions require `--confirm`.
